# Subsystem: Queue
# Role: Provides the runnable projection of the durable job repository.

"""Thread-safe runnable projection with priority + FIFO behavior.

PR-CORE1-060: queue runtime is NJR-only for active jobs. Queue items rely on
`_normalized_record`, `config_snapshot`, and `snapshot`, not `pipeline_config`.
"""

from __future__ import annotations

import heapq
from collections import deque
from collections.abc import Callable, Iterable
from threading import Lock
from typing import Any

from src.queue.job_model import Job, JobStatus
from src.queue.job_repository import JobRepository


class JobQueue:
    """Thread-safe runnable projection of one authoritative repository."""

    _FINAL_STATUSES = {JobStatus.COMPLETED, JobStatus.FAILED, JobStatus.CANCELLED}

    def __init__(
        self,
        *,
        repository: JobRepository | None = None,
        history_store: JobRepository | None = None,
    ) -> None:
        if repository is not None and history_store is not None and repository is not history_store:
            raise ValueError("JobQueue accepts exactly one JobRepository authority")
        selected = repository or history_store
        if selected is not None and not isinstance(selected, JobRepository):
            raise TypeError("JSON/JSONL stores cannot be attached to the live queue")
        self._repository = selected or JobRepository()
        self._queue: list[tuple[int, int, str]] = []
        self._jobs: dict[str, Job] = {}
        self._counter = 0
        self._lock = Lock()
        self._paused = False
        self._history_store = self._repository
        # PR-MEMORY-001: Bounded finalized jobs (max 100) using deque for FIFO eviction
        self._finalized_jobs_order: deque[str] = deque(maxlen=100)
        self._finalized_jobs: dict[str, Job] = {}
        self._status_callbacks: list[Callable[[Job, JobStatus], None]] = []
        self._state_listeners: list[Callable[[], None]] = []
        self._state_notifications_suppressed = 0
        self._state_notifications_pending = False
        self._restore_repository_projection()

    @property
    def repository(self) -> JobRepository:
        return self._repository

    def _restore_repository_projection(self) -> None:
        for job in self._repository.load_runnable_jobs(recover_interrupted=True):
            job._persist_runtime_state = lambda current=job: self.persist_runtime_state(current)
            self._counter += 1
            self._jobs[job.job_id] = job
            heapq.heappush(self._queue, (-int(job.priority), self._counter, job.job_id))
        self._paused = bool(self._repository.get_setting("queue_paused", False))

    def submit(self, job: Job) -> None:
        self._repository.record_job_submission(job)
        job._persist_runtime_state = lambda current=job: self.persist_runtime_state(current)
        with self._lock:
            self._counter += 1
            self._jobs[job.job_id] = job
            heapq.heappush(self._queue, (-int(job.priority), self._counter, job.job_id))
        self._notify_state_listeners()

    def get_next_job(self) -> Job | None:
        with self._lock:
            if self._paused:
                return None
            while self._queue:
                _, _, job_id = heapq.heappop(self._queue)
                job = self._jobs.get(job_id)
                if job and job.status == JobStatus.QUEUED:
                    return job
            return None

    def pause(self) -> None:
        self._repository.set_setting("queue_paused", True)
        with self._lock:
            self._paused = True
        self._notify_state_listeners()

    def resume(self) -> None:
        self._repository.set_setting("queue_paused", False)
        with self._lock:
            self._paused = False
        self._notify_state_listeners()

    def is_paused(self) -> bool:
        with self._lock:
            return bool(self._paused)

    def pause_running_job(self) -> Job | None:
        self.pause()
        with self._lock:
            return next((job for job in self._jobs.values() if job.status == JobStatus.RUNNING), None)

    def resume_running_job(self) -> Job | None:
        self.resume()
        with self._lock:
            return next((job for job in self._jobs.values() if job.status == JobStatus.RUNNING), None)

    def cancel_running_job(self, *, return_to_queue: bool = False) -> Job | None:
        with self._lock:
            running = next((job for job in self._jobs.values() if job.status == JobStatus.RUNNING), None)
            if running is None:
                return None
        if return_to_queue:
            running.execution_metadata.last_control_action = "return_to_queue"
            running.execution_metadata.return_to_queue_count += 1
            running.progress = 0.0
            running.eta_seconds = None
            running.error_message = None
            running.result = None
            persisted = self._repository.transition_job(running, JobStatus.QUEUED)
            with self._lock:
                self._copy_persisted_state(running, persisted)
                self._counter += 1
                self._queue = [(p, c, jid) for (p, c, jid) in self._queue if jid != running.job_id]
                heapq.heappush(self._queue, (-int(running.priority), self._counter, running.job_id))
                heapq.heapify(self._queue)
            self._notify_status(running, JobStatus.QUEUED)
            self._notify_state_listeners()
        else:
            running.execution_metadata.last_control_action = "cancelled"
            cancelled = self._update_status(running.job_id, JobStatus.CANCELLED, "cancelled")
        return running

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

    def list_jobs(self, status_filter: JobStatus | None = None) -> list[Job]:
        with self._lock:
            if status_filter is None:
                return list(self._jobs.values())
            return [job for job in self._jobs.values() if job.status == status_filter]

    def list_active_jobs_ordered(self) -> list[Job]:
        """Return running + queued jobs in display order.

        Running jobs appear first, followed by queued jobs in actual queue order.
        """
        with self._lock:
            running_jobs = [job for job in self._jobs.values() if job.status == JobStatus.RUNNING]
            queued_jobs = [
                self._jobs[jid]
                for _, _, jid in self._get_ordered_queued_jobs()
                if jid in self._jobs
            ]
            return running_jobs + queued_jobs

    def get_job(self, job_id: str) -> Job | None:
        with self._lock:
            job = self._jobs.get(job_id)
            if job is not None:
                return job
            finalized = self._finalized_jobs.get(job_id)
        return finalized or self._repository.get_job_model(job_id)

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
        persisted = self._repository.transition_job(
            job,
            status,
            error_message=error_message,
            result=result,
        )
        with self._lock:
            self._copy_persisted_state(job, persisted)
            should_prune = status in self._FINAL_STATUSES
            if should_prune:
                # PR-MEMORY-001: Add to bounded finalized jobs collection
                self._add_finalized_job(job_id, job)
                self._prune_job(job_id)
        self._notify_status(job, status)
        self._notify_state_listeners()
        return job

    def claim_next_job(self) -> Job | None:
        """Atomically claim the next runnable job for the single-node worker."""
        claimed: Job | None = None
        with self._lock:
            if self._paused:
                return None
            while self._queue:
                queue_item = heapq.heappop(self._queue)
                job = self._jobs.get(queue_item[2])
                if job is None or job.status != JobStatus.QUEUED:
                    continue
                try:
                    persisted = self._repository.transition_job(job, JobStatus.RUNNING)
                except Exception:
                    heapq.heappush(self._queue, queue_item)
                    raise
                self._copy_persisted_state(job, persisted)
                claimed = job
                break
        if claimed is not None:
            self._notify_status(claimed, JobStatus.RUNNING)
            self._notify_state_listeners()
        return claimed

    def _add_finalized_job(self, job_id: str, job: Job) -> None:
        """Add job to bounded finalized collection.
        
        PR-MEMORY-001: Maintains max 100 finalized jobs. When full, evicts oldest.
        Also clears job payload to free memory.
        """
        # Clear payload to free memory (PR-MEMORY-001)
        job.payload = None
        
        # Check if deque is full and will evict oldest
        if len(self._finalized_jobs_order) == self._finalized_jobs_order.maxlen:
            # Get the oldest job_id that will be evicted
            oldest_jid = self._finalized_jobs_order[0] if self._finalized_jobs_order else None
            if oldest_jid and oldest_jid in self._finalized_jobs:
                self._finalized_jobs.pop(oldest_jid, None)
        
        # Add new job (deque will auto-evict if at maxlen)
        self._finalized_jobs_order.append(job_id)
        self._finalized_jobs[job_id] = job

    @staticmethod
    def _copy_persisted_state(target: Job, source: Job) -> None:
        for name in (
            "status",
            "updated_at",
            "started_at",
            "completed_at",
            "progress",
            "eta_seconds",
            "worker_id",
            "execution_metadata",
            "error_message",
            "error_envelope",
            "result",
        ):
            setattr(target, name, getattr(source, name))

    def persist_runtime_state(self, job: Job) -> None:
        """Durably checkpoint mutable execution metadata for an active job."""
        self._repository.persist_runtime_state(job)

    def register_status_callback(self, callback: Callable[[Job, JobStatus], None]) -> None:
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
        moved = False
        with self._lock:
            # Find queued jobs in order
            queued = self._get_ordered_queued_jobs()
            for i, (priority, counter, jid) in enumerate(queued):
                if jid == job_id:
                    if i == 0:
                        return False  # Already at top
                    # Swap counters with the job above to change ordering
                    prev_priority, prev_counter, prev_jid = queued[i - 1]
                    if priority != prev_priority:
                        return False
                    candidate = list(queued)
                    candidate[i - 1], candidate[i] = candidate[i], candidate[i - 1]
                    self._repository.update_queue_order([item[2] for item in candidate])
                    self._swap_queue_positions(job_id, prev_jid, counter, prev_counter)
                    moved = True
                    break
        if moved:
            self._notify_state_listeners()
        return moved

    def move_down(self, job_id: str) -> bool:
        """Move a queued job down one position (lower priority).

        Args:
            job_id: The ID of the job to move.

        Returns:
            True if the job was moved, False if not found or already at bottom.
        """
        moved = False
        with self._lock:
            queued = self._get_ordered_queued_jobs()
            for i, (priority, counter, jid) in enumerate(queued):
                if jid == job_id:
                    if i == len(queued) - 1:
                        return False  # Already at bottom
                    # Swap counters with the job below to change ordering
                    next_priority, next_counter, next_jid = queued[i + 1]
                    if priority != next_priority:
                        return False
                    candidate = list(queued)
                    candidate[i], candidate[i + 1] = candidate[i + 1], candidate[i]
                    self._repository.update_queue_order([item[2] for item in candidate])
                    self._swap_queue_positions(job_id, next_jid, counter, next_counter)
                    moved = True
                    break
        if moved:
            self._notify_state_listeners()
        return moved

    def move_to_front(self, job_id: str) -> bool:
        """Move a queued job to the front of the queue (highest priority within its priority level).

        Args:
            job_id: The ID of the job to move.

        Returns:
            True if the job was moved, False if not found or already at front.
        """
        moved = False
        with self._lock:
            queued = self._get_ordered_queued_jobs()
            if not queued:
                return False
            
            # Find the job
            job_index = None
            job_priority = None
            for i, (priority, counter, jid) in enumerate(queued):
                if jid == job_id:
                    job_index = i
                    job_priority = priority
                    break
            
            if job_index is None:
                return False  # Job not found
            
            if job_index == 0:
                return False  # Already at front
            
            # Get the minimum counter value (front of queue) for this priority
            # We want to assign a counter lower than the first job in the same priority level
            min_counter_for_priority = float('inf')
            for priority, counter, jid in queued:
                if priority == job_priority:
                    min_counter_for_priority = min(min_counter_for_priority, counter)
            
            # Assign a new lower counter (move to front)
            new_counter = min_counter_for_priority - 1
            
            candidate = [item for item in queued if item[2] != job_id]
            insert_at = next(
                (index for index, item in enumerate(candidate) if item[0] == job_priority),
                0,
            )
            candidate.insert(insert_at, queued[job_index])
            self._repository.update_queue_order([item[2] for item in candidate])

            # Update the in-memory projection after the durable order succeeds.
            new_queue = []
            for priority, counter, jid in self._queue:
                if jid == job_id:
                    new_queue.append((priority, new_counter, jid))
                else:
                    new_queue.append((priority, counter, jid))
            self._queue = new_queue
            heapq.heapify(self._queue)
            moved = True
        if moved:
            self._notify_state_listeners()
        return moved

    def move_to_back(self, job_id: str) -> bool:
        """Move a queued job to the back of the queue (lowest priority within its priority level).

        Args:
            job_id: The ID of the job to move.

        Returns:
            True if the job was moved, False if not found or already at back.
        """
        moved = False
        with self._lock:
            queued = self._get_ordered_queued_jobs()
            if not queued:
                return False
            
            # Find the job
            job_index = None
            job_priority = None
            for i, (priority, counter, jid) in enumerate(queued):
                if jid == job_id:
                    job_index = i
                    job_priority = priority
                    break
            
            if job_index is None:
                return False  # Job not found
            
            if job_index == len(queued) - 1:
                return False  # Already at back
            
            # Get the maximum counter value (back of queue) for this priority
            # We want to assign a counter higher than the last job in the same priority level
            max_counter_for_priority = float('-inf')
            for priority, counter, jid in queued:
                if priority == job_priority:
                    max_counter_for_priority = max(max_counter_for_priority, counter)
            
            # Assign a new higher counter (move to back)
            new_counter = max_counter_for_priority + 1
            
            candidate = [item for item in queued if item[2] != job_id]
            insert_at = max(
                (index for index, item in enumerate(candidate) if item[0] == job_priority),
                default=len(candidate) - 1,
            ) + 1
            candidate.insert(insert_at, queued[job_index])
            self._repository.update_queue_order([item[2] for item in candidate])

            # Update the in-memory projection after the durable order succeeds.
            new_queue = []
            for priority, counter, jid in self._queue:
                if jid == job_id:
                    new_queue.append((priority, new_counter, jid))
                else:
                    new_queue.append((priority, counter, jid))
            self._queue = new_queue
            heapq.heapify(self._queue)
            moved = True
        if moved:
            self._notify_state_listeners()
        return moved

    def remove(self, job_id: str) -> Job | None:
        """Remove a job from the queue.

        Args:
            job_id: The ID of the job to remove.

        Returns:
            The removed Job, or None if not found.
        """
        with self._lock:
            live_job = self._jobs.get(job_id)
            if live_job is None or live_job.status == JobStatus.RUNNING:
                return None
        return self.mark_cancelled(job_id, "removed from queue")

    def clear(self) -> int:
        """Clear all queued jobs (not running or completed).

        Returns:
            The number of jobs removed.
        """
        with self._lock:
            queued_ids = [jid for jid, job in self._jobs.items() if job.status == JobStatus.QUEUED]
        with self.coalesce_state_notifications():
            for job_id in queued_ids:
                self.mark_cancelled(job_id, "queue cleared")
        return len(queued_ids)

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
        self, job_id1: str, job_id2: str, counter1: int, counter2: int
    ) -> None:
        """Swap queue positions between two jobs (internal, must hold lock)."""
        # Swap counters to preserve priority ordering while reordering within priority.
        new_queue = []
        for priority, counter, jid in self._queue:
            if jid == job_id1:
                new_queue.append((priority, counter2, jid))
            elif jid == job_id2:
                new_queue.append((priority, counter1, jid))
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

    def coalesce_state_notifications(self) -> _QueueStateNotificationBatch:
        return _QueueStateNotificationBatch(self)

    def _notify_state_listeners(self) -> None:
        """Notify listeners that the queue state has changed."""
        with self._lock:
            if self._state_notifications_suppressed > 0:
                self._state_notifications_pending = True
                return
            listeners = list(self._state_listeners)
        for listener in listeners:
            try:
                listener()
            except Exception:
                continue

    def restore_jobs(self, jobs: Iterable[Job]) -> None:
        """Submit recovered jobs through repository authority.

        Offline legacy recovery should normally use the migration tool; this
        method remains for callers that already hold valid NJR-backed jobs.
        """
        with self.coalesce_state_notifications():
            for job in jobs:
                job.status = JobStatus.QUEUED
                self.submit(job)


class _QueueStateNotificationBatch:
    def __init__(self, queue: JobQueue) -> None:
        self._queue = queue

    def __enter__(self) -> _QueueStateNotificationBatch:
        with self._queue._lock:
            self._queue._state_notifications_suppressed += 1
        return self

    def __exit__(self, exc_type: Any, exc: Any, tb: Any) -> bool:
        listeners: list[Callable[[], None]] = []
        with self._queue._lock:
            self._queue._state_notifications_suppressed = max(
                0,
                self._queue._state_notifications_suppressed - 1,
            )
            should_flush = (
                self._queue._state_notifications_suppressed == 0
                and self._queue._state_notifications_pending
            )
            if should_flush:
                self._queue._state_notifications_pending = False
                listeners = list(self._queue._state_listeners)
        for listener in listeners:
            try:
                listener()
            except Exception:
                continue
        return False
