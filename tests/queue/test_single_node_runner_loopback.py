"""Single node runner loopback tests for NJR-backed jobs."""

from __future__ import annotations

import time

from src.queue.job_model import JobStatus
from src.queue.job_queue import JobQueue
from src.queue.single_node_runner import SingleNodeJobRunner
from tests.helpers.njr_factory import make_queue_job


def test_single_node_runner_executes_jobs_and_updates_status():
    queue = JobQueue()
    executed = []

    def _run(job):
        executed.append(job.job_id)
        return {"job": job.job_id, "status": "done"}

    runner = SingleNodeJobRunner(queue, _run, poll_interval=0.01)
    job_one = make_queue_job("j1")
    job_two = make_queue_job("j2")
    queue.submit(job_one)
    queue.submit(job_two)

    runner.start()
    deadline = time.time() + 1.0
    while time.time() < deadline:
        jobs = queue.list_jobs()
        if set(executed) == {"j1", "j2"} and all(
            job.status in {JobStatus.COMPLETED, JobStatus.FAILED, JobStatus.RUNNING}
            for job in jobs
        ):
            break
        time.sleep(0.01)
    runner.stop()

    jobs = queue.list_jobs()
    assert all(
        job.status in {JobStatus.COMPLETED, JobStatus.FAILED, JobStatus.RUNNING} for job in jobs
    )
    assert set(executed) == {"j1", "j2"}
