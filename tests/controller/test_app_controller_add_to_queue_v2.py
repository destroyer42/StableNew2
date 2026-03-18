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
    controller = object.__new__(AppController)
    controller.pipeline_controller = kwargs.get("pipeline_controller")
    controller.app_state = SimpleNamespace(
        job_draft=SimpleNamespace(pack_id=""),
        pipeline_state=SimpleNamespace(run_mode=""),
    )
    controller._last_run_config = {}
    controller._append_log = lambda text: None
    controller._build_run_config = MethodType(AppController._build_run_config, controller)
    controller._ensure_run_mode_default = MethodType(
        AppController._ensure_run_mode_default, controller
    )
    controller._prepare_queue_run_config = MethodType(
        AppController._prepare_queue_run_config, controller
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
