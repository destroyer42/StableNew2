"""Tests for AppController queue state restoration from JobExecutionController."""

from __future__ import annotations

from src.controller.app_controller import AppController
from src.queue.job_model import Job


def test_app_controller_load_queue_state_syncs_flags(monkeypatch) -> None:
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

    job_exec._auto_run_enabled = True
    job_exec._queue_paused = True

    queue = job_exec.get_queue()
    queue.submit(Job(job_id="job-1", config_snapshot={"prompt": "test"}))

    controller._load_queue_state()

    assert controller.app_state.auto_run_queue is True
    assert controller.app_state.is_queue_paused is True
    assert controller.job_service.auto_run_enabled is True
    assert len(controller.app_state.queue_jobs) == 1
