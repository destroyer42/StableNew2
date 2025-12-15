# Subsystem: Queue
# Role: Implements the in-memory job queue contract.

"""In-memory job queue with simple priority + FIFO behavior.

PR-CORE1-B2: For jobs created after v2.6, NormalizedJobRecord (NJR) is required
for execution. The pipeline_config field is legacy-only and should not be relied
upon for new queue jobs.
"""

from __future__ import annotations

import heapq
from threading import Lock
from typing import Callable, Dict, Iterable, List, Optional, TYPE_CHECKING

from src.queue.job_model import Job, JobPriority, JobStatus
from src.queue.job_history_store import JobHistoryStore

if TYPE_CHECKING:  # pragma: no cover
    from datetime import datetime


class JobQueue:
    """Thread-safe in-memory job queue."""

    _FINAL_STATUSES = {JobStatus.COMPLETED, JobStatus.FAILED, JobStatus.CANCELLED}

    def __init__(self, *, history_store: JobHistoryStore | None = None) -> None:
        self._queue: list[tuple[int, int, str]] = []
        self._jobs: Dict[str, Job] = {}
        self._counter = 0
        self._lock = Lock()
        self._history_store = history_store
        self._finalized_jobs: dict[str, Job] = {}
        self._status_callbacks: list[Callable[[Job, JobStatus], None]] = []
        self._state_listeners: list[Callable[[], None]] = []

    def submit(self, job: Job) -> None:
        with self._lock:
            self._counter += 1
            self._jobs[job.job_id] = job
            heapq.heappush(self._queue, (-int(job.priority), self._counter, job.job_id))
        self._record_submission(job)
        self._notify_state_listeners()

    def get_next_job(self) -> Optional[Job]:
        with self._lock:
            while self._queue:
                _, _, job_id = heapq.heappop(self._queue)
                job = self._jobs.get(job_id)
                if job and job.status == JobStatus.QUEUED:
                    return job
            return None

    def mark_running(self, job_id: str) -> None:
        self._update_status(job_id, JobStatus.RUNNING)

    def mark_completed(self, job_id: str, result: dict | None = None) -> None:
        self._update_status(job_id, JobStatus.COMPLETED, result=result)

    def mark_failed(self, job_id: str, error_message: str, result: dict | None = None) -> None:
        job = self._update_status(job_id, JobStatus.FAILED, error_message, result=result)
        if job:
            job.error_message = error_message

    def mark_cancelled(self, job_id: str, reason: str | None = None) -> Job | None:
        return self._update_status(job_id, JobStatus.CANCELLED, reason or "cancelled")

    def list_jobs(self, status_filter: JobStatus | None = None) -> List[Job]:
        with self._lock:
            if status_filter is None:
                return list(self._jobs.values())
            return [job for job in self._jobs.values() if job.status == status_filter]

    def get_job(self, job_id: str) -> Optional[Job]:
        with self._lock:
            job = self._jobs.get(job_id)
            if job is not None:
                return job
            return self._finalized_jobs.get(job_id)

    def _update_status(
        self,
        job_id: str,
        status: JobStatus,
        error_message: str | None = None,
        result: dict | None = None,
    ) -> Job | None:
        with self._lock:
            job = self._jobs.get(job_id)
            if job is None:
                return None
            job.mark_status(status, error_message)
            if result is not None:
                job.result = result
            ts = job.updated_at
            should_prune = status in self._FINAL_STATUSES and self._history_store is not None
            if should_prune:
                self._finalized_jobs[job_id] = job
                self._prune_job(job_id)
        self._record_status(job_id, status, ts, error_message, result=result)
        self._notify_status(job, status)
        self._notify_state_listeners()
        return job

    def _record_submission(self, job: Job) -> None:
        if not self._history_store:
            return
        try:
            self._history_store.record_job_submission(job)
        except Exception:
            pass

    def _record_status(
        self,
        job_id: str,
        status: JobStatus,
        ts: "datetime",
        error: str | None,
        result: dict | None,
    ) -> None:
        if not self._history_store:
            return
        try:
            self._history_store.record_status_change(job_id, status, ts, error, result=result)
        except Exception:
            pass

    def register_status_callback(
        self, callback: Callable[[Job, JobStatus], None]
    ) -> None:
        """Allow observers to react to job status changes."""
        self._status_callbacks.append(callback)

    def _notify_status(self, job: Job, status: JobStatus) -> None:
        """Notify registered callbacks about status transitions."""
        for callback in list(self._status_callbacks):
            try:
                callback(job, status)
            except Exception:
                continue

    # ------------------------------------------------------------------
    # PR-GUI-F2: Queue Manipulation Methods
    # ------------------------------------------------------------------

    def move_up(self, job_id: str) -> bool:
        """Move a queued job up one position (higher priority).
        
        Args:
            job_id: The ID of the job to move.
            
        Returns:
            True if the job was moved, False if not found or already at top.
        """
        with self._lock:
            # Find queued jobs in order
            queued = self._get_ordered_queued_jobs()
            for i, (priority, counter, jid) in enumerate(queued):
                if jid == job_id:
                    if i == 0:
                        return False  # Already at top
                    # Swap priorities with the job above
                    prev_priority, prev_counter, prev_jid = queued[i - 1]
                    # Adjust internal queue entries
                    self._swap_queue_positions(job_id, prev_jid, priority, prev_priority)
                    self._notify_state_listeners()
                    return True
            return False

    def move_down(self, job_id: str) -> bool:
        """Move a queued job down one position (lower priority).
        
        Args:
            job_id: The ID of the job to move.
            
        Returns:
            True if the job was moved, False if not found or already at bottom.
        """
        with self._lock:
            queued = self._get_ordered_queued_jobs()
            for i, (priority, counter, jid) in enumerate(queued):
                if jid == job_id:
                    if i == len(queued) - 1:
                        return False  # Already at bottom
                    # Swap priorities with the job below
                    next_priority, next_counter, next_jid = queued[i + 1]
                    self._swap_queue_positions(job_id, next_jid, priority, next_priority)
                    self._notify_state_listeners()
                    return True
            return False

    def remove(self, job_id: str) -> Job | None:
        """Remove a job from the queue.
        
        Args:
            job_id: The ID of the job to remove.
            
        Returns:
            The removed Job, or None if not found.
        """
        with self._lock:
            job = self._jobs.pop(job_id, None)
            if job is None:
                job = self._finalized_jobs.pop(job_id, None)
            else:
                self._finalized_jobs.pop(job_id, None)
            if job:
                # Remove from heap by marking as cancelled
                job.status = JobStatus.CANCELLED
                # Rebuild queue without this job
            self._queue = [
                (p, c, jid) for (p, c, jid) in self._queue if jid != job_id
            ]
            heapq.heapify(self._queue)
            self._notify_state_listeners()
            return job

    def clear(self) -> int:
        """Clear all queued jobs (not running or completed).
        
        Returns:
            The number of jobs removed.
        """
        with self._lock:
            # Find all queued jobs
            queued_ids = [
                jid for jid, job in self._jobs.items()
                if job.status == JobStatus.QUEUED
            ]
            count = len(queued_ids)
            # Remove from jobs dict
            for jid in queued_ids:
                self._jobs.pop(jid, None)
                self._finalized_jobs.pop(jid, None)
            # Rebuild queue without queued jobs
            self._queue = [
                (p, c, jid) for (p, c, jid) in self._queue
                if jid not in queued_ids
            ]
            heapq.heapify(self._queue)
            self._notify_state_listeners()
            return count

    def _get_ordered_queued_jobs(self) -> list[tuple[int, int, str]]:
        """Get queued jobs in priority order (internal, must hold lock)."""
        queued = []
        for priority, counter, jid in self._queue:
            job = self._jobs.get(jid)
            if job and job.status == JobStatus.QUEUED:
                queued.append((priority, counter, jid))
        # Sort by priority (higher first), then by counter (lower first)
        queued.sort(key=lambda x: (x[0], x[1]))
        return queued

    def _swap_queue_positions(
        self, job_id1: str, job_id2: str, priority1: int, priority2: int
    ) -> None:
        """Swap queue positions between two jobs (internal, must hold lock)."""
        # We swap by adjusting counter values since priority might be the same
        new_queue = []
        for priority, counter, jid in self._queue:
            if jid == job_id1:
                # Give it the other job's counter (position)
                new_queue.append((priority2, counter, jid))
            elif jid == job_id2:
                new_queue.append((priority1, counter, jid))
            else:
                new_queue.append((priority, counter, jid))
        self._queue = new_queue
        heapq.heapify(self._queue)

    def _prune_job(self, job_id: str) -> None:
        """Remove a terminal job from the queue heap."""
        self._jobs.pop(job_id, None)
        self._queue = [(p, c, jid) for (p, c, jid) in self._queue if jid != job_id]
        heapq.heapify(self._queue)

    def register_state_listener(self, callback: Callable[[], None]) -> None:
        """Register a listener for queue state changes."""
        if callback not in self._state_listeners:
            self._state_listeners.append(callback)

    def _notify_state_listeners(self) -> None:
        """Notify listeners that the queue state has changed."""
        for listener in list(self._state_listeners):
            try:
                listener()
            except Exception:
                continue

    def restore_jobs(self, jobs: Iterable[Job]) -> None:
        """Restore queued jobs without recording submissions."""
        with self._lock:
            for job in jobs:
                self._counter += 1
                job.status = JobStatus.QUEUED
                self._jobs[job.job_id] = job
                heapq.heappush(self._queue, (-int(job.priority), self._counter, job.job_id))
        self._notify_state_listeners()
