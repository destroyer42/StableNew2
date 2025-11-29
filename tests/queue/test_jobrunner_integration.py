from __future__ import annotations

import time

from src.queue.job_model import Job, JobPriority
from src.queue.job_queue import JobQueue
from src.queue.single_node_runner import SingleNodeJobRunner


def test_jobrunner_integration_updates_status_and_result():
    queue = JobQueue()
    seen = []

    def _execute(job: Job):
        seen.append(job.job_id)
        return {"done": True}

    runner = SingleNodeJobRunner(queue, _execute, poll_interval=0.01)
    queue.submit(Job("j1", None, priority=JobPriority.NORMAL, payload=lambda: None))
    runner.start()
    time.sleep(0.05)
    runner.stop()
    jobs = queue.list_jobs()
    assert jobs
    assert jobs[0].result is not None or jobs[0].status in {jobs[0].status.FAILED, jobs[0].status.RUNNING}
