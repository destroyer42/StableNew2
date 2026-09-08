from __future__ import annotations

import logging
from typing import Any

from src.utils import LogContext, log_with_ctx


def dispatch_next_now(service: Any, *, logger: logging.Logger) -> bool:
    """Dispatch one queued job when auto-run is disabled, otherwise start worker."""
    is_paused = getattr(service.job_queue, "is_paused", None)
    if callable(is_paused) and is_paused():
        log_with_ctx(
            logger,
            logging.INFO,
            "Manual queue dispatch blocked while queue is paused",
            ctx=LogContext(subsystem="job_service"),
        )
        service._set_queue_status("paused")
        return False
    if not service.auto_run_enabled:
        run_next_once = getattr(service.runner, "run_next_once", None)
        if callable(run_next_once):
            return bool(run_next_once())
    if not service.runner.is_running():
        log_with_ctx(
            logger,
            logging.INFO,
            "Starting queue worker for manual execution",
            ctx=LogContext(subsystem="job_service"),
        )
        service._ensure_runner_started()
    else:
        log_with_ctx(
            logger,
            logging.DEBUG,
            "Queue worker already running",
            ctx=LogContext(subsystem="job_service"),
        )
    return True
