"""Two-tier analysis for ``eval/2`` (PR-AI-VL-242): per-tier dimensions with intervals, the paired comparison, floors, the
optional Florence-2 comparator and the escalation simulation. Pure: it takes parsed documents and returns numbers.

Inputs are the case set and its human labels, one ``evidence/2`` file per tier for that same case set and plan, and optionally
a Florence-2 comparator file. Nothing here reads a file, runs a model or keeps text; the outputs are counts, rates and
intervals with no case id, so a report can be shared without exposing which image said what.
"""

from __future__ import annotations

import re
from collections import Counter
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Any

from src.review.findings import Category
from tools.qualification.vl220 import eval2
from tools.qualification.vl220.contract import ContractViolation
from tools.qualification.vl220.eval2 import CaseResult, CaseSet, Evidence, LabelSet
from tools.qualification.vl220.eval2_scoring import (
    ImageOutcome,
    PairOutcome,
    image_metrics,
    image_outcome,
    outcomes,
    pair_metrics,
    resource_metrics,
    structured_metrics,
    subject_count_agrees,
)
from tools.qualification.vl242 import stats

COMPARATOR_SCHEMA = "stablenew.vl242.comparator_evidence/1"
FLORENCE_ID = "florence2-caption"
#: What the Florence-2 adapter (caption and object labels) can answer in this contract, and why not the rest.
FLORENCE_DIMENSIONS: tuple[str, ...] = ("multi_subject",)
FLORENCE_CANNOT: Mapping[str, str] = {
    "image_detection": "no defect output: captions and object labels only",
    "finding_triage": "no defect categories or regions",
    "before_after": "no comparison output",
    "structured_validity": "not a structured-answer system",
}

RULE_NEVER = "never"
RULE_ALWAYS = "always"
RULE_ON_DEFECT = "on_defect"
RULE_ON_CLEAN = "on_clean"
RULE_DEEP_ONLY = "deep_only"
RULES: tuple[str, ...] = (RULE_NEVER, RULE_ALWAYS, RULE_ON_DEFECT, RULE_ON_CLEAN, RULE_DEEP_ONLY)
RULE_TEXT: Mapping[str, str] = {
    RULE_NEVER: "deep tier never (fast alone; also the operator who never asks)",
    RULE_ALWAYS: "deep tier always, after the fast look",
    RULE_ON_DEFECT: "deep tier only when the fast tier reports a defect (or gives no usable answer)",
    RULE_ON_CLEAN: "deep tier only when the fast tier reports clean (or gives no usable answer)",
    RULE_DEEP_ONLY: "deep tier alone (the operator asks for the deep look directly)",
}
CONDITIONAL_RULES: tuple[str, ...] = (RULE_ON_DEFECT, RULE_ON_CLEAN)

NOT_EVALUATED: Mapping[str, str] = {
    "prompt_adherence": "the export carries no prompt and no human element reference",
    "object_hallucination": "the export carries no human object list; clean-image findings are the hallucination proxy",
    "multi_subject_identity": "the export records subject counts, not whether each subject stayed the same",
}


class AnalysisRefused(ValueError):
    def __init__(self, code: str) -> None:
        super().__init__(code)
        self.code = code


# ---------------------------------------------------------------------------------------------- light statistics


def _detection(rows: Sequence[ImageOutcome], idx: Sequence[int]) -> tuple[int, int, int, int]:
    tp = fn = tn = nc = 0
    for i in idx:
        row = rows[i]
        if row.truth == eval2.VERDICT_DEFECTIVE:
            if row.flagged:
                tp += 1
            else:
                fn += 1
        elif row.predicted == eval2.VERDICT_CLEAN:
            tn += 1
        else:
            nc += 1
    return tp, fn, tn, nc


def f1(rows: Sequence[ImageOutcome], idx: Sequence[int]) -> float | None:
    tp, fn, _, nc = _detection(rows, idx)
    denominator = 2 * tp + fn + nc
    return None if denominator == 0 else 2 * tp / denominator


