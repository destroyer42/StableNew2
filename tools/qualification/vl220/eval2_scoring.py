"""Deterministic scoring for ``eval/2`` (PR-AI-VL-242). Pure functions over closed answers; no model, file or clock access.

Every case is scored, never skipped. A case without a usable answer (invalid, refused, timed out, not run) counts against the
system on both sides: a confirmed-defect image it did not flag is a miss, and a confirmed-clean image it did not clear is a
false alarm ("not cleared"), so a system cannot improve its false-alarm rate by failing to answer.

Per image the scorer records an :class:`ImageOutcome`; per pair a :class:`PairOutcome`. :func:`image_metrics` and
:func:`pair_metrics` turn lists of them into numbers, so the analysis can recompute them on bootstrap resamples and on the
simulated two-tier answers with the same code.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, replace
from typing import Any

from tools.qualification.vl220 import eval2
from tools.qualification.vl220.eval2 import (
    CaseResult,
    CaseSet,
    Evidence,
    HumanFinding,
    ImageReference,
    LabelSet,
    PairReference,
)


def _ratio(numerator: float, denominator: float) -> float | None:
    return None if denominator == 0 else round(numerator / denominator, 6)


# ----------------------------------------------------------------------------------------------------------- matching


def max_matching(left: int, right: int, compatible: Callable[[int, int], bool]) -> int:
    """Size of a maximum one-to-one matching (Kuhn's augmenting paths; lists are at most 24 long)."""

    owner: list[int | None] = [None] * right

    def augment(i: int, seen: list[bool]) -> bool:
        for j in range(right):
            if not seen[j] and compatible(i, j):
                seen[j] = True
                current = owner[j]
                if current is None or augment(current, seen):
                    owner[j] = i
                    return True
        return False

    return sum(1 for i in range(left) if augment(i, [False] * right))


def match_findings(
    answer: Sequence[Mapping[str, str]], human: Sequence[HumanFinding], *, use_region: bool = True
) -> tuple[int, int, int]:
    """``(true positives, unsupported answer findings, missed human findings)`` under a one-to-one matching.

    An answer finding matches a human one when the category is equal and (``use_region``) the region is compatible
    (:func:`eval2.region_matches`)."""

    def compatible(i: int, j: int) -> bool:
        if answer[i]["category"] != human[j].category:
            return False
        return not use_region or eval2.region_matches(answer[i]["region"], human[j].zones)

    tp = max_matching(len(answer), len(human), compatible)
    return tp, len(answer) - tp, len(human) - tp


def subject_count_agrees(answer: str, truth: int) -> bool:
    return truth >= 5 if answer == "5_or_more" else answer.isdigit() and int(answer) == truth


# ---------------------------------------------------------------------------------------------------------- outcomes


@dataclass(frozen=True, slots=True)
class ImageOutcome:
    case_id: str
    truth: str
    #: ``None`` when the system gave no usable answer.
    predicted: str | None
    tp: int
    fp: int
    fn: int
    category_tp: int
    category_fp: int
    category_fn: int
    subject_truth: int | None
    subject_answer: str | None
    wall_seconds: float
    peak_working_set_bytes: int
    status: str

    @property
    def flagged(self) -> bool:
        return self.predicted == eval2.VERDICT_DEFECTIVE

    @property
    def correct(self) -> bool:
        """Per-image correctness for the paired test: the answered verdict equals the human one."""

        return self.predicted is not None and self.predicted == self.truth


def image_outcome(reference: ImageReference, result: CaseResult) -> ImageOutcome:
    answer = result.answer if result.answered else None
    findings: Sequence[Mapping[str, str]] = answer["findings"] if answer else ()
    tp, fp, fn = match_findings(findings, reference.findings)
    ctp, cfp, cfn = match_findings(findings, reference.findings, use_region=False)
    return ImageOutcome(
        case_id=result.case_id,
        truth=reference.verdict,
        predicted=answer["verdict"] if answer else None,
        tp=tp, fp=fp, fn=fn, category_tp=ctp, category_fp=cfp, category_fn=cfn,
        subject_truth=reference.subject_count,
        subject_answer=answer["subject_count"] if answer else None,
        wall_seconds=result.wall_seconds,
        peak_working_set_bytes=result.peak_working_set_bytes,
        status=result.status,
    )  # fmt: skip


def unanswered(outcome: ImageOutcome, reference: ImageReference) -> ImageOutcome:
    """The same image scored as if no usable answer came back (used by floors and fallbacks)."""

    misses = len(reference.findings)
    return replace(
        outcome, predicted=None, tp=0, fp=0, fn=misses, category_tp=0, category_fp=0, category_fn=misses,
        subject_answer=None,
    )  # fmt: skip


@dataclass(frozen=True, slots=True)
class PairOutcome:
    case_id: str
    judgment: str
    #: The system's answer mapped to a judgment (``None``: no usable answer).
    predicted: str | None
    wall_seconds: float
    status: str


def pair_judgment(answer: str, after_first: bool) -> str:
    """Map a position answer to the judgment vocabulary: the corrected image better is ``helped``."""

    if answer == eval2.PAIR_NONE:
        return eval2.JUDGMENT_NO_BENEFIT
    first_better = answer == eval2.PAIR_FIRST
    return eval2.JUDGMENT_HELPED if first_better == after_first else eval2.JUDGMENT_WORSE


def pair_outcome(case: eval2.Case, reference: PairReference, result: CaseResult) -> PairOutcome:
    predicted = None
    if result.answered and result.answer is not None:
        predicted = pair_judgment(
            result.answer["answer"], case.asset_ids[0] == reference.after_asset_id
        )
    return PairOutcome(
        result.case_id, reference.judgment, predicted, result.wall_seconds, result.status
    )


def outcomes(
    case_set: CaseSet, labels: LabelSet, evidence: Evidence
) -> tuple[list[ImageOutcome], list[PairOutcome]]:
    images: list[ImageOutcome] = []
    pairs: list[PairOutcome] = []
    for case in case_set.cases:
        result = evidence.results[case.case_id]
        if case.kind == eval2.KIND_IMAGE:
            images.append(image_outcome(labels.image(case.case_id), result))
        else:
            pairs.append(pair_outcome(case, labels.pair(case.case_id), result))
    return images, pairs


# ----------------------------------------------------------------------------------------------------------- metrics


def image_metrics(rows: Sequence[ImageOutcome]) -> dict[str, Any]:
    """Image-level detection, finding-level triage, clean false alarms and the hallucination proxy for one system."""

    defective = [row for row in rows if row.truth == eval2.VERDICT_DEFECTIVE]
    clean = [row for row in rows if row.truth == eval2.VERDICT_CLEAN]
    tp = sum(1 for row in defective if row.flagged)
    fn = len(defective) - tp
    tn = sum(1 for row in clean if row.predicted == eval2.VERDICT_CLEAN)
    not_cleared = len(clean) - tn
    recall = _ratio(tp, len(defective))
    false_alarm = _ratio(not_cleared, len(clean))
    specificity = None if false_alarm is None else round(1 - false_alarm, 6)
    balanced = (
        None if recall is None or specificity is None else round((recall + specificity) / 2, 6)
    )
    f_tp = sum(row.tp for row in defective)
    f_fp = sum(row.fp for row in defective)
    f_fn = sum(row.fn for row in defective)
    c_tp = sum(row.category_tp for row in defective)
    c_fp = sum(row.category_fp for row in defective)
    c_fn = sum(row.category_fn for row in defective)
    clean_unsupported = sum(row.fp for row in clean)
    return {
        "image_detection": {
            "defective": len(defective), "clean": len(clean), "tp": tp, "fn": fn, "tn": tn, "not_cleared": not_cleared,
            "unanswered_defective": sum(1 for row in defective if row.predicted is None),
            "unanswered_clean": sum(1 for row in clean if row.predicted is None),
            "recall": recall, "false_alarm_rate": false_alarm, "specificity": specificity,
            "precision": _ratio(tp, tp + not_cleared), "f1": _ratio(2 * tp, 2 * tp + not_cleared + fn),
            "balanced_accuracy": balanced,
        },
        "finding_triage": {
            "tp": f_tp, "fp": f_fp, "fn": f_fn,
            "precision": _ratio(f_tp, f_tp + f_fp), "recall": _ratio(f_tp, f_tp + f_fn),
            "category_only": {"tp": c_tp, "fp": c_fp, "fn": c_fn, "precision": _ratio(c_tp, c_tp + c_fp),
                              "recall": _ratio(c_tp, c_tp + c_fn)},
        },
        "hallucination": {
            "clean_images": len(clean),
            "findings_on_clean_images": clean_unsupported,
            "findings_per_clean_image": _ratio(clean_unsupported, len(clean)),
            "unmatched_findings_on_defective_images": f_fp,
            "note": "unmatched findings on defective images may be real defects the operator did not record",
        },
        "multi_subject": _subjects(rows),
    }  # fmt: skip


def _subjects(rows: Sequence[ImageOutcome]) -> dict[str, Any]:
    recorded = [row for row in rows if row.subject_truth is not None]
    multi = [row for row in recorded if row.subject_truth is not None and row.subject_truth >= 2]
    if not multi:
        return {
            "evaluated": False,
            "reason": "no_multi_subject_reference_in_export",
            "recorded": len(recorded),
        }

    def agree(items: Sequence[ImageOutcome]) -> int:
        return sum(
            1
            for row in items
            if row.subject_answer is not None
            and row.subject_truth is not None
            and subject_count_agrees(row.subject_answer, row.subject_truth)
        )

    return {
        "evaluated": True,
        "measure": "subject count agreement (the export records counts, not per-subject identity)",
        "multi_subject_images": len(multi), "agree": agree(multi), "agreement": _ratio(agree(multi), len(multi)),
        "recorded": len(recorded), "agree_all_recorded": agree(recorded),
        "agreement_all_recorded": _ratio(agree(recorded), len(recorded)),
    }  # fmt: skip


def pair_metrics(rows: Sequence[PairOutcome]) -> dict[str, Any]:
    """Before/after agreement with the human judgment. ``inconclusive`` pairs have no reference and are excluded (counted);
    ``no_benefit`` is matched by ``no_clear_difference``. A binary helped / not-helped agreement is reported beside it."""

    scored = [row for row in rows if row.judgment != eval2.JUDGMENT_INCONCLUSIVE]
    if not scored:
        return {"evaluated": False, "reason": "no_conclusive_pair_judgment", "pairs": len(rows)}
    agree = sum(1 for row in scored if row.predicted == row.judgment)
    helped = sum(
        1
        for row in scored
        if row.predicted is not None
        and (row.predicted == eval2.JUDGMENT_HELPED) == (row.judgment == eval2.JUDGMENT_HELPED)
    )
    return {
        "evaluated": True, "pairs": len(rows), "scored": len(scored),
        "inconclusive_excluded": len(rows) - len(scored),
        "unanswered": sum(1 for row in scored if row.predicted is None),
        "agree": agree, "agreement": _ratio(agree, len(scored)),
        "helped_binary_agree": helped, "helped_binary_agreement": _ratio(helped, len(scored)),
    }  # fmt: skip


def structured_metrics(evidence: Evidence) -> dict[str, Any]:
    statuses: dict[str, int] = {}
    reasons: dict[str, int] = {}
    for result in evidence.results.values():
        statuses[result.status] = statuses.get(result.status, 0) + 1
        if result.status == eval2.STATUS_INVALID and result.reason:
            reasons[result.reason] = reasons.get(result.reason, 0) + 1
    total = len(evidence.results)
    valid = statuses.get(eval2.STATUS_VALID, 0)
    return {
        "cases": total, "valid": valid, "valid_rate": _ratio(valid, total),
        "statuses": dict(sorted(statuses.items())), "invalid_reasons": dict(sorted(reasons.items())),
    }  # fmt: skip


def resource_metrics(
    evidence: Evidence,
    *,
    max_wall_seconds: float,
    max_peak_working_set_bytes: int,
    median_seconds_budget: float,
) -> dict[str, Any]:
    walls = sorted(result.wall_seconds for result in evidence.results.values())
    peak = max(result.peak_working_set_bytes for result in evidence.results.values())
    mid = len(walls) // 2
    median = walls[mid] if len(walls) % 2 else (walls[mid - 1] + walls[mid]) / 2
    memory = sum(
        1
        for r in evidence.results.values()
        if r.peak_working_set_bytes > max_peak_working_set_bytes
    )
    wall = sum(
        1
        for r in evidence.results.values()
        if r.wall_seconds > max_wall_seconds or r.status == "timeout"
    )
    over_budget = median > median_seconds_budget
    return {
        "cases": len(walls), "mean_seconds": round(sum(walls) / len(walls), 3), "median_seconds": round(median, 3),
        "max_seconds": walls[-1], "peak_working_set_bytes": peak,
        "memory_violations": memory, "wall_violations": wall, "median_over_budget": over_budget,
        # Memory over the limit and a median over the budget fail the resource gate; a timed-out case is also invalid.
        "resource_violations": memory + (1 if over_budget else 0),
    }  # fmt: skip


__all__ = [
    "ImageOutcome",
    "PairOutcome",
    "image_metrics",
    "image_outcome",
    "match_findings",
    "max_matching",
    "outcomes",
    "pair_judgment",
    "pair_metrics",
    "pair_outcome",
    "resource_metrics",
    "structured_metrics",
    "subject_count_agrees",
    "unanswered",
]
