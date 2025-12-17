from __future__ import annotations

from types import SimpleNamespace

from src.controller.pipeline_controller import PipelineController
from src.controller.webui_connection_controller import WebUIConnectionState


def test_controller_submits_job_and_transitions_states():
    controller = PipelineController()
    transitions: list[object] = []

    def capture_state(state: object) -> bool:
        transitions.append(state)
        return True

    controller.gui_transition_state = capture_state
    controller._webui_connection.ensure_connected = (
        lambda autostart=True: WebUIConnectionState.READY
    )
    controller._job_controller.submit_pipeline_run = lambda fn: fn()
    calls = SimpleNamespace(completed=False)

    def _pipeline_func():
        calls.completed = True
        return {"ok": True}

    controller.start_pipeline(_pipeline_func)
    assert calls.completed
    assert any(getattr(state, "name", "") == "RUNNING" for state in transitions)