def balanced_accuracy(rows: Sequence[ImageOutcome], idx: Sequence[int]) -> float | None:
    tp, fn, tn, nc = _detection(rows, idx)
    if tp + fn == 0 or tn + nc == 0:
        return None
    return (tp / (tp + fn) + tn / (tn + nc)) / 2


def finding_precision(rows: Sequence[ImageOutcome], idx: Sequence[int]) -> float | None:
    tp = sum(rows[i].tp for i in idx if rows[i].truth == eval2.VERDICT_DEFECTIVE)
    fp = sum(rows[i].fp for i in idx if rows[i].truth == eval2.VERDICT_DEFECTIVE)
    return None if tp + fp == 0 else tp / (tp + fp)


def _strata(rows: Sequence[ImageOutcome]) -> list[list[int]]:
    return [
        [i for i, row in enumerate(rows) if row.truth == eval2.VERDICT_CLEAN],
        [i for i, row in enumerate(rows) if row.truth == eval2.VERDICT_DEFECTIVE],
    ]


def _boot(strata: Sequence[Sequence[int]], statistic: Any, offset: int = 0) -> dict[str, Any]:
    return stats.bootstrap(
        strata, statistic, resamples=eval2.BOOTSTRAP_RESAMPLES, seed=eval2.BOOTSTRAP_SEED + offset,
        confidence=eval2.CONFIDENCE,
    ).record()  # fmt: skip


def _wilson(k: int, n: int) -> dict[str, Any]:
    two = stats.wilson(k, n)
    one = stats.wilson(k, n, stats.Z_ONE_SIDED_95)
    return {
        "k": k, "n": n, "point": None if n == 0 else round(k / n, 6),
        "low": two[0] if two else None, "high": two[1] if two else None,
        "lower_95": one[0] if one else None, "upper_95": one[1] if one else None,
    }  # fmt: skip


# -------------------------------------------------------------------------------------------------------- tiers


@dataclass(frozen=True, slots=True)
class TierLimits:
    """Per-case ceilings and the median time budget a tier is judged against (bound into the plan)."""

    max_wall_seconds: float
    max_peak_working_set_bytes: int
    median_seconds_budget: float

    def record(self) -> dict[str, Any]:
        return {
            "max_wall_seconds": self.max_wall_seconds,
            "max_peak_working_set_bytes": self.max_peak_working_set_bytes,
            "median_seconds_budget": self.median_seconds_budget,
        }


@dataclass(frozen=True, slots=True)
class TierAnalysis:
    summary: dict[str, Any]
    images: tuple[ImageOutcome, ...]
    pairs: tuple[PairOutcome, ...]


def summarize_rows(
    images: Sequence[ImageOutcome], pairs: Sequence[PairOutcome], *, offset: int = 0
) -> dict[str, Any]:
    """Image and pair dimensions with their intervals (shared by tiers, floors and escalated answers)."""

    metrics = image_metrics(images)
    detection = metrics["image_detection"]
    strata = _strata(images)
    defective_only = [strata[1]]
    summary: dict[str, Any] = {
        **metrics,
        "before_after": pair_metrics(pairs),
        "intervals": {
            "recall": _wilson(detection["tp"], detection["defective"]),
            "false_alarm_rate": _wilson(detection["not_cleared"], detection["clean"]),
            "f1": _boot(strata, lambda idx: f1(images, idx), offset),
            "balanced_accuracy": _boot(
                strata, lambda idx: balanced_accuracy(images, idx), offset + 1
            ),
            "finding_precision": _boot(
                defective_only, lambda idx: finding_precision(images, idx), offset + 2
            ),
        },
    }
    before_after = summary["before_after"]
    if before_after["evaluated"]:
        summary["intervals"]["before_after_agreement"] = _wilson(
            before_after["agree"], before_after["scored"]
        )
    subjects = metrics["multi_subject"]
    if subjects["evaluated"]:
        summary["intervals"]["subject_agreement"] = _wilson(
            subjects["agree"], subjects["multi_subject_images"]
        )
    return summary


