from __future__ import annotations

from src.controller.app_controller import AppController
from tests.helpers.job_service_di_test_helpers import make_stubbed_job_service


class DummyPipelineController:
    def __init__(self):
        self.start_calls = 0

    def start_pipeline(self, *args, **kwargs):
        self.start_calls += 1
        return True


def _build_controller(**kwargs) -> AppController:
    # PR-0114C-Ty: Default to stubbed job_service to prevent real execution
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


def test_run_pipeline_v2_bridge_invokes_pipeline_controller():
    dummy = DummyPipelineController()
    controller = _build_controller(pipeline_controller=dummy)

    assert controller.run_pipeline_v2_bridge() is True
    assert dummy.start_calls == 1


def test_run_pipeline_v2_bridge_without_pipeline_controller():
    controller = _build_controller()
    controller.pipeline_controller = None

    assert controller.run_pipeline_v2_bridge() is False


def test_start_run_v2_uses_bridge_and_skips_legacy(monkeypatch):
    dummy = DummyPipelineController()
    controller = _build_controller(pipeline_controller=dummy)
    legacy_called = {"count": 0}

    def fake_start_run(self):
        legacy_called["count"] += 1
        return "legacy"

    monkeypatch.setattr(AppController, "start_run", fake_start_run, raising=True)

    assert controller.start_run_v2() is True
    assert dummy.start_calls == 1
    assert legacy_called["count"] == 0


def test_start_run_v2_falls_back_to_legacy(monkeypatch):
    controller = _build_controller()
    legacy_called = {"count": 0}

    def fake_start_run(self):
        legacy_called["count"] += 1
        return "legacy"

    monkeypatch.setattr(AppController, "start_run", fake_start_run, raising=True)

    assert controller.start_run_v2() == "legacy"
    assert legacy_called["count"] == 1
