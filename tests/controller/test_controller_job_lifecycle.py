from __future__ import annotations

from typing import List, Any

from src.controller.pipeline_controller import PipelineController
from src.queue.job_model import JobStatus


def test_controller_job_lifecycle_mapping():
    controller = PipelineController()
    transitions: List[Any] = []

    def capture_state(state: Any) -> bool:
        transitions.append(state)
        return True

    controller.gui_transition_state = capture_state

    controller._active_job_id = "job-1"
    controller._on_job_status(type("Job", (), {"job_id": "job-1"}), JobStatus.COMPLETED)
    assert transitions[-1].name == "IDLE"

    controller._active_job_id = "job-2"
    controller._on_job_status(type("Job", (), {"job_id": "job-2"}), JobStatus.FAILED)
    assert transitions[-1].name == "ERROR"

    controller._active_job_id = "job-3"
    controller._on_job_status(type("Job", (), {"job_id": "job-3"}), JobStatus.CANCELLED)
    assert transitions[-1].name == "IDLE"
