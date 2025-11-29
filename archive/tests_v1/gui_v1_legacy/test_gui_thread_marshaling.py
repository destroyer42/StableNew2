"""
Test GUI error dialog marshaling and controller lifecycle signaling on pipeline exception.
"""
import threading
import time
import tkinter as tk

from src.gui.main_window import (
    GUIState,
    StableNewGUI,
    enable_gui_test_mode,
    reset_gui_test_mode,
)


def test_pipeline_error_marshaling(monkeypatch):
    # Suppress error dialogs for test
    monkeypatch.setenv("STABLENEW_NO_ERROR_DIALOG", "1")
    enable_gui_test_mode()
    try:
        root = tk.Tk()
        gui = StableNewGUI(root)

        # Simulate pipeline error from worker thread
        def raise_error():
            gui.on_error(RuntimeError("Simulated pipeline failure"))

        t = threading.Thread(target=raise_error)
        t.start()
        t.join(timeout=2)
        # Wait for state transition
        deadline = time.time() + 2
        while time.time() < deadline:
            root.update()
            if gui.state_manager.state == GUIState.ERROR:
                break
            time.sleep(0.05)
        assert gui.state_manager.state == GUIState.ERROR, "State did not transition to ERROR"
        assert gui.controller.lifecycle_event.is_set(), "lifecycle_event was not signaled"
        # No blocking modal should appear (test would hang otherwise)
        root.destroy()
    finally:
        reset_gui_test_mode()
