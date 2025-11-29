import threading

from src.gui.controller import PipelineController
from src.gui.state import GUIState, StateManager


def test_lifecycle_event_set_after_two_runs(monkeypatch):
    """Controller should set lifecycle_event after two sequential runs without hanging."""

    sm = StateManager()
    ctrl = PipelineController(sm)

    # Provide no-op pipeline
    ctrl.set_pipeline(None)

    call_count = {"runs": 0}

    def pipeline_func():
        call_count["runs"] += 1
        return {"ok": True}

    # Run 1
    assert ctrl.start_pipeline(pipeline_func) is True
    # Wait for lifecycle
    assert ctrl.lifecycle_event.wait(timeout=2.0)
    assert sm.is_state(GUIState.IDLE)

    # Reset event for next run (start_pipeline clears it)
    assert ctrl.start_pipeline(pipeline_func) is True
    assert ctrl.lifecycle_event.wait(timeout=2.0)
    assert sm.is_state(GUIState.IDLE)

    assert call_count["runs"] == 2


def test_start_rejected_while_cleanup_running():
    sm = StateManager()
    ctrl = PipelineController(sm)
    ctrl.set_pipeline(None)

    def pipeline_func():
        return {"ok": True}

    # Simulate cleanup still running
    ctrl._cleanup_done.clear()
    assert ctrl.start_pipeline(pipeline_func) is False
    assert sm.is_state(GUIState.IDLE)


def test_stop_pipeline_triggers_async_cleanup(monkeypatch):
    sm = StateManager()
    ctrl = PipelineController(sm)
    ctrl.set_pipeline(None)

    proceed = threading.Event()

    def pipeline_func():
        proceed.wait(timeout=2.0)
        return {"ok": True}

    assert ctrl.start_pipeline(pipeline_func) is True

    cleanup_called = threading.Event()
    original_cleanup = ctrl._do_cleanup

    def wrapped_cleanup(eid, error_occurred):
        cleanup_called.set()
        return original_cleanup(eid, error_occurred)

    monkeypatch.setattr(ctrl, "_do_cleanup", wrapped_cleanup)
    assert ctrl.stop_pipeline() is True
    proceed.set()
    assert cleanup_called.wait(timeout=2.0)
