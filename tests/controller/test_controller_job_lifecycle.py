from __future__ import annotations

from src.controller.pipeline_controller import PipelineController
from src.queue.job_model import JobStatus
from src.gui.state import GUIState, StateManager


def test_controller_job_lifecycle_mapping():
    state_manager = StateManager(initial_state=GUIState.IDLE)
    controller = PipelineController()
    controller.state_manager = state_manager
    controller._active_job_id = "job-1"
    controller._on_job_status(type("Job", (), {"job_id": "job-1"}), JobStatus.COMPLETED)
    assert state_manager.current == GUIState.IDLE
    controller._active_job_id = "job-2"
    controller._on_job_status(type("Job", (), {"job_id": "job-2"}), JobStatus.FAILED)
    assert state_manager.current == GUIState.ERROR
    controller._active_job_id = "job-3"
    controller._on_job_status(type("Job", (), {"job_id": "job-3"}), JobStatus.CANCELLED)
    assert state_manager.current == GUIState.IDLE