def tier_analysis(
    case_set: CaseSet, labels: LabelSet, evidence: Evidence, limits: TierLimits
) -> TierAnalysis:
    images, pairs = outcomes(case_set, labels, evidence)
    summary = summarize_rows(images, pairs)
    structured = structured_metrics(evidence)
    summary["structured"] = {
        **structured,
        "interval": _wilson(structured["valid"], structured["cases"]),
    }
    summary["resources"] = resource_metrics(
        evidence, max_wall_seconds=limits.max_wall_seconds,
        max_peak_working_set_bytes=limits.max_peak_working_set_bytes,
        median_seconds_budget=limits.median_seconds_budget,
    )  # fmt: skip
    summary["candidate_id"] = evidence.candidate_id
    summary["complete"] = evidence.complete
    return TierAnalysis(summary, tuple(images), tuple(pairs))


# ------------------------------------------------------------------------------------------------------- floors


def _count_token(count: int) -> str:
    return "5_or_more" if count >= 5 else str(count)


def _modal_finding(labels: LabelSet, case_set: CaseSet) -> dict[str, str]:
    tally: Counter[tuple[str, str]] = Counter()
    categories: Counter[str] = Counter()
    for case in case_set.cases:
        if case.kind != eval2.KIND_IMAGE:
            continue
        for finding in labels.image(case.case_id).findings:
            categories[finding.category] += 1
            for zone in finding.zones or ():
                tally[(finding.category, zone)] += 1
    if tally:
        best = max(
            tally.items(),
            key=lambda kv: (kv[1], -eval2.CATEGORIES.index(kv[0][0]), -eval2.ZONES.index(kv[0][1])),
        )
        return {"category": best[0][0], "region": best[0][1]}
    if categories:
        best_category = max(
            categories.items(), key=lambda kv: (kv[1], -eval2.CATEGORIES.index(kv[0]))
        )[0]
        return {"category": best_category, "region": "center"}
    return {"category": Category.GENERAL.value, "region": eval2.WHOLE_IMAGE}


def floor_answers(case_set: CaseSet, labels: LabelSet) -> dict[str, dict[str, Any]]:
    """The image answer each deterministic floor gives on every image (it looks at nothing).

    ``most_frequent`` knows the label distribution (the majority verdict, the most frequent finding and subject count): it is
    the strongest answer a system that ignores the image can give."""

    images = [
        labels.image(case.case_id) for case in case_set.cases if case.kind == eval2.KIND_IMAGE
    ]
    verdicts = Counter(reference.verdict for reference in images)
    majority = (
        eval2.VERDICT_DEFECTIVE
        if verdicts[eval2.VERDICT_DEFECTIVE] > verdicts[eval2.VERDICT_CLEAN]
        else (eval2.VERDICT_CLEAN)
    )
    counts = Counter(
        reference.subject_count for reference in images if reference.subject_count is not None
    )
    modal_count = (
        _count_token(max(counts.items(), key=lambda kv: (kv[1], -kv[0]))[0]) if counts else "1"
    )
    modal = _modal_finding(labels, case_set)
    return {
        "always_clean": {"verdict": eval2.VERDICT_CLEAN, "findings": [], "subject_count": "1"},
        "always_defect": {
            "verdict": eval2.VERDICT_DEFECTIVE,
            "findings": [{"category": Category.GENERAL.value, "region": eval2.WHOLE_IMAGE}],
            "subject_count": "1",
        },
        "most_frequent": {
            "verdict": majority,
            "findings": [] if majority == eval2.VERDICT_CLEAN else [modal],
            "subject_count": modal_count,
        },
    }


