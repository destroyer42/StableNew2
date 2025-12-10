from src.controller.webui_connection_controller import WebUIConnectionState
from types import SimpleNamespace
from unittest import mock

import pytest

from src.controller.pipeline_controller import PipelineController
from src.queue.job_model import JobStatus
from src.gui.state import StateManager, GUIState


class FakeQueueExecutionController:
    def __init__(self):
        self.submitted = []
        self.cancelled = []
        self.callback = None

    def submit_pipeline_job(self, payload):
        job_id = f"job-{len(self.submitted)+1}"
        self.submitted.append(payload)
        return job_id

    def cancel_job(self, job_id: str):
        self.cancelled.append(job_id)

    def observe(self, key, callback):
        self.callback = callback

    register_status_callback = observe


def test_queue_mode_disabled_uses_direct(monkeypatch):
    monkeypatch.setattr("src.controller.pipeline_controller.is_queue_execution_enabled", lambda: False)
    controller = PipelineController()
    controller._webui_connection.ensure_connected = lambda autostart=True: WebUIConnectionState.READY
    controller._queue_execution_enabled = False
    controller._queue_execution_controller = mock.Mock()
    controller._job_controller.submit_pipeline_run = mock.Mock(return_value="direct-job")

    called = controller.start_pipeline(lambda: {"result": 1})
    assert called is True
    controller._job_controller.submit_pipeline_run.assert_called_once()
    controller._queue_execution_controller.submit_pipeline_job.assert_not_called()


def test_queue_mode_enabled_submits_and_handles_callbacks(monkeypatch):
    monkeypatch.setattr("src.controller.pipeline_controller.is_queue_execution_enabled", lambda: True)
    queue_ctrl = FakeQueueExecutionController()
    sm = StateManager()
    controller = PipelineController(queue_execution_controller=queue_ctrl)
    controller.state_manager = sm
    controller._webui_connection.ensure_connected = lambda autostart=True: WebUIConnectionState.READY
    controller._queue_execution_enabled = True

    started = controller.start_pipeline(lambda: {"ok": True})
    assert started is True
    assert controller._active_job_id == "job-1"

    job = SimpleNamespace(job_id="job-1")
    queue_ctrl.callback(job, JobStatus.QUEUED)
    assert sm.is_state(GUIState.RUNNING)

    queue_ctrl.callback(job, JobStatus.RUNNING)
    assert sm.is_state(GUIState.RUNNING)

    queue_ctrl.callback(job, JobStatus.COMPLETED)
    assert sm.is_state(GUIState.IDLE)
    assert controller._active_job_id is None


def test_queue_mode_cancel(monkeypatch):
    monkeypatch.setattr("src.controller.pipeline_controller.is_queue_execution_enabled", lambda: True)
    queue_ctrl = FakeQueueExecutionController()
    controller = PipelineController(queue_execution_controller=queue_ctrl)
    controller.state_manager = StateManager()
    controller._queue_execution_enabled = True
    controller._active_job_id = "job-xyz"

    controller.stop_pipeline()
    assert queue_ctrl.cancelled == ["job-xyz"]
