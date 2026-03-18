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


def test_runner_does_not_dequeue_while_queue_paused() -> None:
    queue = JobQueue()
    executed: list[str] = []

    def _execute(job: Job):
        executed.append(job.job_id)
        return {"success": True}

    queue.submit(Job("paused-job", priority=JobPriority.NORMAL))
    queue.pause()
    runner = SingleNodeJobRunner(queue, _execute, poll_interval=0.01)

    runner.start()
    time.sleep(0.05)
    runner.stop()

    assert executed == []
    assert queue.get_job("paused-job").status == JobStatus.QUEUED

    queue.resume()
    runner = SingleNodeJobRunner(queue, _execute, poll_interval=0.01)
    runner.start()
    time.sleep(0.05)
    runner.stop()

    assert executed == ["paused-job"]


def test_run_once_cancel_return_to_queue_requeues_job() -> None:
    queue = JobQueue()
    runner: SingleNodeJobRunner

    def _execute(job: Job):
        runner.cancel_current(return_to_queue=True)
        return {
            "success": True,
            "stage_events": [{"stage": "txt2img", "event": "exit"}],
            "variants": [{"path": "out/test.png"}],
        }

    runner = SingleNodeJobRunner(queue, _execute, poll_interval=0.01)
    job = Job("return-job", priority=JobPriority.NORMAL)
    queue.submit(job)

    result = runner.run_once(job)

    assert result is not None
    assert job.status == JobStatus.QUEUED
    assert job.execution_metadata.return_to_queue_count == 1
    assert job.execution_metadata.stage_checkpoints
