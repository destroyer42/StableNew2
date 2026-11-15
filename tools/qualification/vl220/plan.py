"""The visual evaluation plan: one deterministic document that says what would be measured, against what, and what is held.

``build_plan`` runs nothing. It records the contract (dimensions, response schemas, limits), the synthetic wiring set's
digests, the candidate's pinned identities and the comparator eligibility table, and states that no model is executed and that
the image invocation is not approved. Its digest changes whenever any of those change, so the document the owner approves is
the document that is checked.
"""

from __future__ import annotations

from dataclasses import replace
from typing import Any

from tools.qualification.vl220 import contract, scoring, synthetic
from tools.qualification.vl220.candidates import (
    GEMMA_CANDIDATE_ID,
    LFM_CANDIDATE_ID,
    VisualCandidate,
    find_candidate,
)

INVOCATION_DOCUMENT = "docs/Subsystems/AiAssist/PR-AI-VL-220_Image_Invocation_Contract.md"
EVALUATION_DOCUMENT = "docs/Subsystems/AiAssist/PR-AI-VL-220_Visual_Evaluation_Contract.md"


def dry_run() -> dict[str, Any]:
    """Validate the synthetic set end to end and score the three no-look baselines. Reads and writes no file."""

    _, case_doc, label_doc = synthetic.build_synthetic_set()
    case_set = contract.validate_case_set(case_doc)
    labels = contract.validate_label_set(label_doc, case_set)
    return {
        "set_id": case_set.set_id,
        "cases": len(case_set.cases),
        "baselines": {
            mode: scoring.score_run(case_set, labels, scoring.baseline_responses(case_set, mode))
            for mode in ("all_yes", "all_no", "seeded_random")
        },
    }


def evaluation_limits(candidate: VisualCandidate) -> contract.ResourceLimits:
    limits = contract.ResourceLimits()
    if candidate.candidate_id == GEMMA_CANDIDATE_ID:
        return replace(limits, max_peak_working_set_bytes=12 * 1024**3)
    return limits


def build_plan(candidate: VisualCandidate | None = None) -> dict[str, Any]:
    chosen = candidate if candidate is not None else find_candidate(LFM_CANDIDATE_ID)
    limits = evaluation_limits(chosen)
    images, case_doc, label_doc = synthetic.build_synthetic_set()
    plan: dict[str, Any] = {
        "contract_id": contract.CONTRACT_ID,
        "executes_models": False,
        "image_invocation": {
            "approved": contract.INVOCATION_APPROVED and chosen.image_invocation_approved,
            "document": INVOCATION_DOCUMENT,
        },
        "evaluation_document": EVALUATION_DOCUMENT,
        "dimensions": list(contract.DIMENSIONS),
        "kinds": {kind: contract.DIMENSION_OF_KIND[kind] for kind in contract.KINDS},
        "response_schema_digests": {
            kind: contract.digest(contract.build_response_schema(kind)) for kind in contract.KINDS
        },
        "limits": {
            "max_wall_seconds": limits.max_wall_seconds,
            "max_peak_working_set_bytes": limits.max_peak_working_set_bytes,
            "max_context_tokens": limits.max_context_tokens,
            "require_cpu_only": limits.require_cpu_only,
        },
        "synthetic_set": {
            "set_id": synthetic.SET_ID,
            "images": len(images),
            "case_set_sha256": contract.digest(case_doc),
            "label_set_sha256": contract.digest(label_doc),
        },
        "candidate": {
            "candidate_id": chosen.candidate_id,
            "model_sha256": chosen.model.sha256,
            "projector_sha256": chosen.projector.sha256,
            "required_build_id": chosen.runtime.required_build_id,
            "tool": chosen.runtime.tool,
            "license_text_sha256": chosen.license.text_sha256,
            "qualified": False,
        },
        "comparators": contract.comparator_table(),
    }
    plan["plan_sha256"] = contract.digest(plan)
    return plan


__all__ = ["EVALUATION_DOCUMENT", "INVOCATION_DOCUMENT", "build_plan", "dry_run"]
