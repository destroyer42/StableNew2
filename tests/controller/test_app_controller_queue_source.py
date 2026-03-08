"""Tests for AppController queue wiring to JobExecutionController."""

from __future__ import annotations

from unittest.mock import MagicMock

from src.controller.app_controller import AppController


def test_app_controller_uses_job_execution_controller_queue(monkeypatch) -> None:
    monkeypatch.setattr(
        "src.controller.job_execution_controller.load_queue_snapshot",
        lambda *_, **__: None,
    )
    monkeypatch.setattr(
        "src.controller.job_execution_controller.save_queue_snapshot",
        lambda *_, **__: True,
    )

    controller = AppController(main_window=None, threaded=False)

    job_exec = controller.pipeline_controller.get_job_execution_controller()
    job_service = controller.pipeline_controller.get_job_service()

    assert controller.job_service is job_service
    assert job_service.queue is job_exec.get_queue()

    job_exec.persist_queue_state = MagicMock()
    controller._save_queue_state()
    job_exec.persist_queue_state.assert_called_once()
