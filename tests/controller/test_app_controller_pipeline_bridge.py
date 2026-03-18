from __future__ import annotations

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
    assert dummy.last_run_config["run_mode"] == "direct"
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
