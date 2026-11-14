"""Describe the frozen VL-220 evaluation inputs and score the synthetic baselines."""

from __future__ import annotations

from typing import Any

from tools.qualification.vl220 import contract, scoring, synthetic
from tools.qualification.vl220.candidates import VisualCandidate, find_candidate

LFM_CANDIDATE_ID = "lfm3-vl-2b-q4_k_m-liquidai"
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


def build_plan(candidate: VisualCandidate | None = None) -> dict[str, Any]:
    chosen = candidate if candidate is not None else find_candidate(LFM_CANDIDATE_ID)
    images, case_doc, label_doc = synthetic.build_synthetic_set()
    plan: dict[str, Any] = {
        "contract_id": contract.CONTRACT_ID,
        "executes_models": False,
        "image_invocation": {
            "approved": chosen.image_invocation_approved,
            "document": INVOCATION_DOCUMENT,
        },
        "evaluation_document": EVALUATION_DOCUMENT,
        "dimensions": list(contract.DIMENSIONS),
        "kinds": {kind: contract.DIMENSION_OF_KIND[kind] for kind in contract.KINDS},
        "response_schema_digests": {
            kind: contract.digest(contract.build_response_schema(kind)) for kind in contract.KINDS
        },
        "limits": {
            "max_wall_seconds": contract.ResourceLimits().max_wall_seconds,
            "max_peak_working_set_bytes": contract.ResourceLimits().max_peak_working_set_bytes,
            "max_context_tokens": contract.ResourceLimits().max_context_tokens,
            "require_cpu_only": contract.ResourceLimits().require_cpu_only,
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
            # Preserve the archive identity and comparator snapshot in the original LFM plan.
            # describe-execution binds the exact vision build, hashes, and launch limits.
            "required_build_id": (
                "b11960-cpu"
                if chosen.candidate_id == LFM_CANDIDATE_ID
                else chosen.runtime.required_build_id
            ),
            "tool": chosen.runtime.tool,
            "license_text_sha256": chosen.license.text_sha256,
            "qualified": False,
        },
        "comparators": contract.comparator_table(),
    }
    plan["plan_sha256"] = contract.digest(plan)
    return plan


__all__ = ["EVALUATION_DOCUMENT", "INVOCATION_DOCUMENT", "build_plan", "dry_run"]
