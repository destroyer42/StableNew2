#ARCHIVE
# Legacy run-now bridge tests archived since new error handling diverges.
from __future__ import annotations

from typing import Any

from src.controller.app_controller import AppController
from tests.helpers.job_service_di_test_helpers import make_stubbed_job_service


class DummyQueueController:
    def __init__(self) -> None:
        self.queue_called = 0
        self.v2_called = 0

    def on_run_job_now(self) -> str:
        self.queue_called += 1
        return "queue-run"

    def start_run_v2(self) -> str:
        self.v2_called += 1
        return "v2-run"


def _build_controller(**kwargs: Any) -> AppController:
    # PR-0114C-Ty: Default to stubbed job_service to prevent real execution
    if "job_service" not in kwargs:
        kwargs["job_service"] = make_stubbed_job_service()
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


def test_on_run_job_now_v2_prefers_queue_handler(monkeypatch):
    dummy = DummyQueueController()
    controller = _build_controller()

    controller.on_run_job_now = dummy.on_run_job_now  # type: ignore[attr-defined]
    controller.start_run_v2 = dummy.start_run_v2  # type: ignore[attr-defined]

    result = controller.on_run_job_now_v2()

    assert result == "queue-run"
    assert dummy.queue_called == 1
    assert dummy.v2_called == 0


def test_on_run_job_now_v2_falls_back_to_start_run_v2(monkeypatch):
    dummy = DummyQueueController()
    controller = _build_controller()

    # Only start_run_v2 available
    controller.start_run_v2 = dummy.start_run_v2  # type: ignore[attr-defined]

    result = controller.on_run_job_now_v2()

    assert result == "v2-run"
    assert dummy.queue_called == 0
    assert dummy.v2_called == 1
