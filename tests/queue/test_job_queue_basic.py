from __future__ import annotations

from src.queue.job_model import Job, JobPriority, JobStatus
from src.queue.job_queue import JobQueue
from src.pipeline.pipeline_runner import PipelineConfig


def _cfg():
    return PipelineConfig(prompt="p", model="m", sampler="Euler", width=512, height=512, steps=10, cfg_scale=7.0)


def test_job_queue_respects_priority_and_fifo():
    queue = JobQueue()
    queue.submit(Job("low-1", _cfg(), priority=JobPriority.LOW))
    queue.submit(Job("high-1", _cfg(), priority=JobPriority.HIGH))
    queue.submit(Job("norm-1", _cfg(), priority=JobPriority.NORMAL))
    queue.submit(Job("high-2", _cfg(), priority=JobPriority.HIGH))

    order = [queue.get_next_job().job_id for _ in range(4)]
    assert order[:2] == ["high-1", "high-2"]
    assert order[2:] == ["norm-1", "low-1"]


def test_job_queue_status_transitions():
    queue = JobQueue()
    job = Job("j1", _cfg())
    queue.submit(job)
    next_job = queue.get_next_job()
    assert next_job.job_id == "j1"
    queue.mark_running("j1")
    assert job.status == JobStatus.RUNNING
    queue.mark_completed("j1", result={"ok": True})
    assert job.status == JobStatus.COMPLETED
    assert job.result == {"ok": True}
    queue.mark_failed("j1", "error")  # even completed, should update status
    assert job.status == JobStatus.FAILED
    assert job.error_message == "error"
