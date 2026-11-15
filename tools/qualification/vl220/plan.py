"""The visual evaluation plan: one deterministic document that says what would be measured, against what, and what is held.

``build_plan`` runs nothing. It records the contract (dimensions, response schemas, limits), the synthetic wiring set's
digests, the candidate's pinned identities and the comparator eligibility table, and states that no model is executed and that
the image invocation is not approved. Its digest changes whenever any of those change, so the document the owner approves is
the document that is checked.
"""

from __future__ import annotations

import hashlib
from typing import Any

from tools.qualification.vl220 import contract, diagnostics, prompts, scoring, synthetic
from tools.qualification.vl220.candidates import VisualCandidate, load_candidates

INVOCATION_DOCUMENT = "docs/Subsystems/AiAssist/PR-AI-VL-220_Image_Invocation_Contract.md"
EVALUATION_DOCUMENT = "docs/Subsystems/AiAssist/PR-AI-VL-220_Visual_Evaluation_Contract.md"
DIAGNOSTIC_DOCUMENT = "docs/work_packages/AI-VL-222_visual_diagnostic.md"


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


def _sha(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def diagnostic_section() -> dict[str, Any]:
    """What the PR-AI-VL-222 diagnostic would send and keep, so the digest the owner approves covers the exact question text.

    Per built-in synthetic set: its pinned digests, and for every case the SHA-256 of the prompt file and of its own response
    schema; the two free-text controls and their prompt. It also states, as data, what the invocation does *not* change."""

    sets: dict[str, Any] = {}
    invocations = 0
    for set_id, scale in synthetic.BUILTIN_SCALES.items():
        images, case_doc, label_doc = synthetic.build_synthetic_set(set_id)
        case_set = contract.validate_case_set(case_doc)
        requests = {
            case.case_id: {
                "prompt_sha256": _sha(prompts.render_visual_prompt(case)),
                "schema_sha256": contract.digest(contract.build_response_schema(case.kind, case)),
            }
            for case in case_set.cases
        }
        controls = [
            {
                "request_id": item.request_id,
                "asset_id": item.asset_id,
                "prompt_sha256": _sha(prompts.render_control_prompt()),
            }
            for item in diagnostics.control_requests(set_id)
        ]
        invocations += len(requests) + len(controls)
        sets[set_id] = {
            "image_edge_pixels": synthetic.CELL * scale,
            "images": len(images),
            "case_set_sha256": contract.digest(case_doc),
            "label_set_sha256": contract.digest(label_doc),
            "requests": requests,
            "controls": controls,
        }
    return {
        "decision": "D23",
        "document": DIAGNOSTIC_DOCUMENT,
        "capture": {
            "only_for": "built-in synthetic sets with labeler synthetic_by_construction and matching pins",
            "answer_text_bytes": diagnostics.ANSWER_BYTES,
            "stderr_head_bytes": diagnostics.STDERR_HEAD_BYTES,
            "stderr_tail_bytes": diagnostics.STDERR_TAIL_BYTES,
            "written_to": "next to the evidence file, outside Git",
        },
        "invocation_unchanged": {
            "executable": "llama-mtmd-cli.exe of b11960-cpu-vision",
            "new_flags": [],
            "jinja": "refused",
            "cpu_only": True,
            "control_has_no_json_schema": True,
        },
        "invocations": invocations,
        "sets": sets,
    }


def build_plan(candidate: VisualCandidate | None = None) -> dict[str, Any]:
    chosen = candidate if candidate is not None else load_candidates()[0]
    images, case_doc, label_doc = synthetic.build_synthetic_set()
    plan: dict[str, Any] = {
        "contract_id": contract.CONTRACT_ID,
        "executes_models": False,
        "image_invocation": {
            "approved": contract.INVOCATION_APPROVED,
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
            "required_build_id": chosen.runtime.required_build_id,
            "tool": chosen.runtime.tool,
            "license_text_sha256": chosen.license.text_sha256,
            "qualified": False,
        },
        "comparators": contract.comparator_table(),
        "diagnostic": diagnostic_section(),
    }
    plan["plan_sha256"] = contract.digest(plan)
    return plan


__all__ = [
    "DIAGNOSTIC_DOCUMENT",
    "EVALUATION_DOCUMENT",
    "INVOCATION_DOCUMENT",
    "build_plan",
    "diagnostic_section",
    "dry_run",
]
