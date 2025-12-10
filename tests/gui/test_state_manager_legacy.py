from __future__ import annotations

from types import SimpleNamespace

from src.controller.pipeline_controller import PipelineController
from src.gui.state import GUIState, StateManager
from src.queue.job_model import JobStatus


def test_job_status_transitions_state_manager():
    controller = PipelineController()
    controller.state_manager = StateManager()
    controller._active_job_id = "job-123"

    controller._on_job_status(SimpleNamespace(job_id="job-123"), JobStatus.RUNNING)
    assert controller.state_manager.is_state(GUIState.RUNNING)

    controller._active_job_id = "job-123"
    controller._on_job_status(SimpleNamespace(job_id="job-123"), JobStatus.COMPLETED)
    assert controller.state_manager.is_state(GUIState.IDLE)

    controller._active_job_id = "job-123"
    controller._on_job_status(SimpleNamespace(job_id="job-123"), JobStatus.FAILED)
    assert controller.state_manager.is_state(GUIState.ERROR)
