"""Single node runner loopback tests for NJR-backed jobs."""

from __future__ import annotations

import time

from src.pipeline.job_models_v2 import NormalizedJobRecord
from src.queue.job_model import Job, JobStatus
from src.queue.job_queue import JobQueue
from src.queue.single_node_runner import SingleNodeJobRunner


def _record(job_id: str) -> NormalizedJobRecord:
    return NormalizedJobRecord(
        job_id=job_id,
        config={"prompt": "p", "model": "m"},
        path_output_dir="output",
        filename_template="{seed}",
        seed=1,
        positive_prompt="p",
        base_model="m",
    )


def test_single_node_runner_executes_jobs_and_updates_status():
    queue = JobQueue()
    executed = []

    def _run(job):
        executed.append(job.job_id)
        return {"job": job.job_id, "status": "done"}

    runner = SingleNodeJobRunner(queue, _run, poll_interval=0.01)
    job_one = Job(job_id="j1")
    job_one._normalized_record = _record("j1")
    job_one.snapshot = {"normalized_job": job_one._normalized_record.to_queue_snapshot()}
    job_two = Job(job_id="j2")
    job_two._normalized_record = _record("j2")
    job_two.snapshot = {"normalized_job": job_two._normalized_record.to_queue_snapshot()}
    queue.submit(job_one)
    queue.submit(job_two)

    runner.start()
    time.sleep(0.1)
    runner.stop()

    jobs = queue.list_jobs()
    assert all(
        job.status in {JobStatus.COMPLETED, JobStatus.FAILED, JobStatus.RUNNING} for job in jobs
    )
    assert set(executed) == {"j1", "j2"}
