from __future__ import annotations

from typing import Any

from src.controller.pipeline_controller import PipelineController
from src.controller.runtime_state import GUIState, StateManager
from src.queue.job_model import JobStatus


def test_controller_job_lifecycle_mapping():
    controller = PipelineController()
    transitions: list[Any] = []

    def capture_state(state: Any) -> bool:
        transitions.append(state)
        return True

    controller.gui_transition_state = capture_state

    controller._active_job_id = "job-0"
    controller._on_job_status(type("Job", (), {"job_id": "job-0"}), JobStatus.RUNNING)
    assert transitions[-1].name == "RUNNING"

    controller._active_job_id = "job-1"
    controller._on_job_status(type("Job", (), {"job_id": "job-1"}), JobStatus.COMPLETED)
    assert transitions[-1].name == "IDLE"

    controller._active_job_id = "job-2"
    controller._on_job_status(type("Job", (), {"job_id": "job-2"}), JobStatus.FAILED)
    assert transitions[-1].name == "ERROR"

    controller._active_job_id = "job-3"
    controller._on_job_status(type("Job", (), {"job_id": "job-3"}), JobStatus.CANCELLED)
    assert transitions[-1].name == "IDLE"


def test_job_status_drives_the_real_state_manager_through_legal_transitions():
    """The mapped GUIState transitions are accepted by the real StateManager (not a capture stub)."""
    controller = PipelineController()
    controller.state_manager = StateManager()

    def status(state: JobStatus) -> None:
        controller._active_job_id = "job-123"
        controller._on_job_status(type("Job", (), {"job_id": "job-123"}), state)

    status(JobStatus.RUNNING)
    assert controller.state_manager.is_state(GUIState.RUNNING)

    status(JobStatus.COMPLETED)
    assert controller.state_manager.is_state(GUIState.IDLE)

    status(JobStatus.FAILED)
    assert controller.state_manager.is_state(GUIState.ERROR)
