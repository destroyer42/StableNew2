"""The ``eval/2`` paired-run plan (PR-AI-VL-242): the one digest the owner approves before a real two-tier run.

The plan binds the contract (vocabularies, response schemas, question texts, gate values and interval methods), the case set
and label set digests with content-free counts, the stage (``pilot`` or ``full``), both candidates' pinned identities and each
tier's limits, and whether the Florence-2 comparator is in scope. Any change to any of them changes ``plan_sha256``; evidence
files must name that digest or the analysis refuses them. It holds no image, prompt, path or case id.
"""

from __future__ import annotations

from typing import Any

from tools.qualification.vl220 import eval2
from tools.qualification.vl220 import plan as vl220_plan
from tools.qualification.vl220.candidates import (
    GEMMA_CANDIDATE_ID,
    LFM_CANDIDATE_ID,
    VisualCandidate,
    find_candidate,
)
from tools.qualification.vl220.contract import digest
from tools.qualification.vl242.analysis import RULE_TEXT, RULES, TierLimits
from tools.qualification.vl242.gates import STAGES

CONTRACT_DOCUMENT = "docs/Subsystems/AiAssist/PR-AI-VL-242_Two_Tier_Evaluation_Contract.md"
WORK_PACKAGE_DOCUMENT = "docs/work_packages/AI-VL-242_two_tier_evaluation.md"

#: The planned real set (owner proposal) and the pilot that may come first.
PLANNED_SET = {"clean": 20, "defective": 30, "multi_subject": 10, "pairs": 12}
PILOT_IMAGES = 30
#: Proposed share of defective images among those an operator sends for review, used only to weight two-tier time
#: (recall and false alarm do not depend on it). Neutral 0.5 until Review history gives a better figure; owner-tunable.
OPERATOR_DEFECT_SHARE = 0.5

#: Proposed median seconds-per-image budgets, pending the per-image times AI-VL-241 measures. The per-case wall and memory
#: ceilings default to the ones the VL-220 plan already uses for each candidate.
MEDIAN_BUDGET_SECONDS = {eval2.TIER_FAST: 20.0, eval2.TIER_DEEP: 120.0}
LIMITS_PROPOSED = "proposed_defaults_pending_ai_vl_241_measurement"
LIMITS_OWNER = "owner_supplied"


def default_limits(candidate: VisualCandidate, tier: str) -> TierLimits:
    base = vl220_plan.evaluation_limits(candidate)
    return TierLimits(
        base.max_wall_seconds, base.max_peak_working_set_bytes, MEDIAN_BUDGET_SECONDS[tier]
    )


def _candidate(candidate: VisualCandidate) -> dict[str, Any]:
    return {
        "candidate_id": candidate.candidate_id,
        "model_sha256": candidate.model.sha256,
        "projector_sha256": candidate.projector.sha256,
        "required_build_id": candidate.runtime.required_build_id,
        "tool": candidate.runtime.tool,
        "license_text_sha256": candidate.license.text_sha256,
        "qualified": False,
    }


def case_counts(case_set: eval2.CaseSet, labels: eval2.LabelSet) -> dict[str, int]:
    images = [
        labels.image(case.case_id) for case in case_set.cases if case.kind == eval2.KIND_IMAGE
    ]
    pairs = [labels.pair(case.case_id) for case in case_set.cases if case.kind == eval2.KIND_PAIR]
    return {
        "cases": len(case_set.cases),
        "images": len(images),
        "clean": sum(1 for ref in images if ref.verdict == eval2.VERDICT_CLEAN),
        "defective": sum(1 for ref in images if ref.verdict == eval2.VERDICT_DEFECTIVE),
        "human_findings": sum(len(ref.findings) for ref in images),
        "multi_subject": sum(1 for ref in images if (ref.subject_count or 0) >= 2),
        "pairs": len(pairs),
        "conclusive_pairs": sum(1 for ref in pairs if ref.judgment != eval2.JUDGMENT_INCONCLUSIVE),
    }


def build_plan(
    case_doc: Any,
    label_doc: Any,
    *,
    stage: str,
    fast: VisualCandidate | None = None,
    deep: VisualCandidate | None = None,
    fast_limits: TierLimits | None = None,
    deep_limits: TierLimits | None = None,
    florence_in_scope: bool = False,
    operator_defect_share: float = OPERATOR_DEFECT_SHARE,
) -> dict[str, Any]:
    """Validate the case and label documents and return the plan with its ``plan_sha256``. Runs nothing."""

    if stage not in STAGES:
        raise ValueError(f"stage must be one of {STAGES}")
    case_set = eval2.validate_case_set(case_doc)
    labels = eval2.validate_label_set(label_doc, case_set)
    fast_candidate = fast if fast is not None else find_candidate(LFM_CANDIDATE_ID)
    deep_candidate = deep if deep is not None else find_candidate(GEMMA_CANDIDATE_ID)
    if fast_candidate.candidate_id == deep_candidate.candidate_id:
        raise ValueError("the two tiers must be different candidates")
    if not 0.0 < operator_defect_share < 1.0:
        raise ValueError("operator_defect_share must be strictly between 0 and 1")
    chosen = {
        eval2.TIER_FAST: (fast_candidate, fast_limits),
        eval2.TIER_DEEP: (deep_candidate, deep_limits),
    }
    tiers: dict[str, Any] = {}
    for tier, (candidate, limits) in chosen.items():
        effective = limits if limits is not None else default_limits(candidate, tier)
        tiers[tier] = {
            **_candidate(candidate),
            "limits": effective.record(),
            "limits_source": LIMITS_OWNER if limits is not None else LIMITS_PROPOSED,
        }
    plan: dict[str, Any] = {
        "contract": eval2.contract_section(),
        "contract_document": CONTRACT_DOCUMENT,
        "executes_models": False,
        "qualified": False,
        "stage": stage,
        "planned_set": dict(PLANNED_SET),
        "pilot_images": PILOT_IMAGES,
        "case_set": {
            "set_id": case_set.set_id,
            "export_sha256": case_set.export_sha256,
            "case_set_sha256": digest(case_doc),
            "label_set_sha256": digest(label_doc),
            "counts": case_counts(case_set, labels),
        },
        "tiers": tiers,
        "florence_in_scope": bool(florence_in_scope),
        "escalation_rules": {rule: RULE_TEXT[rule] for rule in RULES},
        "operator_defect_share": float(operator_defect_share),
        "driver_support": "evidence/2 records come from eval2.evidence_record; the driver integration is a separate package",
    }
    plan["plan_sha256"] = digest(plan)
    return plan


__all__ = [
    "CONTRACT_DOCUMENT",
    "LIMITS_OWNER",
    "LIMITS_PROPOSED",
    "MEDIAN_BUDGET_SECONDS",
    "OPERATOR_DEFECT_SHARE",
    "PILOT_IMAGES",
    "PLANNED_SET",
    "WORK_PACKAGE_DOCUMENT",
    "build_plan",
    "case_counts",
    "default_limits",
]
