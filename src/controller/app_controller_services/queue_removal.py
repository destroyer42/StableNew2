"""Batched queue removal on a tracked worker (QUEUE-MULTI), so Clear All and Remove selected never block Tk.

Clearing 2,000 queued jobs froze the window for about 8 s because the Tk thread did the work. The removal itself is
``job_service_queue_batch.remove_queued_jobs`` (``JobQueue.remove_many``, one repository transaction); this only
decides where it runs and where the result is delivered. The controller's ``BackgroundTaskCoordinator`` is the tracked-worker authority and delivers through
``_ui_dispatch``, so ``on_done`` and the projection refresh run on the UI thread.
"""

from __future__ import annotations

from collections.abc import Callable, Iterable
from typing import TYPE_CHECKING, Any

from src.controller.job_service_queue_batch import remove_queued_jobs

if TYPE_CHECKING:
    from src.queue.job_queue import RemoveManyOutcome


def remove_queued_jobs_async(
    controller: Any,
    job_ids: Iterable[str] | None,
    *,
    reason: str | None = None,
    on_done: Callable[[RemoveManyOutcome | None], None] | None = None,
) -> bool:
    """Start the removal of ``job_ids`` (``None`` = every queued job); ``on_done(outcome | None)`` runs on Tk.

    Returns whether a worker was started: False without a job service or once shutdown closed admission, in which
    case nothing will call ``on_done``. Running jobs are skipped and reported by the outcome, never cancelled.
    ``None`` is delivered when the removal failed.
    """

    service = controller.job_service
    if not service:
        return False
    ids = None if job_ids is None else list(job_ids)
    label = reason or ("queue cleared" if ids is None else "removed from queue")
    controller._queue_removal_serial = getattr(controller, "_queue_removal_serial", 0) + 1

    def finish(outcome: RemoveManyOutcome | None) -> None:
        if outcome is not None and outcome.removed:
            controller._refresh_app_state_queue()
        controller._save_queue_state()
        if on_done is not None:
            on_done(outcome)

    def failed(exc: Exception) -> None:
        controller._append_log(f"[controller] queue removal error: {exc!r}")
        finish(None)

    try:
        # One key per request: the coordinator is latest-wins per key, and no request may supersede another.
        started = controller._background_tasks.submit(
            f"queue-remove:{controller._queue_removal_serial}",
            lambda: remove_queued_jobs(service, ids, label),
            on_result=finish,
            on_error=failed,
            name="QueueRemoveJobs",
            purpose="Remove queued jobs in one batch off the UI thread",
        )
    except Exception as exc:  # noqa: BLE001 - e.g. the thread registry is closing
        controller._append_log(f"[controller] queue removal not started: {exc!r}")
        return False
    return bool(started)  # 0: admission is closed (shutting down), so nothing will report back
