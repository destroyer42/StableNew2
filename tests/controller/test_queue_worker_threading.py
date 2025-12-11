from __future__ import annotations

import pytest

from src.controller.job_service import JobService
from src.queue.job_model import Job, JobPriority
from src.queue.job_queue import JobQueue


class StubRunner:
    def __init__(self) -> None:
        self.start_calls = 0
        self.stop_calls = 0
        self._running = False

    def start(self) -> None:
        self.start_calls += 1
        self._running = True

    def stop(self) -> None:
        self.stop_calls += 1
        self._running = False

    def is_running(self) -> bool:
        return self._running

    def run_once(self, job: Job) -> dict | None:
        return {"job_id": job.job_id}

    def cancel_current(self) -> None:
        pass


class FailingRunner(StubRunner):
    def start(self) -> None:
        super().start()
        raise RuntimeError("worker start failed")


def test_submit_queue_jobs_starts_worker_once() -> None:
    queue = JobQueue()
    runner = StubRunner()
    service = JobService(queue, runner=runner)

    job_one = Job(job_id="job-1", priority=JobPriority.NORMAL)
    job_two = Job(job_id="job-2", priority=JobPriority.NORMAL)

    service.submit_queued(job_one)
    service.submit_queued(job_two)

    assert runner.start_calls == 1
    assert len(queue.list_jobs()) == 2


def test_queue_worker_start_failure_propagates_error() -> None:
    queue = JobQueue()
    runner = FailingRunner()
    service = JobService(queue, runner=runner)
    job = Job(job_id="job-fail", priority=JobPriority.NORMAL)

    with pytest.raises(RuntimeError):
        service.submit_queued(job)

    assert runner.start_calls == 1
    assert len(queue.list_jobs()) == 1