def floor_rows(
    case_set: CaseSet, labels: LabelSet
) -> dict[str, tuple[list[ImageOutcome], list[PairOutcome]]]:
    answers = floor_answers(case_set, labels)
    conclusive = Counter(
        labels.pair(case.case_id).judgment
        for case in case_set.cases
        if case.kind == eval2.KIND_PAIR
        and labels.pair(case.case_id).judgment != eval2.JUDGMENT_INCONCLUSIVE
    )
    pair_choice = {
        "always_clean": eval2.JUDGMENT_NO_BENEFIT,
        "always_defect": eval2.JUDGMENT_HELPED,
        "most_frequent": max(
            conclusive.items(), key=lambda kv: (kv[1], -eval2.JUDGMENTS.index(kv[0]))
        )[0] if conclusive else eval2.JUDGMENT_HELPED,
        "always_worse": eval2.JUDGMENT_WORSE,
    }  # fmt: skip
    out: dict[str, tuple[list[ImageOutcome], list[PairOutcome]]] = {}
    for name, judgment in pair_choice.items():
        answer = answers.get(name)
        images: list[ImageOutcome] = []
        pairs: list[PairOutcome] = []
        for case in case_set.cases:
            if case.kind == eval2.KIND_IMAGE:
                if answer is None:
                    continue
                result = CaseResult(case.case_id, eval2.STATUS_VALID, "", 0.0, 0, answer)
                images.append(image_outcome(labels.image(case.case_id), result))
            else:
                reference = labels.pair(case.case_id)
                pairs.append(
                    PairOutcome(case.case_id, reference.judgment, judgment, 0.0, eval2.STATUS_VALID)
                )
        out[name] = (images, pairs)
    return out


def floors(case_set: CaseSet, labels: LabelSet) -> dict[str, Any]:
    """Every floor scored by the same code as the tiers. ``always_worse`` exists for before/after only. Floors are valid by
    construction, so they have no structured-validity or resource row."""

    result: dict[str, Any] = {}
    for offset, (name, (images, pairs)) in enumerate(floor_rows(case_set, labels).items()):
        if images:
            result[name] = summarize_rows(images, pairs, offset=100 + 10 * offset)
        else:
            result[name] = {"before_after": pair_metrics(pairs)}
    return result


# ---------------------------------------------------------------------------------------------------- comparator


def validate_comparator(document: Any, case_set: CaseSet) -> dict[str, str | None]:
    """A Florence-2 comparator file: per image case only a subject-count token (or ``None``), nothing else."""

    if not isinstance(document, dict) or set(document) != {
        "schema",
        "comparator_id",
        "case_set_sha256",
        "cases",
    }:
        raise ContractViolation("bad_comparator_document")
    if document["schema"] != COMPARATOR_SCHEMA or document["comparator_id"] != FLORENCE_ID:
        raise ContractViolation("bad_schema", "comparator")
    if (
        not isinstance(document["case_set_sha256"], str)
        or re.fullmatch(r"[0-9a-f]{64}", document["case_set_sha256"]) is None
    ):
        raise ContractViolation("bad_digest", "comparator")
    expected = {case.case_id for case in case_set.cases if case.kind == eval2.KIND_IMAGE}
    answers: dict[str, str | None] = {}
    if not isinstance(document["cases"], list):
        raise ContractViolation("bad_list", "comparator cases")
    for raw in document["cases"]:
        if not isinstance(raw, dict) or set(raw) != {"case_id", "subject_count"}:
            raise ContractViolation("bad_comparator_record")
        if raw["case_id"] not in expected or raw["case_id"] in answers:
            raise ContractViolation("bad_comparator_case")
        if raw["subject_count"] is not None and raw["subject_count"] not in eval2.SUBJECT_COUNTS:
            raise ContractViolation("bad_subject_count")
        answers[raw["case_id"]] = raw["subject_count"]
    if set(answers) != expected:
        raise ContractViolation("comparator_does_not_cover_cases")
    return answers


