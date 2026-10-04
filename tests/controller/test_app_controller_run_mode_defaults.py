import os
from types import SimpleNamespace

import pytest
import requests

from src.api.client import ApiClient
from src.controller.app_controller import AppController, RunSource
from src.controller.app_controller_services.run_submission_service import (
    QueueRunSubmissionService,
)
from tests.helpers.job_service_di_test_helpers import make_stubbed_job_service


class DummyPipelineController:
    """Records the queue-first hand-off; never builds or runs a job."""

    def __init__(self):
        self.start_pipeline_called = 0
        self.run_configs: list[dict] = []

    def start_pipeline(self, run_config=None):
        self.start_pipeline_called += 1
        self.run_configs.append(dict(run_config or {}))
        return True


@pytest.fixture(autouse=True)
def _forbid_api_transport(monkeypatch):
    """Run/Run Now must reach the PipelineController boundary, never an API transport."""

    def _no_transport(*args, **kwargs):
        raise AssertionError("Run/Run Now must not issue API transport or generation requests")

    monkeypatch.setattr(ApiClient, "generate_images", _no_transport)
    monkeypatch.setattr(requests.Session, "request", _no_transport)
    # This is the condition the removed production hook used to react to.
    assert os.environ.get("PYTEST_CURRENT_TEST")


def _build_controller(**kwargs):
    # PR-0114C-Ty: Default to stubbed job_service to prevent real execution
    if "job_service" not in kwargs:
        kwargs["job_service"] = make_stubbed_job_service()
    if "pipeline_controller" not in kwargs:
        kwargs["pipeline_controller"] = DummyPipelineController()
    return AppController(
        main_window=None,
        pipeline_runner=None,
        api_client=None,
        structured_logger=None,
        webui_process_manager=None,
        config_manager=None,
        resource_service=None,
        **kwargs,
    )


def _attach_pipeline_state(controller, run_mode=None):
    state = SimpleNamespace(pipeline_state=SimpleNamespace(run_mode=run_mode))
    controller.app_state = state
    return state


def test_run_defaults_to_queue():
    controller = _build_controller()
    _attach_pipeline_state(controller)
    controller.start_run_v2()
    assert controller.app_state.pipeline_state.run_mode == "queue"
    pipeline = controller.pipeline_controller
    assert pipeline.start_pipeline_called == 1
    assert pipeline.run_configs[0]["run_mode"] == "queue"
    assert pipeline.run_configs[0]["source"] == RunSource.RUN_BUTTON.value


def test_run_now_defaults_to_queue():
    controller = _build_controller()
    _attach_pipeline_state(controller)
    controller.on_run_job_now_v2()
    assert controller.app_state.pipeline_state.run_mode == "queue"
    pipeline = controller.pipeline_controller
    assert pipeline.start_pipeline_called == 1
    assert pipeline.run_configs[0]["run_mode"] == "queue"
    assert pipeline.run_configs[0]["source"] == RunSource.RUN_NOW_BUTTON.value


def test_respects_existing_run_mode():
    controller = _build_controller()
    state = _attach_pipeline_state(controller)
    state.pipeline_state.run_mode = "queue"
    controller.start_run_v2()
    assert controller.app_state.pipeline_state.run_mode == "queue"
    state.pipeline_state.run_mode = "direct"
    controller.on_run_job_now_v2()
    assert controller.app_state.pipeline_state.run_mode == "queue"
    assert controller.pipeline_controller.start_pipeline_called == 2


def test_run_submission_service_hands_off_to_pipeline_controller_under_pytest():
    """Under pytest the service performs only the queue-first hand-off, nothing else."""
    pipeline = DummyPipelineController()
    captured: list[object] = []
    service = QueueRunSubmissionService(
        append_log=lambda message: None,
        capture_stage_plan_for_tests=captured.append,
    )
    app_state = SimpleNamespace(pipeline_state=SimpleNamespace(run_mode="direct"))
    recorded: list[dict] = []

    result = service.start_run(
        app_state=app_state,
        pipeline_controller=pipeline,
        mode="queue",
        source=RunSource.RUN_BUTTON.value,
        set_last_run_config=recorded.append,
    )

    assert result is True
    assert app_state.pipeline_state.run_mode == "queue"
    assert pipeline.start_pipeline_called == 1
    assert captured == [pipeline]
    assert recorded and recorded[0]["run_mode"] == "queue"


def test_pytest_only_generation_hook_is_gone():
    assert not hasattr(AppController, "_invoke_mock_generate_for_tests")
