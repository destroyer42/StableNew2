"""Synthetic fixtures for the AI-VL-242 tests: a fake Review export and scripted evidence. No real image, prompt or label."""

from __future__ import annotations

import hashlib
from collections.abc import Callable, Mapping
from typing import Any

from tools.qualification.vl220 import eval2, review_export
from tools.qualification.vl220.contract import canonical_json
from tools.qualification.vl220.eval2 import CaseSet, LabelSet
from tools.qualification.vl242 import plan as plan_module

FAST_ID = "lfm3-vl-2b-q4_k_m-liquidai"
DEEP_ID = "gemma-4-12b-it-qat-q4_0-google"


def sha(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def image(
    name: str,
    *,
    clean: bool = True,
    findings: list[dict[str, Any]] | None = None,
    subject_count: int | None = None,
    size: int = 300,
) -> dict[str, Any]:
    return {
        "image_id": name, "sha256": sha(name), "width": size, "height": size, "clean_confirmed": clean,
        "findings": findings or [], "subject_count": subject_count,
    }  # fmt: skip


def finding(
    category: str = "Hands", region: list[int] | None = None, **extra: Any
) -> dict[str, Any]:
    return {
        "category": category,
        "region": region if region is not None else [0, 0, 90, 90],
        **extra,
    }


def export(
    images: list[dict[str, Any]], pairs: list[dict[str, Any]] | None = None
) -> dict[str, Any]:
    return {
        "schema": eval2.EXPORT_SCHEMA,
        "provenance": {"labeler": "human", "tool": "synthetic-fixture"},
        "images": images,
        "pairs": pairs or [],
    }


def pair(name: str, before: str, after: str, judgment: str) -> dict[str, Any]:
    return {
        "pair_id": name,
        "before_image_id": before,
        "after_image_id": after,
        "intervention": "x",
        "judgment": judgment,
    }


CATEGORY_CYCLE = ("Hands", "Face", "Anatomy")
#: top_left, center and bottom_right of a 300-pixel image.
REGION_CYCLE = ([0, 0, 90, 90], [110, 110, 190, 190], [210, 210, 300, 300])


def standard_export(
    clean: int = 20, defective: int = 30, multi: int = 10, pairs: int = 12
) -> dict[str, Any]:
    """The planned set's shape: ``clean`` + ``defective`` images (one finding each, categories and zones cycling), the first ``multi`` defective
    images with two subjects, and ``pairs`` before/after pairs over the defective images."""

    images = [image(f"clean-{i}", subject_count=1) for i in range(clean)]
    images += [
        image(
            f"defect-{i}",
            clean=False,
            findings=[finding(CATEGORY_CYCLE[i % 3], REGION_CYCLE[(i // 3) % 3])],
            subject_count=2 if i < multi else 1,
        )
        for i in range(defective)
    ]
    judgments = (
        eval2.JUDGMENT_HELPED,
        eval2.JUDGMENT_NO_BENEFIT,
        eval2.JUDGMENT_WORSE,
        eval2.JUDGMENT_INCONCLUSIVE,
    )
    pair_rows = []
    for i in range(pairs):
        after = f"after-{i}"
        images.append(image(after, clean=False, findings=[], subject_count=None))
        pair_rows.append(pair(f"pair-{i}", f"defect-{i % defective}", after, judgments[i % 4]))
    return export(images, pair_rows)


def documents(
    document: Mapping[str, Any],
) -> tuple[dict[str, Any], dict[str, Any], CaseSet, LabelSet]:
    conversion = review_export.convert(document)
    case_set = eval2.validate_case_set(conversion.cases)
    labels = eval2.validate_label_set(conversion.labels, case_set)
    return conversion.cases, conversion.labels, case_set, labels


def image_answer(
    verdict: str, findings: list[tuple[str, str]] | None = None, subjects: str = "1"
) -> dict[str, Any]:
    return {
        "verdict": verdict,
        "findings": [{"category": c, "region": r} for c, r in (findings or [])],
        "subject_count": subjects,
    }


def response_text(case: eval2.Case, answer: Mapping[str, Any]) -> str:
    return canonical_json(
        {"schema": eval2.RESPONSE_SCHEMA, "status": "ok", "kind": case.kind, **answer}
    )


Policy = Callable[[eval2.Case, Any], tuple[Mapping[str, Any] | None, float]]


def scripted(
    case_set: CaseSet,
    labels: LabelSet,
    policy: Policy,
    *,
    tier: str,
    plan_sha256: str,
    case_set_sha256: str,
    peak: int = 1024**3,
) -> dict[str, Any]:
    """An ``evidence/2`` document whose answers come from ``policy(case, reference) -> (answer or None, seconds)``."""

    rows = []
    for case in case_set.cases:
        answer, seconds = policy(case, labels.references[case.case_id])
        if answer is None:
            rows.append(
                eval2.evidence_record(
                    case,
                    None,
                    wall_seconds=seconds,
                    peak_working_set_bytes=peak,
                    run_status="invalid",
                    reason="not_json",
                )
            )
            continue
        check = eval2.validate_response(case, response_text(case, answer))
        assert check.status == eval2.STATUS_VALID, check
        rows.append(
            eval2.evidence_record(case, check, wall_seconds=seconds, peak_working_set_bytes=peak)
        )
    return eval2.evidence_document(
        rows, tier=tier, candidate_id=FAST_ID if tier == eval2.TIER_FAST else DEEP_ID, plan_sha256=plan_sha256,
        case_set_sha256=case_set_sha256, complete=True,
    )  # fmt: skip


def truthful(seconds: float = 1.0) -> Policy:
    """Answers every image exactly as labelled (each finding's category and first zone) and every pair with the corrected image's judgment."""

    def policy(case: eval2.Case, reference: Any) -> tuple[Mapping[str, Any] | None, float]:
        if case.kind == eval2.KIND_IMAGE:
            if reference.verdict == eval2.VERDICT_CLEAN:
                return image_answer(
                    "clean", subjects=str(min(reference.subject_count or 1, 4))
                ), seconds
            found = [(item.category, (item.zones or ("center",))[0]) for item in reference.findings]
            return image_answer("defective", found[:6], str(reference.subject_count or 1)), seconds
        after_first = case.asset_ids[0] == reference.after_asset_id
        if reference.judgment == eval2.JUDGMENT_HELPED:
            return {"answer": "first_better" if after_first else "second_better"}, seconds
        if reference.judgment == eval2.JUDGMENT_WORSE:
            return {"answer": "second_better" if after_first else "first_better"}, seconds
        return {"answer": "no_clear_difference"}, seconds

    return policy


def planned(case_doc: Any, label_doc: Any, stage: str = "full", **kwargs: Any) -> dict[str, Any]:
    return plan_module.build_plan(case_doc, label_doc, stage=stage, **kwargs)
