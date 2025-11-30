"""JobService bridges JobQueue, runner, and history for higher-level orchestration."""

from __future__ import annotations

from typing import Any, Callable, Literal

from src.queue.job_model import Job, JobStatus
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
        if not self.runner.is_running():
            self.runner.start()
        self._set_queue_status("running")

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
        summaries = [job.summary() for job in self.job_queue.list_jobs()]
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