def florence_summary(
    answers: Mapping[str, str | None], case_set: CaseSet, labels: LabelSet
) -> dict[str, Any]:
    multi = [
        (case.case_id, labels.image(case.case_id).subject_count)
        for case in case_set.cases
        if case.kind == eval2.KIND_IMAGE and (labels.image(case.case_id).subject_count or 0) >= 2
    ]
    agree = sum(
        1
        for case_id, truth in multi
        if truth is not None
        and answers[case_id] is not None
        and subject_count_agrees(str(answers[case_id]), truth)
    )
    summary: dict[str, Any] = {
        "comparator_id": FLORENCE_ID,
        "dimensions": list(FLORENCE_DIMENSIONS),
        "not_addressable": dict(FLORENCE_CANNOT),
    }
    if multi:
        summary["multi_subject"] = {
            "multi_subject_images": len(multi),
            "agree": agree,
            **_wilson(agree, len(multi)),
        }
    else:
        summary["multi_subject"] = {
            "evaluated": False,
            "reason": "no_multi_subject_reference_in_export",
        }
    return summary


# ------------------------------------------------------------------------------------------------------ paired


def paired(fast: TierAnalysis, deep: TierAnalysis) -> dict[str, Any]:
    """The tiers on the same images. Exact McNemar on per-image correctness (overall, defective images, clean images) and a
    paired stratified bootstrap of the F1 and balanced-accuracy differences (deep minus fast)."""

    if [row.case_id for row in fast.images] != [row.case_id for row in deep.images]:
        raise AnalysisRefused("tiers_cover_different_images")

    def test(select: str | None) -> dict[str, Any]:
        b = c = 0
        n = 0
        for f, d in zip(fast.images, deep.images, strict=True):
            if select is not None and f.truth != select:
                continue
            n += 1
            if d.correct and not f.correct:
                b += 1
            elif f.correct and not d.correct:
                c += 1
        result = stats.mcnemar(b, c)
        return {
            "images": n, "deep_right_fast_wrong": b, "fast_right_deep_wrong": c,
            "p_one_sided_deep_better": result.p_one_sided, "p_two_sided": result.p_two_sided,
        }  # fmt: skip

    strata = _strata(fast.images)
    fast_f1, deep_f1 = (
        f1(fast.images, range(len(fast.images))),
        f1(deep.images, range(len(deep.images))),
    )

    def gain(idx: Sequence[int]) -> float | None:
        a, b = f1(deep.images, idx), f1(fast.images, idx)
        return None if a is None or b is None else a - b

    def ba_gain(idx: Sequence[int]) -> float | None:
        a, b = balanced_accuracy(deep.images, idx), balanced_accuracy(fast.images, idx)
        return None if a is None or b is None else a - b

    return {
        "correctness": test(None),
        "defective_images": test(eval2.VERDICT_DEFECTIVE),
        "clean_images": test(eval2.VERDICT_CLEAN),
        "f1_fast": None if fast_f1 is None else round(fast_f1, 6),
        "f1_deep": None if deep_f1 is None else round(deep_f1, 6),
        "f1_gain": _boot(strata, gain, 200),
        "balanced_accuracy_gain": _boot(strata, ba_gain, 201),
        "minimum_discordant_for_p_0_05": stats.mcnemar_minimum_discordant(0.05),
    }


# -------------------------------------------------------------------------------------------------- escalation


def simulate(
    rule: str, fast: TierAnalysis, deep: TierAnalysis
) -> tuple[list[ImageOutcome], list[float], int]:
    """The final answer, seconds and escalation decision per image under ``rule``, from the two tiers' real answers.

    Escalated images show the deep answer; when the deep tier gave no usable answer the operator still has the fast one."""

    if rule not in RULES:
        raise AnalysisRefused("unknown_rule")
    final: list[ImageOutcome] = []
    seconds: list[float] = []
    escalated = 0
    for f, d in zip(fast.images, deep.images, strict=True):
        if rule == RULE_DEEP_ONLY:
            final.append(d)
            seconds.append(d.wall_seconds)
            continue
        if rule == RULE_NEVER:
            escalate = False
        elif rule == RULE_ALWAYS:
            escalate = True
        elif rule == RULE_ON_DEFECT:
            escalate = f.predicted != eval2.VERDICT_CLEAN
        else:
            escalate = f.predicted != eval2.VERDICT_DEFECTIVE
        if escalate:
            escalated += 1
            final.append(d if d.predicted is not None else f)
            seconds.append(f.wall_seconds + d.wall_seconds)
        else:
            final.append(f)
            seconds.append(f.wall_seconds)
    return final, seconds, escalated


