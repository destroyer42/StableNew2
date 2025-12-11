"""Tests for SingleNodeJobRunner visibility and resilience."""

from __future__ import annotations

import logging
import threading
import time

from src.queue.job_model import Job, JobStatus
from src.queue.job_queue import JobQueue
from src.queue.single_node_runner import SingleNodeJobRunner


def _wait_for_status(job_queue: JobQueue, job_id: str, *, status: JobStatus, timeout: float = 2.0) -> Job | None:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        job = job_queue.get_job(job_id)
        if job and job.status == status:
            return job
        time.sleep(0.01)
    return None


def test_worker_processes_jobs_from_queue() -> None:
    """The worker loop dequeues jobs, executes them, and marks them as completed."""
    job_queue = JobQueue()
    executed: list[str] = []

    def run_callable(job: Job) -> dict[str, str]:
        executed.append(job.job_id)
        return {"job_id": job.job_id, "status": "completed"}

    runner = SingleNodeJobRunner(job_queue=job_queue, run_callable=run_callable, poll_interval=0.01)
    runner.start()

    job = Job(job_id="runner-001")
    job_queue.submit(job)

    assert _wait_for_status(job_queue, "runner-001", status=JobStatus.COMPLETED) is not None
    assert executed == ["runner-001"]

    runner.stop()


def test_worker_survives_exceptions_and_processes_following_jobs() -> None:
    """Exceptions in run_callable do not kill the worker loop."""
    job_queue = JobQueue()
    executed: list[str] = []

    def run_callable(job: Job) -> dict[str, str]:
        if job.job_id == "runner-fail":
            raise RuntimeError("fail intentionally")
        executed.append(job.job_id)
        return {"job_id": job.job_id, "status": "completed"}

    runner = SingleNodeJobRunner(job_queue=job_queue, run_callable=run_callable, poll_interval=0.01)
    runner.start()

    job_queue.submit(Job(job_id="runner-fail"))
    job_queue.submit(Job(job_id="runner-next"))

    failed = _wait_for_status(job_queue, "runner-fail", status=JobStatus.FAILED)
    assert failed is not None and failed.error_message is not None

    assert _wait_for_status(job_queue, "runner-next", status=JobStatus.COMPLETED) is not None
    assert executed == ["runner-next"]

    runner.stop()


def test_worker_warns_long_running_jobs(monkeypatch, caplog) -> None:
    """Jobs that exceed the soft timeout emit a warning."""
    from src.queue import single_node_runner as runner_module

    monkeypatch.setattr(runner_module, "QUEUE_JOB_SOFT_TIMEOUT_SECONDS", 0)
    job_queue = JobQueue()
    caplog.set_level(logging.WARNING)

    def run_callable(job: Job) -> dict[str, str]:
        time.sleep(0.02)
        return {"job_id": job.job_id, "status": "completed"}

    runner = SingleNodeJobRunner(job_queue=job_queue, run_callable=run_callable, poll_interval=0.01)
    runner.start()

    job_queue.submit(Job(job_id="runner-long"))

    assert _wait_for_status(job_queue, "runner-long", status=JobStatus.COMPLETED) is not None
    runner.stop()

    assert any("QUEUE_JOB_WARNING" in record.getMessage() for record in caplog.records)
