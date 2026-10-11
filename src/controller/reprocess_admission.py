"""Reprocess admission preflight (PR-IMG-MODELS-158): refuse an exact profile's unsupported operation before queueing.

Review, the Reprocess panel, mask edits and photo-optimize all hand their immutable NJRs to one boundary. This function
runs the shared, pure operation assessment over the *whole* batch first, then crosses the existing
``JobService.submit_njrs`` boundary exactly once, so a refused request admits nothing and changes nothing. It builds no
job, owns no queue and no runner, and does not replace backend validation, which still validates every admitted job.
"""

from __future__ import annotations

from typing import Any

from src.controller.submission_policy_v26 import SubmissionPolicy
from src.image_backends.operation_compatibility import require_njr_operation


def submit_reprocess_njrs(job_service: Any, njrs: list[Any]) -> int:
    if not job_service:
        raise RuntimeError("Job service not available")
    if not njrs:
        return 0
    for njr in njrs:
        if getattr(getattr(njr, "workload_kind", None), "value", "") == "image":
            require_njr_operation(njr)
    return len(job_service.submit_njrs(njrs, SubmissionPolicy()))
