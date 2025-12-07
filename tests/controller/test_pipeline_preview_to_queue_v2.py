from __future__ import annotations

from typing import Any

from src.controller.job_service import JobService
from src.controller.pipeline_controller import PipelineController
from src.pipeline.job_models_v2 import NormalizedJobRecord
from src.queue.job_model import Job


class DummyJobService(JobService):  # type: ignore[misc]
    def __init__(self) -> None:
        self.submitted: list[Job] = []

    def submit_job_with_run_mode(self, job: Job) -> None:
        self.submitted.append(job)


class DummyPipelineController(PipelineController):
    def __init__(self) -> None:
        # Avoid calling PipelineController.__init__ by bypassing initializer
        pass


def test_submit_preview_jobs_to_queue_submits_jobs():
    controller = object.__new__(DummyPipelineController)
    controller._job_service = DummyJobService()

    record = NormalizedJobRecord(
        job_id="job-1",
        config={"model": "md", "prompt": "p", "seed": 42},
        path_output_dir="out",
        filename_template="{seed}",
        seed=42,
    )
    controller.get_preview_jobs = lambda: [record]  # type: ignore[assignment]
    controller._to_queue_job = lambda rec, **kwargs: Job(
        job_id=rec.job_id,
        pipeline_config=None,
        run_mode=kwargs["run_mode"],
        source=kwargs["source"],
        prompt_source=kwargs["prompt_source"],
        prompt_pack_id=kwargs.get("prompt_pack_id"),
        config_snapshot=rec.to_queue_snapshot(),
    )
    controller._run_job = lambda job: {}  # type: ignore[assignment]

    submitted = controller.submit_preview_jobs_to_queue()

    assert submitted == 1
    assert len(controller._job_service.submitted) == 1
    job = controller._job_service.submitted[0]
    assert job.run_mode == "queue"
    assert job.source == "gui"


def test_submit_preview_jobs_to_queue_returns_zero_when_no_jobs():
    controller = object.__new__(DummyPipelineController)
    controller._job_service = DummyJobService()
    controller.get_preview_jobs = lambda: []

    submitted = controller.submit_preview_jobs_to_queue()

    assert submitted == 0
    assert not controller._job_service.submitted
