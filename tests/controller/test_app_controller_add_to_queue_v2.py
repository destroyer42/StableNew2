from __future__ import annotations

from types import MethodType, SimpleNamespace
from typing import Any

from src.controller.app_controller import AppController


class DummyAddToQueueHandler:
    def __init__(self) -> None:
        self.calls = 0

    def on_add_job_to_queue(self) -> None:
        self.calls += 1


def _build_controller(**kwargs: Any) -> AppController:
    class _AppState:
        def __init__(self) -> None:
            self.job_draft = SimpleNamespace(pack_id="")
            self.pipeline_state = SimpleNamespace(run_mode="")
            self.preview_jobs: list[Any] = list(kwargs.get("preview_jobs") or [])

        def clear_job_draft(self) -> None:
            self.job_draft = SimpleNamespace(pack_id="")

        def set_preview_jobs(self, jobs) -> None:
            self.preview_jobs = list(jobs or [])

    controller = object.__new__(AppController)
    controller.pipeline_controller = kwargs.get("pipeline_controller")
    controller.app_state = _AppState()
    controller._last_run_config = {}
    controller._append_log = lambda text: None
    controller._ui_dispatch = lambda fn: fn()
    controller._queue_submit_in_progress = False
    controller._spawn_tracked_thread = (
        lambda *, target, args=(), kwargs=None, name=None, purpose=None, daemon=False: target(
            *args, **(kwargs or {})
        )
    )
    controller._build_run_config = MethodType(AppController._build_run_config, controller)
    controller._ensure_run_mode_default = MethodType(
        AppController._ensure_run_mode_default, controller
    )
    controller._prepare_queue_run_config = MethodType(
        AppController._prepare_queue_run_config, controller
    )
    controller._submit_preview_jobs_to_queue_async = MethodType(
        AppController._submit_preview_jobs_to_queue_async, controller
    )
    return controller


def test_on_add_job_to_queue_v2_noops_when_pipeline_controller_missing():
    controller = _build_controller(pipeline_controller=None)
    handler = DummyAddToQueueHandler()
    controller.on_add_job_to_queue = handler.on_add_job_to_queue  # type: ignore[attr-defined]

    controller.on_add_job_to_queue_v2()

    assert handler.calls == 0


def test_on_add_job_to_queue_v2_noop_without_handler():
    controller = _build_controller(pipeline_controller=None)

    controller.on_add_job_to_queue_v2()

    assert True


def test_on_add_job_to_queue_v2_prefers_pipeline_controller():
    class DummyPipelineCtrl:
        def __init__(self) -> None:
            self.calls = 0

        def enqueue_draft_jobs(self, **kwargs: Any) -> int:
            self.calls += 1
            return 1

    pipeline_ctrl = DummyPipelineCtrl()
    controller = _build_controller(pipeline_controller=pipeline_ctrl)

    controller.on_add_job_to_queue_v2()

    assert pipeline_ctrl.calls == 1


def test_on_add_job_to_queue_v2_does_not_fall_back_when_preview_jobs_missing():
    class DummyPipelineCtrl:
        def enqueue_draft_jobs(self, **kwargs: Any) -> int:
            return 0

    handler = DummyAddToQueueHandler()
    controller = _build_controller(pipeline_controller=DummyPipelineCtrl())
    controller.on_add_job_to_queue = handler.on_add_job_to_queue  # type: ignore[attr-defined]

    controller.on_add_job_to_queue_v2()

    assert handler.calls == 0


def test_on_add_job_to_queue_v2_submits_preview_jobs_in_background_and_clears_preview():
    class DummyPipelineCtrl:
        def __init__(self) -> None:
            self.calls: list[dict[str, Any]] = []

        def submit_preview_jobs_to_queue(self, **kwargs: Any) -> int:
            self.calls.append(kwargs)
            return 2

    preview_jobs = [SimpleNamespace(job_id="job-1"), SimpleNamespace(job_id="job-2")]
    pipeline_ctrl = DummyPipelineCtrl()
    controller = _build_controller(
        pipeline_controller=pipeline_ctrl,
        preview_jobs=preview_jobs,
    )

    controller.on_add_job_to_queue_v2()

    assert len(pipeline_ctrl.calls) == 1
    assert pipeline_ctrl.calls[0]["records"] == preview_jobs
    assert controller.app_state.preview_jobs == []
    assert controller._queue_submit_in_progress is False
