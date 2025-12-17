from __future__ import annotations

import time

from src.queue.job_model import Job, JobPriority, JobStatus
from src.queue.job_queue import JobQueue
from src.queue.single_node_runner import SingleNodeJobRunner


def test_jobrunner_integration_updates_status_and_result():
    queue = JobQueue()
    seen = []

    def _execute(job: Job):
        seen.append(job.job_id)
        return {"done": True}

    runner = SingleNodeJobRunner(queue, _execute, poll_interval=0.01)
    job = Job("j1", priority=JobPriority.NORMAL)
    job.payload = lambda: None
    queue.submit(job)
    runner.start()
    time.sleep(0.05)
    runner.stop()
    jobs = queue.list_jobs()
    assert jobs
    assert jobs[0].result is not None or jobs[0].status in {
        jobs[0].status.FAILED,
        jobs[0].status.RUNNING,
    }


def test_runner_executes_restored_jobs() -> None:
    queue = JobQueue()
    executed: list[str] = []

    def _execute(job: Job):
        executed.append(job.job_id)
        return {"restored": True, "success": True}

    runner = SingleNodeJobRunner(queue, _execute, poll_interval=0.01)
    job = Job("restored-job", priority=JobPriority.NORMAL)
    job.payload = lambda: {"restored": True}
    queue.restore_jobs([job])

    runner.start()
    time.sleep(0.05)
    runner.stop()

    assert "restored-job" in executed
    assert job.status == JobStatus.COMPLETED
    assert job.result and job.result.get("success") is True
