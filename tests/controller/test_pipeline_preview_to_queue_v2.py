from __future__ import annotations

from unittest.mock import Mock

from src.controller.job_service import JobService
from src.controller.pipeline_controller import PipelineController
from src.pipeline.job_models_v2 import NormalizedJobRecord
from tests.helpers.job_helpers import make_test_njr


class DummyJobService(JobService):  # type: ignore[misc]
    def __init__(self) -> None:
        self.submitted: list[NormalizedJobRecord] = []

    def submit_njrs(self, records, policy=None):
        self.submitted.extend(records)
        return [record.job_id for record in records]


class DummyPipelineController(PipelineController):
    def __init__(self) -> None:
        pass


def _controller() -> DummyPipelineController:
    controller = object.__new__(DummyPipelineController)
    controller._job_service = DummyJobService()
    controller._last_run_config = None
    controller._app_controller = None
    controller.can_enqueue_learning_jobs = lambda _count: (True, "")
    controller._is_queue_submission_blocked = lambda: False
    controller._sort_jobs_by_model = lambda rows: rows
    return controller


def test_submit_preview_jobs_to_queue_submits_njrs() -> None:
    controller = _controller()
    record = make_test_njr(job_id="job-1", prompt_source="manual", prompt_pack_id="")
    controller.get_preview_jobs = lambda: [record]  # type: ignore[assignment]

    submitted = controller.submit_preview_jobs_to_queue()

    assert submitted == 1
    assert controller._job_service.submitted == [record]


def test_submit_preview_jobs_to_queue_returns_zero_when_no_jobs() -> None:
    controller = _controller()
    controller.get_preview_jobs = lambda: []

    submitted = controller.submit_preview_jobs_to_queue()

    assert submitted == 0
    assert not controller._job_service.submitted


def test_enqueue_draft_jobs_reuses_cached_preview_jobs() -> None:
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

    controller = _controller()
    controller._app_state = DummyAppState()
    record = make_test_njr(job_id="job-cached", prompt_source="manual", prompt_pack_id="")
    controller._app_state.preview_jobs = [record]
    controller.submit_preview_jobs_to_queue = Mock(return_value=1)
    controller.get_preview_jobs = lambda: (_ for _ in ()).throw(AssertionError("should not rebuild preview"))

    submitted = controller.enqueue_draft_jobs(run_config={"run_mode": "queue"})

    assert submitted == 1
    assert controller._app_state.cleared == 1
    assert controller._app_state.preview_updates[-1] == []
