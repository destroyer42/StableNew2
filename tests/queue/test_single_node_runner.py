from __future__ import annotations

from types import SimpleNamespace

import pytest

from src.pipeline.pipeline_runner import PipelineConfig
from src.queue.job_model import Job, JobStatus
from src.queue.job_queue import JobQueue
from src.queue.single_node_runner import SingleNodeJobRunner


def _pipeline_config() -> PipelineConfig:
    return PipelineConfig(
        prompt="prompt",
        model="sd_xl_base_1.0",
        sampler="Euler",
        width=512,
        height=512,
        steps=20,
        cfg_scale=7.5,
    )


class DummyResultRunner:
    def __init__(self, *, should_raise: bool = False):
        self.should_raise = should_raise
        self.calls: list[Job] = []

    def __call__(self, job: Job) -> dict[str, str]:
        self.calls.append(job)
        if self.should_raise:
            raise RuntimeError("Run failed")
        return {"job": job.job_id}


def test_run_once_marks_completed_result():
    queue = JobQueue()
    job = Job(job_id="run-1")
    queue.submit(job)
    runner = SingleNodeJobRunner(queue, run_callable=DummyResultRunner())

    result = runner.run_once(job)
    assert result == {"job": "run-1"}
    assert job.status == JobStatus.COMPLETED


def test_run_once_handles_error():
    queue = JobQueue()
    job = Job(job_id="run-error")
    queue.submit(job)
    runner = SingleNodeJobRunner(queue, run_callable=DummyResultRunner(should_raise=True))

    with pytest.raises(RuntimeError):
        runner.run_once(job)
    assert job.status == JobStatus.FAILED


def test_run_once_publishes_cancelled():
    queue = JobQueue()
    job = Job(job_id="cancelled")
    queue.submit(job)
    class CancelingRunner:
        def __init__(self):
            self.runner: SingleNodeJobRunner | None = None

        def __call__(self, job_arg: Job) -> dict[str, str]:
            if self.runner:
                self.runner.cancel_current()
            return {"job": job_arg.job_id}

    canceler = CancelingRunner()
    runner = SingleNodeJobRunner(queue, run_callable=canceler)
    canceler.runner = runner
    runner.run_once(job)
    assert job.status in {JobStatus.COMPLETED, JobStatus.CANCELLED}
