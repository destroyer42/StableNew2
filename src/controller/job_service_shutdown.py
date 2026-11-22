"""Shutdown admission fence and runner quiescence owned at the JobService boundary (PR-RUNTIME-SHUTDOWN-140).

``JobService`` already owns continuous-dispatch policy; this module owns the *terminal* counterpart used when the
application is closing, plus the inspectable "has every worker stopped" answer that repository closure depends on.
It adds no queue, runner or lifecycle authority: SQLite stays the only lifecycle authority, the atomic claim
boundary stays in ``JobQueue``, and worker threads stay owned by the runner.
"""

from __future__ import annotations

import inspect
import logging
import time
from typing import TYPE_CHECKING, Any

from src.utils import LogContext, log_with_ctx
from src.utils.thread_registry import get_thread_registry

if TYPE_CHECKING:
    from src.controller.job_service import JobService
    from src.queue.job_model import Job
    from src.utils.watchdog_v2 import JobWatchdog

logger = logging.getLogger(__name__)

DEFAULT_STOP_TIMEOUT_SECONDS = 10.0


def is_shutting_down(service: JobService) -> bool:
    return bool(getattr(service, "_shutting_down", False))


def request_shutdown(service: JobService) -> None:
    """Close admission and signal retirement without waiting on SQLite."""
    service._shutting_down = True  # noqa: SLF001 - JobService state, owned here
    service.job_queue.request_dispatch_fence()
    request = getattr(service.runner, "request_shutdown", None)
    if callable(request):
        request()


def begin_shutdown(service: JobService) -> None:
    """Fence the queue and synchronize with any already-admitted claim."""
    request_shutdown(service)
    fence = getattr(service.runner, "begin_shutdown", None)
    if callable(fence):
        fence()
    else:
        service.job_queue.fence_dispatch()


def start_job_watchdog(service: JobService, job: Job, watchdog: JobWatchdog) -> None:
    registry = get_thread_registry()

    watchdog.name = "JobWatchdog"
    service._active_watchdogs[job.job_id] = watchdog  # noqa: SLF001
    try:
        registry.start_tracked_thread(watchdog, "Queue watchdog and repository settlement")
    except RuntimeError:
        service._active_watchdogs.pop(job.job_id, None)  # noqa: SLF001
        if not registry.is_shutdown_requested():
            raise


def cancel_current_job(service: JobService, *, return_to_queue: bool) -> Any:
    """Signal a fenced runner before persistence or child cleanup can delay its token."""
    def signal_runner() -> None:
        try:
            service.runner.cancel_current(return_to_queue=return_to_queue)
        except TypeError:
            service.runner.cancel_current()

    shutting_down = is_shutting_down(service)
    if shutting_down:
        signal_runner()
    running = service._find_running_job()  # noqa: SLF001
    if running is None:
        running = getattr(service.runner, "current_job", None)
    if running and not return_to_queue:
        service.cancel_job(running.job_id, reason="cancel_requested")
    if not shutting_down:
        signal_runner()
    return running


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
    limit = DEFAULT_STOP_TIMEOUT_SECONDS if timeout is None else max(0.0, float(timeout))
    deadline = time.monotonic() + limit
    lock = service._runner_lock  # noqa: SLF001
    if not lock.acquire(timeout=limit):
        return False
    try:
        if not service._worker_started and is_quiescent(service):  # noqa: SLF001
            return True
        log_with_ctx(
            logger,
            logging.INFO,
            "Queue worker stopping (runner=%s)",
            ctx=LogContext(subsystem="job_service"),
            extra_fields={"runner": type(service.runner).__name__},
        )
        stop_with_timeout(service.runner, max(0.0, deadline - time.monotonic()))
        service._worker_started = False  # noqa: SLF001
    finally:
        lock.release()
    return is_quiescent(service)
