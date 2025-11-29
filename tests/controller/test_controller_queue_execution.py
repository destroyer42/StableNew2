from __future__ import annotations

from types import SimpleNamespace

from src.controller.webui_connection_controller import WebUIConnectionState
from src.controller.pipeline_controller import PipelineController
from src.gui.state import GUIState, StateManager


def test_controller_submits_job_and_transitions_states():
    state_manager = StateManager(initial_state=GUIState.IDLE)
    controller = PipelineController(state_manager=state_manager)
    controller._webui_connection.ensure_connected = lambda autostart=True: WebUIConnectionState.READY
    controller._job_controller.submit_pipeline_run = lambda fn: fn()
    calls = SimpleNamespace(completed=False)

    def _pipeline_func():
        calls.completed = True
        return {"ok": True}

    controller.start_pipeline(_pipeline_func)
    assert calls.completed
    assert state_manager.is_state(GUIState.RUNNING)