#: Shares of defective images at which the report also shows two-tier time (the test set's own share is a design choice).
SENSITIVITY_SHARES: tuple[float, ...] = (0.25, 0.5, 0.75)


def weighted_seconds(
    rows: Sequence[ImageOutcome], seconds: Sequence[float], share: float
) -> float | None:
    """Expected seconds per image when ``share`` of reviewed images are defective: class means weighted by ``share``.

    Recall and false-alarm rate are class-conditional and do not depend on the mix; time does, because the conditional rules
    escalate by the fast tier's verdict. Falls back to the plain mean when a class is absent."""

    if not seconds:
        return None
    by_class: dict[str, list[float]] = {eval2.VERDICT_DEFECTIVE: [], eval2.VERDICT_CLEAN: []}
    for row, value in zip(rows, seconds, strict=True):
        by_class[row.truth].append(value)
    if not all(by_class.values()):
        return round(sum(seconds) / len(seconds), 3)
    mean = {key: sum(values) / len(values) for key, values in by_class.items()}
    return round(share * mean[eval2.VERDICT_DEFECTIVE] + (1 - share) * mean[eval2.VERDICT_CLEAN], 3)


def escalation(
    fast: TierAnalysis, deep: TierAnalysis, operator_defect_share: float
) -> dict[str, Any]:
    """Every rule on the same images. ``time_vs_deep`` and the two-tier gate use seconds at the plan's
    ``operator_defect_share``; ``mean_seconds_per_image`` is the plain mean over this set."""

    rows: dict[str, Any] = {}
    for rule in RULES:
        final, seconds, escalated = simulate(rule, fast, deep)
        metrics = image_metrics(final)
        detection, triage = metrics["image_detection"], metrics["finding_triage"]
        count = len(final)
        rows[rule] = {
            "description": RULE_TEXT[rule],
            "recall": detection["recall"], "false_alarm_rate": detection["false_alarm_rate"], "f1": detection["f1"],
            "balanced_accuracy": detection["balanced_accuracy"], "finding_precision": triage["precision"],
            "escalation_rate": None if count == 0 or rule == RULE_DEEP_ONLY else round(escalated / count, 6),
            "mean_seconds_per_image": None if count == 0 else round(sum(seconds) / count, 3),
            "seconds_at_operator_share": weighted_seconds(final, seconds, operator_defect_share),
            "seconds_by_share": {str(s): weighted_seconds(final, seconds, s) for s in SENSITIVITY_SHARES},
        }  # fmt: skip
    deep_seconds = rows[RULE_DEEP_ONLY]["seconds_at_operator_share"]
    deep_recall = rows[RULE_DEEP_ONLY]["recall"]
    for rule in RULES:
        row = rows[rule]
        row["time_vs_deep"] = (
            None if not deep_seconds or row["seconds_at_operator_share"] is None
            else round(row["seconds_at_operator_share"] / deep_seconds, 6)
        )  # fmt: skip
        row["recall_shortfall_vs_deep"] = (
            None
            if deep_recall is None or row["recall"] is None
            else round(deep_recall - row["recall"], 6)
        )
    rows["operator_requested"] = {
        "description": "operator-requested only: the fast look by default, the deep look when asked; see never and deep_only",
        "same_as": [RULE_NEVER, RULE_DEEP_ONLY],
    }
    return rows


