from __future__ import annotations

from collections.abc import Callable
from dataclasses import asdict

import pytest

from src.controller.job_service import JobService, QueueStatus
from src.queue.job_model import Job, JobPriority, JobStatus, StageCheckpoint


class FakeQueue:
    def __init__(self) -> None:
        self.jobs: list[Job] = []
        self.running = []
        self._status_callbacks: list[Callable[[Job, JobStatus], None]] = []
        self.paused = False

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

    def pause(self) -> None:
        self.paused = True

    def resume(self) -> None:
        self.paused = False

    def cancel_running_job(self, *, return_to_queue: bool = False) -> Job | None:
        running = next((job for job in self.jobs if job.status == JobStatus.RUNNING), None)
        if running is None:
            return None
        if return_to_queue:
            running.status = JobStatus.QUEUED
            return running
        self._update_status(running.job_id, JobStatus.CANCELLED)
        return running

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

    def register_status_callback(self, callback: Callable[[Job, JobStatus], None]) -> None:
        self._status_callbacks.append(callback)

    def get_job(self, job_id: str) -> Job | None:
        return next((job for job in self.jobs if job.job_id == job_id), None)


class FakeRunner:
    def __init__(self) -> None:
        self.started = False
        self.stopped = False
        self.cancelled = False
        self.cancel_return_to_queue = False
        self._callback: Callable[[Job, JobStatus], None] | None = None
        self.current_job: Job | None = None

    def start(self) -> None:
        self.started = True

    def stop(self) -> None:
        self.stopped = True

    def cancel_current(self, *, return_to_queue: bool = False) -> None:
        self.cancelled = True
        self.cancel_return_to_queue = bool(return_to_queue)
        if self.current_job and self._callback:
            self._callback(
                self.current_job,
                JobStatus.QUEUED if self.cancel_return_to_queue else JobStatus.CANCELLED,
            )

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
    return Job(job_id=job_id, priority=JobPriority.NORMAL)


@pytest.fixture
def service() -> JobService:
    queue = FakeQueue()
    runner = FakeRunner()
    history = FakeHistory()
    return JobService(queue, runner, history)


def test_enqueue_emits_queue_update(service: JobService) -> None:
    received: list[list[str]] = []

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
    statuses: list[QueueStatus] = []

    service.register_callback(JobService.EVENT_QUEUE_STATUS, statuses.append)
    service.pause()
    service.resume()
    assert ["paused", "running"] == statuses
    assert service.queue.paused is False


def test_cancel_current_triggers_failed_event(service: JobService) -> None:
    failures: list[Job] = []

    def on_failed(job: Job) -> None:
        failures.append(job)

    service.register_callback(JobService.EVENT_JOB_FAILED, on_failed)
    job = make_job("cancel")
    service.enqueue(job)
    service.runner.current_job = job
    service.cancel_current()
    assert failures


def test_cancel_current_return_to_queue_uses_runner_contract(service: JobService) -> None:
    job = make_job("return")
    service.enqueue(job)
    service.queue.mark_running(job.job_id)
    service.runner.current_job = job

    returned = service.cancel_current(return_to_queue=True)

    assert returned is job
    assert service.runner.cancelled is True
    assert service.runner.cancel_return_to_queue is True


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
    failures: list[str] = []

    service.register_callback(
        JobService.EVENT_JOB_FAILED,
        lambda job: failures.append(job.job_id),
    )

    job = make_job("queue-fail")
    service.enqueue(job)
    service.queue.mark_running(job.job_id)
    service.queue.mark_failed(job.job_id, "uh-oh")

    assert failures == ["queue-fail"]


def test_get_diagnostics_snapshot_includes_queue_and_checkpoint_state(service: JobService) -> None:
    job = make_job("diag")
    job.status = JobStatus.RUNNING
    job.result = {
        "success": False,
        "error": "boom",
        "metadata": {"duration_ms": 123, "recovery_classification": "pre_stage_health_failed"},
        "stage_events": [{"stage": "txt2img"}],
        "variants": [{"path": "output/test.png"}],
    }
    job.execution_metadata.stage_checkpoints.append(
        StageCheckpoint(stage_name="txt2img", output_paths=["output/test.png"])
    )
    job.execution_metadata.last_control_action = "return_to_queue"
    job.execution_metadata.return_to_queue_count = 2
    service.queue.jobs.append(job)
    service.runner.current_job = job
    service.runner.started = True

    snapshot = service.get_diagnostics_snapshot()

    assert snapshot["queue"]["current_job_id"] == "diag"
    assert snapshot["queue"]["runner_running"] is True
    job_entry = snapshot["jobs"][0]
    assert job_entry["stage_checkpoints"] == [asdict(job.execution_metadata.stage_checkpoints[0])]
    assert job_entry["last_control_action"] == "return_to_queue"
    assert job_entry["return_to_queue_count"] == 2
    assert job_entry["result_summary"]["duration_ms"] == 123
    assert job_entry["result_summary"]["output_count"] == 1
