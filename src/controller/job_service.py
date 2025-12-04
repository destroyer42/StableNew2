"""JobService bridges JobQueue, runner, and history for higher-level orchestration."""

from __future__ import annotations

import logging

from typing import Any, Callable, Literal

from src.queue.job_model import Job, JobStatus
from src.gui.pipeline_panel_v2 import format_queue_job_summary
from src.queue.job_queue import JobQueue
from src.queue.single_node_runner import SingleNodeJobRunner
from src.queue.job_history_store import JobHistoryStore

QueueStatus = Literal["idle", "running", "paused"]


class JobService:
    EVENT_QUEUE_UPDATED = "queue_updated"
    EVENT_JOB_STARTED = "job_started"
    EVENT_JOB_FINISHED = "job_finished"
    EVENT_JOB_FAILED = "job_failed"
    EVENT_QUEUE_EMPTY = "queue_empty"
    EVENT_QUEUE_STATUS = "queue_status"

    def __init__(
        self,
        job_queue: JobQueue,
        runner: SingleNodeJobRunner,
        history_store: JobHistoryStore | None = None,
    ) -> None:
        self.job_queue = job_queue
        self.runner = runner
        self.history_store = history_store
        self._listeners: dict[str, list[Callable[..., None]]] = {}
        self._queue_status: QueueStatus = "idle"
        self.runner._on_status_change = self._handle_runner_status

    def register_callback(self, event: str, callback: Callable[..., None]) -> None:
        self._listeners.setdefault(event, []).append(callback)

    def enqueue(self, job: Job) -> None:
        self.job_queue.submit(job)
        self._emit_queue_updated()

    def run_now(self, job: Job) -> None:
        self.enqueue(job)
        try:
            self.run_next_now()
        except Exception:
            pass
        if not self.runner.is_running():
            self.runner.start()

    def submit_job_with_run_mode(self, job: Job) -> None:
        """Submit a job respecting its configured run_mode."""
        mode = (job.run_mode or "queue").lower()
        logging.info("Submitting job %s with run_mode=%s", job.job_id, mode)
        if mode == "direct":
            self.submit_direct(job)
        else:
            self.submit_queued(job)

    def submit_direct(self, job: Job) -> dict | None:
        """Execute a job synchronously (bypasses queue for 'Run Now' semantics).
        
        PR-106: Explicit API for direct execution path.
        """
        logging.info("Direct execution of job %s", job.job_id)
        self.job_queue.submit(job)
        self._emit_queue_updated()
        try:
            result = self.runner.run_once(job)
            return result
        except Exception:
            raise

    def submit_queued(self, job: Job) -> None:
        """Submit a job to the queue for background execution.
        
        PR-106: Explicit API for queued execution path.
        """
        logging.info("Queuing job %s for background execution", job.job_id)
        self.enqueue(job)
        if not self.runner.is_running():
            self.runner.start()

    def pause(self) -> None:
        self.runner.stop()
        self._set_queue_status("paused")

    def resume(self) -> None:
        self.runner.start()
        self._set_queue_status("running")

    def cancel_current(self) -> None:
        current = getattr(self.runner, "current_job", None)
        if current:
            self.job_queue.mark_cancelled(current.job_id)
        self.runner.cancel_current()
        self._set_queue_status("idle")

    def list_queue(self) -> list[Job]:
        return self.job_queue.list_jobs()

    def run_next_now(self) -> None:
        """Synchronously run the next queued job via the runner."""
        job = self.job_queue.get_next_job()
        if job is None:
            return
        self._set_queue_status("running")
        try:
            self.runner.run_once(job)
        finally:
            if not any(j.status == JobStatus.QUEUED for j in self.job_queue.list_jobs()):
                self._set_queue_status("idle")

    def _handle_runner_status(self, job: Job, status: JobStatus) -> None:
        if status == JobStatus.RUNNING:
            self._emit(self.EVENT_JOB_STARTED, job)
        elif status == JobStatus.COMPLETED:
            self._emit(self.EVENT_JOB_FINISHED, job)
        elif status == JobStatus.CANCELLED:
            self._emit(self.EVENT_JOB_FAILED, job)
        elif status == JobStatus.FAILED:
            self._emit(self.EVENT_JOB_FAILED, job)
        self._emit_queue_updated()
        if not any(j.status == JobStatus.QUEUED for j in self.job_queue.list_jobs()):
            self._emit(self.EVENT_QUEUE_EMPTY)

    def _emit_queue_updated(self) -> None:
        jobs = self.job_queue.list_jobs()
        summaries = [format_queue_job_summary(job) for job in jobs]
        self._emit(self.EVENT_QUEUE_UPDATED, summaries)

    def _set_queue_status(self, status: QueueStatus) -> None:
        if self._queue_status != status:
            self._queue_status = status
            self._emit(self.EVENT_QUEUE_STATUS, status)

    def _emit(self, event: str, *args: Any) -> None:
        for callback in self._listeners.get(event, []):
            try:
                callback(*args)
            except Exception:
                continue