# --------------------------------------------------------------------------------------------------------- whole


def analyze(
    case_set: CaseSet,
    labels: LabelSet,
    fast_evidence: Evidence,
    deep_evidence: Evidence,
    plan: Mapping[str, Any],
    *,
    florence: Any | None = None,
) -> dict[str, Any]:
    """The whole two-tier analysis, bound to the approved plan: refused if an evidence file names another plan, case set,
    tier or candidate."""

    for evidence, tier in ((fast_evidence, eval2.TIER_FAST), (deep_evidence, eval2.TIER_DEEP)):
        if evidence.tier != tier:
            raise AnalysisRefused("evidence_tier_mismatch")
        if evidence.plan_sha256 != plan["plan_sha256"]:
            raise AnalysisRefused("evidence_plan_mismatch")
        if evidence.case_set_sha256 != plan["case_set"]["case_set_sha256"]:
            raise AnalysisRefused("evidence_case_set_mismatch")
        if evidence.candidate_id != plan["tiers"][tier]["candidate_id"]:
            raise AnalysisRefused("evidence_candidate_mismatch")
    if florence is not None and not plan["florence_in_scope"]:
        raise AnalysisRefused("florence_not_in_plan")
    limits = {
        tier: TierLimits(
            **{key: plan["tiers"][tier]["limits"][key] for key in TierLimits.__dataclass_fields__}
        )
        for tier in eval2.TIERS
    }
    fast = tier_analysis(case_set, labels, fast_evidence, limits[eval2.TIER_FAST])
    deep = tier_analysis(case_set, labels, deep_evidence, limits[eval2.TIER_DEEP])
    floor_table = floors(case_set, labels)
    best_floor = max(
        (row["image_detection"]["balanced_accuracy"] for row in floor_table.values() if "image_detection" in row
         and row["image_detection"]["balanced_accuracy"] is not None),
        default=0.5,
    )  # fmt: skip
    best_floor_precision = max(
        (row["finding_triage"]["precision"] for row in floor_table.values() if "finding_triage" in row
         and row["finding_triage"]["precision"] is not None),
        default=None,
    )  # fmt: skip
    florence_part = None
    if florence is not None:
        answers = validate_comparator(florence, case_set)
        if florence["case_set_sha256"] != plan["case_set"]["case_set_sha256"]:
            raise AnalysisRefused("comparator_case_set_mismatch")
        florence_part = florence_summary(answers, case_set, labels)
    images = list(fast.images)
    return {
        "plan_sha256": plan["plan_sha256"],
        "stage": plan["stage"],
        "counts": {
            "cases": len(case_set.cases),
            "images": len(images),
            "clean": sum(1 for row in images if row.truth == eval2.VERDICT_CLEAN),
            "defective": sum(1 for row in images if row.truth == eval2.VERDICT_DEFECTIVE),
            "multi_subject": sum(1 for row in images if (row.subject_truth or 0) >= 2),
            "pairs": len(fast.pairs),
        },
        "tiers": {eval2.TIER_FAST: fast.summary, eval2.TIER_DEEP: deep.summary},
        "floors": floor_table,
        "best_floor_balanced_accuracy": best_floor,
        "best_floor_finding_precision": best_floor_precision,
        "paired": paired(fast, deep),
        "operator_defect_share": plan["operator_defect_share"],
        "escalation": escalation(fast, deep, float(plan["operator_defect_share"])),
        "florence": florence_part,
        "not_evaluated": dict(NOT_EVALUATED),
        "qualified": False,
    }


__all__ = [
    "CONDITIONAL_RULES",
    "RULES",
    "AnalysisRefused",
    "TierAnalysis",
    "TierLimits",
    "analyze",
    "balanced_accuracy",
    "escalation",
    "f1",
    "finding_precision",
    "floor_answers",
    "floors",
    "paired",
    "simulate",
    "summarize_rows",
    "tier_analysis",
    "validate_comparator",
]
