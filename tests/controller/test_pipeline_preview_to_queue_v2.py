from __future__ import annotations

from types import SimpleNamespace

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


def test_submit_preview_jobs_to_queue_rebuilds_stale_cached_records_from_pack_draft():
    controller = object.__new__(DummyPipelineController)
    controller._job_service = DummyJobService()
    preview_updates: list[list[NormalizedJobRecord]] = []
    controller._app_state = SimpleNamespace(
        job_draft=SimpleNamespace(
            packs=[SimpleNamespace(pack_id="pack-1", pack_name="Pack 1")]
        ),
        set_preview_jobs=lambda jobs: preview_updates.append(list(jobs)),
    )

    stale_record = NormalizedJobRecord(
        job_id="job-stale",
        config={"model": "md", "prompt": "p"},
        path_output_dir="out",
        filename_template="{seed}",
        prompt_pack_id="",
    )
    rebuilt_record = NormalizedJobRecord(
        job_id="job-pack",
        config={"model": "md", "prompt": "p", "prompt_pack_id": "pack-1"},
        path_output_dir="out",
        filename_template="{seed}",
        prompt_pack_id="pack-1",
        prompt_pack_name="Pack 1",
        positive_prompt="from pack",
    )

    captured: list[NormalizedJobRecord] = []
    controller.get_preview_jobs_for_request = lambda request: [rebuilt_record]  # type: ignore[assignment]
    controller._split_queueable_records = lambda records: (list(records), [])  # type: ignore[assignment]
    controller._submit_normalized_jobs = (  # type: ignore[assignment]
        lambda records, **kwargs: captured.extend(records) or len(records)
    )

    submitted = controller.submit_preview_jobs_to_queue(records=[stale_record])

    assert submitted == 1
    assert captured == [rebuilt_record]
    assert preview_updates[-1] == [rebuilt_record]
