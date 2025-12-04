# Subsystem: Queue
# Role: Executes queued jobs on a single node in FIFO/priority order.

"""Single-node job runner that executes jobs from an in-memory queue."""

from __future__ import annotations

import logging
import threading
import time
from typing import Callable, Optional

from src.queue.job_model import JobStatus, Job
from src.queue.job_queue import JobQueue

logger = logging.getLogger(__name__)


class SingleNodeJobRunner:
    """Background worker that executes jobs from a JobQueue."""

    def __init__(
        self,
        job_queue: JobQueue,
        run_callable: Callable[[Job], dict] | None,
        poll_interval: float = 0.1,
        on_status_change: Callable[[Job, JobStatus], None] | None = None,
    ) -> None:
        self.job_queue = job_queue
        self.run_callable = run_callable
        self.poll_interval = poll_interval
        self._stop_event = threading.Event()
        self._worker: Optional[threading.Thread] = None
        self._on_status_change = on_status_change
        self._current_job: Job | None = None
        self._cancel_current = threading.Event()

    def start(self) -> None:
        if self._worker and self._worker.is_alive():
            return
        self._stop_event.clear()
        self._worker = threading.Thread(target=self._worker_loop, daemon=True)
        self._worker.start()

    def stop(self) -> None:
        self._stop_event.set()
        if self._worker:
            self._worker.join(timeout=2.0)

    def _worker_loop(self) -> None:
        while not self._stop_event.is_set():
            job = self.job_queue.get_next_job()
            if job is None:
                time.sleep(self.poll_interval)
                continue
            self.job_queue.mark_running(job.job_id)
            self._notify(job, JobStatus.RUNNING)
            self._current_job = job
            self._cancel_current.clear()
            try:
                if self._cancel_current.is_set():
                    self.job_queue.mark_cancelled(job.job_id)
                    self._notify(job, JobStatus.CANCELLED)
                    continue
                if self.run_callable:
                    result = self.run_callable(job)
                else:
                    result = {}
                self.job_queue.mark_completed(job.job_id, result=result)
                self._notify(job, JobStatus.COMPLETED)
            except Exception as exc:  # noqa: BLE001
                logger.error("Job %s failed with error: %s", job.job_id, exc, exc_info=True)
                self.job_queue.mark_failed(job.job_id, error_message=str(exc))
                self._notify(job, JobStatus.FAILED)
            finally:
                self._current_job = None
        return

    def run_once(self, job: Job) -> dict | None:
        """Synchronously execute a single job (used by Run Now)."""
        if job is None:
            return None
        self.job_queue.mark_running(job.job_id)
        self._notify(job, JobStatus.RUNNING)
        self._current_job = job
        self._cancel_current.clear()
        try:
            if self.run_callable:
                result = self.run_callable(job)
            else:
                result = {}
            self.job_queue.mark_completed(job.job_id, result=result)
            self._notify(job, JobStatus.COMPLETED)
            return result
        except Exception as exc:  # noqa: BLE001
            logger.error("Job %s failed with error: %s", job.job_id, exc, exc_info=True)
            self.job_queue.mark_failed(job.job_id, error_message=str(exc))
            self._notify(job, JobStatus.FAILED)
            raise
        finally:
            self._current_job = None

    def _notify(self, job: Job, status: JobStatus) -> None:
        if self._on_status_change:
            try:
                self._on_status_change(job, status)
            except Exception:
                pass

    def cancel_current(self) -> None:
        self._cancel_current.set()

    def is_running(self) -> bool:
        return self._worker is not None and self._worker.is_alive()
