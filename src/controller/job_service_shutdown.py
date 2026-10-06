"""Shutdown admission fence and runner quiescence owned at the JobService boundary (PR-RUNTIME-SHUTDOWN-140).

``JobService`` already owns continuous-dispatch policy; this module owns the *terminal* counterpart used when the
application is closing, plus the inspectable "has every worker stopped" answer that repository closure depends on.
It adds no queue, runner or lifecycle authority: SQLite stays the only lifecycle authority, the atomic claim
boundary stays in ``JobQueue``, and worker threads stay owned by the runner.
"""

from __future__ import annotations

import inspect
import logging
from typing import TYPE_CHECKING, Any

from src.utils import LogContext, log_with_ctx

if TYPE_CHECKING:
    from src.controller.job_service import JobService

logger = logging.getLogger(__name__)

DEFAULT_STOP_TIMEOUT_SECONDS = 10.0


def is_shutting_down(service: JobService) -> bool:
    return bool(getattr(service, "_shutting_down", False))


def begin_shutdown(service: JobService) -> None:
    """Fence queue admission for good (idempotent): no QUEUED job can newly acquire RUNNING ownership.

    The queue fence is the atomic boundary (it is checked under the same lock as the claim and its durable
    transition); the runner is then retired so no worker starts or hands off. The job that is already RUNNING and
    the QUEUED backlog are untouched, and ``auto_run_enabled`` (the user's startup preference) is not changed.
    """
    service._shutting_down = True  # noqa: SLF001 - JobService state, owned by this boundary
    service.job_queue.fence_dispatch()
    fence = getattr(service.runner, "begin_shutdown", None)
    if callable(fence):
        fence()


def is_quiescent(service: JobService) -> bool:
    """True when no worker owned by the service's runner can still call a queue/repository method."""
    runner = service.runner
    query = getattr(runner, "is_quiescent", None)
    if callable(query):
        return bool(query())
    return not bool(runner.is_running())  # a runner that cannot inspect its threads: best available evidence


def stop_with_timeout(target: Any, timeout: float) -> Any:
    """Call ``target.stop(timeout=...)`` when it accepts a timeout, else ``target.stop()``; return its result."""
    try:
        accepts_timeout = "timeout" in inspect.signature(target.stop).parameters
    except (TypeError, ValueError):
        accepts_timeout = False
    return target.stop(timeout=timeout) if accepts_timeout else target.stop()


def stop_runner(service: JobService, timeout: float | None = None) -> bool:
    """Stop the runner (bounded) and report whether it has definitively quiesced.

    A join that returned at its timeout is not quiescence; the result is the runner's own inspectable state.
    A one-shot (Run Now) worker is stopped too, even though the service never marked a continuous worker started.
    """
    limit = DEFAULT_STOP_TIMEOUT_SECONDS if timeout is None else float(timeout)
    with service._runner_lock:  # noqa: SLF001
        if not service._worker_started and is_quiescent(service):  # noqa: SLF001
            return True
        log_with_ctx(
            logger,
            logging.INFO,
            "Queue worker stopping (runner=%s)",
            ctx=LogContext(subsystem="job_service"),
            extra_fields={"runner": type(service.runner).__name__},
        )
        stop_with_timeout(service.runner, limit)
        service._worker_started = False  # noqa: SLF001
    return is_quiescent(service)
