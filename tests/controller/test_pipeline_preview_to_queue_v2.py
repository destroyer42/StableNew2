from __future__ import annotations

from types import SimpleNamespace

from src.controller.job_service import JobService
from src.controller.pipeline_controller import PipelineController
from src.pipeline.job_models_v2 import NormalizedJobRecord
from src.queue.job_model import Job
from tests.helpers.job_helpers import make_test_njr


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


def test_enqueue_draft_jobs_reuses_cached_preview_jobs():
    class DummyAppState:
        def __init__(self) -> None:
            self.preview_jobs: list[NormalizedJobRecord] = []
            self.cleared = 0
            self.preview_updates: list[list[NormalizedJobRecord]] = []

        def clear_job_draft(self) -> None:
            self.cleared += 1

        def set_preview_jobs(self, jobs):
            self.preview_updates.append(list(jobs))
            self.preview_jobs = list(jobs)

    controller = object.__new__(DummyPipelineController)
    controller._app_state = DummyAppState()
    record = NormalizedJobRecord(
        job_id="job-cached",
        config={"model": "md", "prompt": "p", "seed": 42},
        path_output_dir="out",
        filename_template="{seed}",
        seed=42,
    )
    controller._app_state.preview_jobs = [record]
    controller.submit_preview_jobs_to_queue = lambda **kwargs: 1
    controller.get_preview_jobs = lambda: (_ for _ in ()).throw(AssertionError("should not rebuild preview"))

    submitted = controller.enqueue_draft_jobs(run_config={"run_mode": "queue"})

    assert submitted == 1
    assert controller._app_state.cleared == 1
    assert controller._app_state.preview_updates[-1] == []


def test_submit_preview_jobs_to_queue_tracks_remaining_non_queueable_rows() -> None:
    controller = object.__new__(DummyPipelineController)
    controller._job_service = DummyJobService()
    controller._job_lifecycle_logger = None
    controller._app_state = SimpleNamespace(job_draft=SimpleNamespace(summary=SimpleNamespace(part_count=0)))
    controller._run_job = lambda job: {}  # type: ignore[assignment]
    controller._to_queue_job = lambda rec, **kwargs: Job(
        job_id=rec.job_id,
        run_mode=kwargs["run_mode"],
        source=kwargs["source"],
        prompt_source=kwargs["prompt_source"],
        prompt_pack_id=kwargs.get("prompt_pack_id"),
        config_snapshot=rec.to_queue_snapshot(),
    )

    submitted = controller.submit_preview_jobs_to_queue(
        records=[
            make_test_njr(job_id="job-1", prompt_source="pack", prompt_pack_id="pack-a"),
            make_test_njr(job_id="job-2", prompt_source="pack", prompt_pack_id=""),
        ]
    )

    result = controller.get_last_preview_queue_submission_result()

    assert submitted == 1
    assert result.submitted_record_ids == ("job-1",)
    assert result.remaining_record_ids == ("job-2",)
    assert result.non_queueable_record_ids == ("job-2",)
