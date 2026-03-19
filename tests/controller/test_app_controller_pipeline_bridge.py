from __future__ import annotations

from src.pipeline.job_models_v2 import NormalizedJobRecord
from src.controller.app_controller import AppController
from tests.helpers.job_service_di_test_helpers import make_stubbed_job_service


class DummyPipelineController:
    def __init__(self, *, should_raise: bool = False):
        self.start_calls = 0
        self.should_raise = should_raise
        self.last_run_config = None

    def start_pipeline(self, *args, **kwargs):
        self.start_calls += 1
        self.last_run_config = kwargs.get("run_config")
        if self.should_raise:
            raise RuntimeError("bridge failed")
        return True


def _build_controller(**kwargs) -> AppController:
    if "job_service" not in kwargs:
        kwargs["job_service"] = make_stubbed_job_service()
    controller = AppController(
        main_window=None,
        pipeline_runner=None,
        api_client=None,
        structured_logger=None,
        webui_process_manager=None,
        config_manager=None,
        resource_service=None,
        **kwargs,
    )
    if "pipeline_controller" not in kwargs:
        controller.pipeline_controller = None
    return controller


def test_start_run_v2_invokes_pipeline_controller() -> None:
    dummy = DummyPipelineController()
    controller = _build_controller(pipeline_controller=dummy)

    assert controller.start_run_v2() is True
    assert dummy.start_calls == 1
    assert dummy.last_run_config["run_mode"] == "queue"
    assert dummy.last_run_config["source"] == "run"


def test_start_run_v2_returns_false_without_pipeline_controller() -> None:
    controller = _build_controller()
    controller.pipeline_controller = None

    assert controller.start_run_v2() is False


def test_start_run_v2_returns_false_on_bridge_error() -> None:
    dummy = DummyPipelineController(should_raise=True)
    controller = _build_controller(pipeline_controller=dummy)

    assert controller.start_run_v2() is False
    assert dummy.start_calls == 1


def test_refresh_preview_from_state_async_builds_off_thread_and_applies_latest_result() -> None:
    class DummyPreviewController:
        def __init__(self) -> None:
            self.calls = 0

        def get_preview_jobs(self):
            self.calls += 1
            return [
                NormalizedJobRecord(
                    job_id="preview-1",
                    config={"prompt": "p"},
                    path_output_dir="output",
                    filename_template="{seed}",
                )
            ]

    dummy = DummyPreviewController()
    controller = _build_controller(pipeline_controller=dummy)
    controller._spawn_tracked_thread = lambda target, **kwargs: target()

    controller._refresh_preview_from_state_async()

    assert dummy.calls == 1
    assert len(controller.app_state.preview_jobs) == 1
    assert controller.app_state.preview_jobs[0].job_id == "preview-1"
