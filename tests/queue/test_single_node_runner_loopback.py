from __future__ import annotations

import time

from src.queue.job_model import Job, JobStatus
from src.queue.job_queue import JobQueue
from src.queue.single_node_runner import SingleNodeJobRunner
from src.pipeline.pipeline_runner import PipelineConfig


def _cfg():
    return PipelineConfig(prompt="p", model="m", sampler="Euler", width=512, height=512, steps=10, cfg_scale=7.0)


def test_single_node_runner_executes_jobs_and_updates_status():
    queue = JobQueue()
    executed = []

    def _run(job):
        executed.append(job.job_id)
        return {"job": job.job_id, "status": "done"}

    runner = SingleNodeJobRunner(queue, _run, poll_interval=0.01)
    queue.submit(Job("j1", _cfg()))
    queue.submit(Job("j2", _cfg()))

    runner.start()
    time.sleep(0.1)
    runner.stop()

    jobs = queue.list_jobs()
    assert all(job.status in {JobStatus.COMPLETED, JobStatus.FAILED, JobStatus.RUNNING} for job in jobs)
    assert set(executed) == {"j1", "j2"}
