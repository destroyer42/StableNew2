"""Continuous-dispatch policy owned by the JobService boundary."""

from __future__ import annotations

from typing import TYPE_CHECKING

from src.queue.job_model import JobStatus

if TYPE_CHECKING:
    from src.controller.job_service import JobService


def bind_continuous_dispatch_policy(service: JobService) -> None:
    """Bind the runner's pre-claim policy to the authoritative service flag."""
    configure = getattr(service.runner, "set_continuous_dispatch_allowed", None)
    if callable(configure):
        configure(lambda: service.auto_run_enabled)


def set_auto_run_enabled(
    service: JobService, enabled: bool, *, start_if_ready: bool = False
) -> None:
    """Set continuous dispatch without cancelling an active job."""
    service.auto_run_enabled = bool(enabled)
    if (
        service.auto_run_enabled
        and start_if_ready
        and not service.job_queue.is_paused()
        and service.job_queue.list_jobs(status_filter=JobStatus.QUEUED)
    ):
        service._ensure_runner_started()


def retire_idle_runner_for_pause(service: JobService) -> None:
    """Retire the worker on Pause only when it is idle.

    ``JobQueue`` already refuses new claims atomically while paused, and the active job is never cancelled by
    Pause. Joining a worker that is mid-job would block the caller for the whole stop timeout and leave a stop
    request that a quick Resume cannot cancel, stranding the queue.
    """
    if not service.job_queue.list_jobs(status_filter=JobStatus.RUNNING):
        service._stop_runner()  # noqa: SLF001 - JobService lifecycle helper owned by this boundary
