"""Job execution bridge for queue-backed pipeline runs."""

from __future__ import annotations

import threading
import uuid
from typing import Callable, Optional

from src.queue.job_model import Job, JobPriority, JobStatus
from src.queue.job_queue import JobQueue
from src.queue.single_node_runner import SingleNodeJobRunner
from src.queue.job_history_store import JobHistoryStore, JSONLJobHistoryStore
from pathlib import Path
from src.config.app_config import get_job_history_path
from src.cluster.worker_registry import WorkerRegistry
from src.cluster.worker_model import WorkerDescriptor


class JobExecutionController:
    """Owns JobQueue and SingleNodeJobRunner for single-node execution."""

    def __init__(
        self,
        execute_job: Callable[[Job], dict] | None = None,
        poll_interval: float = 0.05,
        history_store: JobHistoryStore | None = None,
        worker_registry: WorkerRegistry | None = None,
    ) -> None:
        self._history_store = history_store or self._default_history_store()
        self._worker_registry = worker_registry or WorkerRegistry()
        self._queue = JobQueue(history_store=self._history_store)
        self._execute_job = execute_job
        self._runner = SingleNodeJobRunner(
            self._queue, self._execute_job, poll_interval=poll_interval, on_status_change=self._on_status
        )
        self._started = False
        self._lock = threading.Lock()
        self._callbacks: dict[str, Callable[[Job, JobStatus], None]] = {}

    def start(self) -> None:
        with self._lock:
            if not self._started:
                self._runner.start()
                self._started = True

    def stop(self) -> None:
        with self._lock:
            if self._started:
                self._runner.stop()
                self._started = False

    def submit_pipeline_run(self, pipeline_callable, *, priority: JobPriority = JobPriority.NORMAL) -> str:
        job_id = str(uuid.uuid4())
        worker_id = None
        try:
            worker_id = self._worker_registry.get_local_worker().id
        except Exception:
            worker_id = None
        job = Job(
            job_id=job_id,
            priority=priority,
            payload=pipeline_callable,
            worker_id=worker_id,
        )
        self._queue.submit(job)
        self.start()
        return job_id

    def cancel_job(self, job_id: str) -> None:
        # Mark as cancelled so runner will skip it if not already running.
        job = next((j for j in self._queue.list_jobs() if j.job_id == job_id), None)
        if job and job.status == JobStatus.QUEUED:
            job.mark_status(JobStatus.CANCELLED)

    def get_job_status(self, job_id: str) -> JobStatus | None:
        job = next((j for j in self._queue.list_jobs() if j.job_id == job_id), None)
        return job.status if job else None

    def set_status_callback(self, key: str, callback: Callable[[Job, JobStatus], None]) -> None:
        self._callbacks[key] = callback

    def clear_status_callback(self, key: str) -> None:
        self._callbacks.pop(key, None)

    def _on_status(self, job: Job, status: JobStatus) -> None:
        for cb in list(self._callbacks.values()):
            try:
                cb(job, status)
            except Exception:
                pass

    def get_history_store(self) -> JobHistoryStore:
        return self._history_store

    def get_queue(self) -> JobQueue:
        return self._queue

    def get_worker_registry(self) -> WorkerRegistry:
        return self._worker_registry

    def get_runner(self) -> SingleNodeJobRunner:
        return self._runner

    def _default_history_store(self) -> JobHistoryStore:
        path = Path(get_job_history_path())
        return JSONLJobHistoryStore(path)
