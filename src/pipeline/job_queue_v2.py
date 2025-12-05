"""V2 Job Queue with ordering, persistence, and auto-run support."""

from __future__ import annotations

import logging
from collections.abc import Callable
from datetime import datetime
from typing import Any

from src.pipeline.job_models_v2 import JobStatusV2, QueueJobV2

logger = logging.getLogger(__name__)


class JobQueueV2:
    """
    V2 Queue system with:
    - Ordered job list
    - Move up/down operations
    - Persistence serialization
    - Auto-run support
    - Running job tracking
    """

    def __init__(self) -> None:
        self._jobs: list[QueueJobV2] = []
        self._running_job: QueueJobV2 | None = None
        self._auto_run_enabled: bool = False
        self._is_paused: bool = False
        self._listeners: list[Callable[[], None]] = []

    @property
    def jobs(self) -> list[QueueJobV2]:
        """Get list of queued jobs (not including running job)."""
        return list(self._jobs)

    @property
    def running_job(self) -> QueueJobV2 | None:
        """Get the currently running job, if any."""
        return self._running_job

    @property
    def is_paused(self) -> bool:
        """Check if queue processing is paused."""
        return self._is_paused

    @property
    def auto_run_enabled(self) -> bool:
        """Check if auto-run is enabled."""
        return self._auto_run_enabled

    @auto_run_enabled.setter
    def auto_run_enabled(self, value: bool) -> None:
        """Set auto-run enabled state."""
        self._auto_run_enabled = value
        self._notify_listeners()

    def add_listener(self, callback: Callable[[], None]) -> None:
        """Add a listener to be notified on queue changes."""
        if callback not in self._listeners:
            self._listeners.append(callback)

    def remove_listener(self, callback: Callable[[], None]) -> None:
        """Remove a queue change listener."""
        if callback in self._listeners:
            self._listeners.remove(callback)

    def _notify_listeners(self) -> None:
        """Notify all listeners of queue state change."""
        for listener in self._listeners:
            try:
                listener()
            except Exception as e:
                logger.warning(f"Queue listener error: {e}")

    def add_job(self, job: QueueJobV2) -> None:
        """Add a job to the end of the queue."""
        job.status = JobStatusV2.QUEUED
        self._jobs.append(job)
        logger.info(f"Job added to queue: {job.job_id}")
        self._notify_listeners()

    def add_jobs(self, jobs: list[QueueJobV2]) -> None:
        """Add multiple jobs to the end of the queue."""
        for job in jobs:
            job.status = JobStatusV2.QUEUED
            self._jobs.append(job)
            logger.info(f"Job added to queue: {job.job_id}")
        self._notify_listeners()

    def remove_job(self, job_id: str) -> QueueJobV2 | None:
        """Remove a job from the queue by ID."""
        for i, job in enumerate(self._jobs):
            if job.job_id == job_id:
                removed = self._jobs.pop(i)
                logger.info(f"Job removed from queue: {job_id}")
                self._notify_listeners()
                return removed
        return None

    def get_job(self, job_id: str) -> QueueJobV2 | None:
        """Get a job by ID."""
        for job in self._jobs:
            if job.job_id == job_id:
                return job
        if self._running_job and self._running_job.job_id == job_id:
            return self._running_job
        return None

    def move_job_up(self, job_id: str) -> bool:
        """Move a job up one position in the queue."""
        for i, job in enumerate(self._jobs):
            if job.job_id == job_id:
                if i > 0:
                    self._jobs[i], self._jobs[i - 1] = self._jobs[i - 1], self._jobs[i]
                    logger.info(f"Job moved up: {job_id}")
                    self._notify_listeners()
                    return True
                return False
        return False

    def move_job_down(self, job_id: str) -> bool:
        """Move a job down one position in the queue."""
        for i, job in enumerate(self._jobs):
            if job.job_id == job_id:
                if i < len(self._jobs) - 1:
                    self._jobs[i], self._jobs[i + 1] = self._jobs[i + 1], self._jobs[i]
                    logger.info(f"Job moved down: {job_id}")
                    self._notify_listeners()
                    return True
                return False
        return False

    def clear_queue(self) -> int:
        """Clear all queued jobs (not the running job). Returns count of removed jobs."""
        count = len(self._jobs)
        self._jobs.clear()
        logger.info(f"Queue cleared: {count} jobs removed")
        self._notify_listeners()
        return count

    def get_next_job(self) -> QueueJobV2 | None:
        """Get the next job to run (first in queue) without removing it."""
        if self._jobs:
            return self._jobs[0]
        return None

    def start_next_job(self) -> QueueJobV2 | None:
        """
        Pop the next job from queue and mark it as running.
        Returns None if queue is empty or paused.
        """
        if self._is_paused:
            logger.debug("Queue is paused, not starting next job")
            return None
        if self._running_job is not None:
            logger.debug("A job is already running")
            return None
        if not self._jobs:
            logger.debug("Queue is empty")
            return None

        job = self._jobs.pop(0)
        job.status = JobStatusV2.RUNNING
        job.started_at = datetime.now()
        self._running_job = job
        logger.info(f"Started job: {job.job_id}")
        self._notify_listeners()
        return job

    def complete_running_job(self, success: bool = True, error_message: str | None = None) -> QueueJobV2 | None:
        """Mark the running job as completed or failed."""
        if self._running_job is None:
            return None

        job = self._running_job
        job.completed_at = datetime.now()
        job.progress = 1.0 if success else job.progress

        if success:
            job.status = JobStatusV2.COMPLETED
            logger.info(f"Job completed: {job.job_id}")
        else:
            job.status = JobStatusV2.FAILED
            job.error_message = error_message
            logger.warning(f"Job failed: {job.job_id} - {error_message}")

        self._running_job = None
        self._notify_listeners()
        return job

    def cancel_running_job(self, return_to_queue: bool = False) -> QueueJobV2 | None:
        """
        Cancel the running job.
        If return_to_queue is True, the job is returned to the bottom of the queue.
        """
        if self._running_job is None:
            return None

        job = self._running_job
        self._running_job = None

        if return_to_queue:
            job.status = JobStatusV2.QUEUED
            job.started_at = None
            job.progress = 0.0
            self._jobs.append(job)
            logger.info(f"Job cancelled and returned to queue: {job.job_id}")
        else:
            job.status = JobStatusV2.CANCELLED
            job.completed_at = datetime.now()
            logger.info(f"Job cancelled: {job.job_id}")

        self._notify_listeners()
        return job

    def update_job_progress(self, progress: float, eta_seconds: float | None = None) -> None:
        """Update progress of the running job."""
        if self._running_job:
            self._running_job.progress = max(0.0, min(1.0, progress))
            self._running_job.eta_seconds = eta_seconds
            self._notify_listeners()

    def pause_queue(self) -> None:
        """Pause queue processing (won't start new jobs)."""
        if not self._is_paused:
            self._is_paused = True
            logger.info("Queue paused")
            self._notify_listeners()

    def resume_queue(self) -> None:
        """Resume queue processing."""
        if self._is_paused:
            self._is_paused = False
            logger.info("Queue resumed")
            self._notify_listeners()

    def pause_running_job(self) -> bool:
        """Pause the currently running job."""
        if self._running_job and self._running_job.status == JobStatusV2.RUNNING:
            self._running_job.status = JobStatusV2.PAUSED
            logger.info(f"Job paused: {self._running_job.job_id}")
            self._notify_listeners()
            return True
        return False

    def resume_running_job(self) -> bool:
        """Resume the paused running job."""
        if self._running_job and self._running_job.status == JobStatusV2.PAUSED:
            self._running_job.status = JobStatusV2.RUNNING
            logger.info(f"Job resumed: {self._running_job.job_id}")
            self._notify_listeners()
            return True
        return False

    def serialize(self) -> dict[str, Any]:
        """Serialize queue state for persistence."""
        jobs_data = []
        for job in self._jobs:
            jobs_data.append(job.to_dict())

        # Include running job (will be treated as interrupted on restore)
        if self._running_job:
            running_data = self._running_job.to_dict()
            running_data["was_running"] = True
            jobs_data.insert(0, running_data)

        return {
            "jobs": jobs_data,
            "auto_run_enabled": self._auto_run_enabled,
            "is_paused": self._is_paused,
        }

    def restore(self, data: dict[str, Any]) -> None:
        """Restore queue state from persisted data."""
        self._jobs.clear()
        self._running_job = None

        self._auto_run_enabled = bool(data.get("auto_run_enabled", False))
        self._is_paused = bool(data.get("is_paused", False))

        jobs_data = data.get("jobs", [])
        for job_data in jobs_data:
            try:
                job = QueueJobV2.from_dict(job_data)
                # Jobs that were running when app closed go back to queue
                if job_data.get("was_running") or job.status == JobStatusV2.RUNNING:
                    job.status = JobStatusV2.QUEUED
                    job.started_at = None
                    job.progress = 0.0
                if job.status == JobStatusV2.QUEUED:
                    self._jobs.append(job)
            except Exception as e:
                logger.warning(f"Failed to restore job: {e}")

        logger.info(f"Queue restored: {len(self._jobs)} jobs, auto_run={self._auto_run_enabled}")
        self._notify_listeners()

    def __len__(self) -> int:
        return len(self._jobs)

    def is_empty(self) -> bool:
        return len(self._jobs) == 0 and self._running_job is None


__all__ = ["JobQueueV2"]
