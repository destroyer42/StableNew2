"""Batch behaviour of the JobService queue boundary (QUEUE-MULTI): one queue-updated event per batch, batched removal.

``JobService`` reacts to every status change of every job. While the queue is inside a coalesced batch (Clear All,
Remove selected, Cancel Remaining) that reaction must not summarize the whole queue once per job: with 2,000 jobs that
was 1,999,000 summary lines. The per-job work (events, completion handlers, process cleanup) is unchanged; only the
queue-wide ``EVENT_QUEUE_UPDATED`` and the "queue is empty" check are published once, when the batch closes.

No queue, runner or lifecycle authority lives here: ``JobQueue.remove_many`` does the removal.
"""

from __future__ import annotations

import weakref
from collections.abc import Iterable
from typing import TYPE_CHECKING

from src.queue.job_model import JobStatus

if TYPE_CHECKING:
    from src.controller.job_service import JobService
    from src.queue.job_queue import RemoveManyOutcome

#: Services that owe one queue-updated event to a batch that is still open.
_OWED: weakref.WeakSet[JobService] = weakref.WeakSet()


def bind(service: JobService) -> None:
    """Flush the queue-updated event a closed batch owes, as a queue state listener."""

    register = getattr(service.job_queue, "register_state_listener", None)
    if callable(register):
        register(lambda: _flush(service))


def publish_queue_update(service: JobService) -> None:
    """Publish the queue-updated event and the empty check now, or owe them to the open batch."""

    coalescing = getattr(service.job_queue, "is_coalescing_state_notifications", None)
    if callable(coalescing) and coalescing():
        _OWED.add(service)
        return
    _publish(service)


def remove_queued_jobs(
    service: JobService, job_ids: Iterable[str] | None, reason: str
) -> RemoveManyOutcome:
    """``JobQueue.remove_many``; ``job_ids=None`` means every job that is QUEUED now. Safe off the UI thread."""

    if job_ids is None:
        job_ids = [job.job_id for job in service.job_queue.list_jobs(JobStatus.QUEUED)]
    return service.job_queue.remove_many(job_ids, reason)


def _flush(service: JobService) -> None:
    if service in _OWED:
        _OWED.discard(service)
        _publish(service)


def _publish(service: JobService) -> None:
    service._emit_queue_updated()
    if not any(job.status == JobStatus.QUEUED for job in service.job_queue.list_jobs()):
        service._emit(service.EVENT_QUEUE_EMPTY)
