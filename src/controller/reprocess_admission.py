"""Reprocess admission preflight (PR-IMG-MODELS-158): refuse an exact profile's unsupported operation before queueing.

Review, the Reprocess panel, mask edits and photo-optimize all hand their immutable NJRs to one boundary. This function
runs the shared, pure operation assessment over the *whole* batch first, then crosses the existing
``JobService.submit_njrs`` boundary exactly once, so a refused request admits nothing and changes nothing. It builds no
job, owns no queue and no runner, and does not replace backend validation, which still validates every admitted job.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from src.controller.submission_policy_v26 import SubmissionPolicy
from src.image_backends.masked_inpaint import validate_frozen_mask_target
from src.image_backends.operation_compatibility import require_njr_operation
from src.pipeline.image_edit_inputs import KEY, verified_inputs


def submit_reprocess_njrs(job_service: Any, njrs: list[Any]) -> int:
    if not job_service:
        raise RuntimeError("Job service not available")
    if not njrs:
        return 0
    for njr in njrs:
        if getattr(getattr(njr, "workload_kind", None), "value", "") == "image":
            require_njr_operation(njr)
            edit = getattr(njr, "config", {}).get("img2img", {})
            if isinstance(edit, Mapping) and KEY in edit:
                validate_frozen_mask_target(
                    njr.base_model or "",
                    njr.backend_options,
                    njr.config,
                    list(njr.stage_chain_labels),
                )
                if tuple(njr.stage_chain_labels) != ("img2img",) or len(njr.input_image_paths) != 1:
                    raise ValueError("Frozen mask edits require exactly one img2img source")
                verified_inputs(edit, njr.input_image_paths[0], check_original=True)
    return len(job_service.submit_njrs(njrs, SubmissionPolicy()))
