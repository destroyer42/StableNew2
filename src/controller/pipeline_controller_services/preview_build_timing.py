"""Preview build timing evidence (extracted from ``PipelineController``; behavior unchanged)."""

from __future__ import annotations

import logging
from typing import Any

from src.utils import LogContext, log_with_ctx

PREVIEW_BUILD_TIMING_INFO_MS = 150.0
PREVIEW_BUILD_TIMING_WARN_MS = 1000.0


def record_preview_build_timing(
    logger: logging.Logger,
    *,
    source: str,
    elapsed_ms: float,
    job_count: int,
    pack_entry_count: int,
    error: str | None = None,
) -> dict[str, Any]:
    """The timing payload for one preview build; slow or failed builds are also logged."""

    payload = {
        "source": source,
        "elapsed_ms": round(float(elapsed_ms), 3),
        "job_count": int(job_count),
        "pack_entry_count": int(pack_entry_count),
        "error": error,
    }
    if error is None and elapsed_ms < PREVIEW_BUILD_TIMING_INFO_MS:
        return payload
    level = (
        logging.WARNING
        if error is not None or elapsed_ms >= PREVIEW_BUILD_TIMING_WARN_MS
        else logging.INFO
    )
    log_with_ctx(
        logger,
        level,
        "Preview build timing",
        ctx=LogContext(subsystem="pipeline_controller", stage="preview_build"),
        extra_fields=payload,
    )
    return payload


__all__ = [
    "PREVIEW_BUILD_TIMING_INFO_MS",
    "PREVIEW_BUILD_TIMING_WARN_MS",
    "record_preview_build_timing",
]
