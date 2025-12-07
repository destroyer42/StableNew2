from __future__ import annotations

from typing import Callable, List

import pytest

from src.controller.job_service import JobService, QueueStatus
from src.queue.job_model import Job, JobPriority, JobStatus


class FakeQueue:
    def __init__(self) -> None:
        self.jobs: list[Job] = []
        self.running = []
        self._status_callbacks: list[Callable[[Job, JobStatus], None]] = []

    def submit(self, job: Job) -> None:
        self.jobs.append(job)

    def list_jobs(self, status_filter: JobStatus | None = None) -> list[Job]:
        if status_filter is None:
            return list(self.jobs)
        return [job for job in self.jobs if job.status == status_filter]

    def mark_running(self, job_id: str) -> None:
        self._update_status(job_id, JobStatus.RUNNING)

    def mark_completed(self, job_id: str, result: dict | None = None) -> None:
        self._update_status(job_id, JobStatus.COMPLETED)

    def mark_failed(self, job_id: str, error_message: str) -> None:
        self._update_status(job_id, JobStatus.FAILED)

    def mark_cancelled(self, job_id: str, reason: str | None = None) -> None:
        self._update_status(job_id, JobStatus.CANCELLED)

    def _update_status(self, job_id: str, status: JobStatus) -> None:
        updated: Job | None = None
        for job in self.jobs:
            if job.job_id == job_id:
                job.status = status
                updated = job
                break
        if updated:
            for callback in self._status_callbacks:
                callback(updated, status)

    def register_status_callback(
        self, callback: Callable[[Job, JobStatus], None]
    ) -> None:
        self._status_callbacks.append(callback)


class FakeRunner:
    def __init__(self) -> None:
        self.started = False
        self.stopped = False
        self.cancelled = False
        self._callback: Callable[[Job, JobStatus], None] | None = None
        self.current_job: Job | None = None

    def start(self) -> None:
        self.started = True

    def stop(self) -> None:
        self.stopped = True

    def cancel_current(self) -> None:
        self.cancelled = True
        if self.current_job and self._callback:
            self._callback(self.current_job, JobStatus.CANCELLED)

    def is_running(self) -> bool:
        return self.started and not self.stopped

    @property
    def _on_status_change(self) -> Callable[[Job, JobStatus], None] | None:
        return self._callback

    @_on_status_change.setter
    def _on_status_change(self, value: Callable[[Job, JobStatus], None] | None) -> None:
        self._callback = value

    def trigger_status(self, job: Job, status: JobStatus) -> None:
        if self._callback:
            self._callback(job, status)


class FakeHistory:
    pass


def make_job(job_id: str = "job1") -> Job:
    return Job(job_id=job_id, pipeline_config=None, priority=JobPriority.NORMAL)


@pytest.fixture
def service() -> JobService:
    queue = FakeQueue()
    runner = FakeRunner()
    history = FakeHistory()
    return JobService(queue, runner, history)


def test_enqueue_emits_queue_update(service: JobService) -> None:
    received: List[list[str]] = []

    def on_queue_update(items: list[str]) -> None:
        received.append(items)

    service.register_callback(JobService.EVENT_QUEUE_UPDATED, on_queue_update)
    service.enqueue(make_job())
    assert received
    assert received[-1][0].endswith("job1")


def test_run_now_starts_runner(service: JobService) -> None:
    runner = service.runner
    job = make_job("run-now")
    service.run_now(job)
    assert runner.started
    assert service.list_queue()


def test_pause_resume_toggle_status(service: JobService) -> None:
    statuses: List[QueueStatus] = []

    service.register_callback(JobService.EVENT_QUEUE_STATUS, statuses.append)
    service.pause()
    service.resume()
    assert ["paused", "running"] == statuses


def test_cancel_current_triggers_failed_event(service: JobService) -> None:
    failures: List[Job] = []

    def on_failed(job: Job) -> None:
        failures.append(job)

    service.register_callback(JobService.EVENT_JOB_FAILED, on_failed)
    job = make_job("cancel")
    service.enqueue(job)
    service.runner.current_job = job
    service.cancel_current()
    assert failures


def test_job_service_emits_started_and_finished(service: JobService) -> None:
    events: list[tuple[str, str]] = []

    service.register_callback(
        JobService.EVENT_JOB_STARTED,
        lambda job: events.append(("started", job.job_id)),
    )
    service.register_callback(
        JobService.EVENT_JOB_FINISHED,
        lambda job: events.append(("finished", job.job_id)),
    )

    job = make_job("start-finish")
    service.enqueue(job)
    service.queue.mark_running(job.job_id)
    service.queue.mark_completed(job.job_id)

    assert events == [("started", "start-finish"), ("finished", "start-finish")]


def test_job_service_emits_failed_event_on_queue_failure(service: JobService) -> None:
    failures: List[str] = []

    service.register_callback(
        JobService.EVENT_JOB_FAILED,
        lambda job: failures.append(job.job_id),
    )

    job = make_job("queue-fail")
    service.enqueue(job)
    service.queue.mark_running(job.job_id)
    service.queue.mark_failed(job.job_id, "uh-oh")

    assert failures == ["queue-fail"]
