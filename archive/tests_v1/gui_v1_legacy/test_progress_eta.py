import math
import tkinter as tk
from collections.abc import Callable

import pytest

from src.gui.main_window import StableNewGUI


@pytest.mark.gui
def test_progress_eta_display(monkeypatch):
    """Ensure progress/ETA fields update via controller callbacks."""

    try:
        tk.Tk().destroy()
    except tk.TclError:
        pytest.skip("Tk/Tcl unavailable in this environment")

    # Avoid side-effects during window construction
    monkeypatch.setattr(StableNewGUI, "_launch_webui", lambda self: None)
    monkeypatch.setattr("src.gui.main_window.messagebox.showinfo", lambda *a, **k: None)
    monkeypatch.setattr("src.gui.main_window.messagebox.showerror", lambda *a, **k: None)

    class DummyEvent:
        def set(self):
            return None

        def clear(self):
            return None

        def wait(self, timeout=None):
            return True

    class DummyController:
        """Lightweight controller that records registered callbacks."""

        def __init__(self, state_manager):
            self.state_manager = state_manager
            self.cancel_token = object()
            self.lifecycle_event = DummyEvent()
            self.state_change_event = DummyEvent()
            self._handlers: dict[str, Callable] = {}

        def get_log_messages(self):
            return []

        # Support multiple potential registration APIs
        def set_progress_callbacks(self, **callbacks):
            self._handlers.update(callbacks)

        def register_progress_callbacks(self, **callbacks):
            self._handlers.update(callbacks)

        def configure_progress_callbacks(self, **callbacks):
            self._handlers.update(callbacks)

        def start_pipeline(
            self, *args, **kwargs
        ):  # defensive check - should never execute in this test
            raise AssertionError("Pipeline should not start in test")

        def stop_pipeline(
            self, *args, **kwargs
        ):  # defensive check - should never execute in this test
            return True

    monkeypatch.setattr("src.gui.main_window.PipelineController", DummyController)

    win = None
    try:
        win = StableNewGUI()
        win.root.withdraw()

        progress_bar = getattr(win, "progress_bar", None)
        status_var = getattr(win, "progress_status_var", None)
        eta_var = getattr(win, "progress_eta_var", None)

        assert progress_bar is not None, "MainWindow should expose progress_bar"
        assert status_var is not None, "MainWindow should expose progress_status_var"
        assert eta_var is not None, "MainWindow should expose progress_eta_var"

        callbacks = dict(getattr(win.controller, "_handlers", {}))

        def _first_callable(names: tuple[str, ...]):
            for name in names:
                cb = callbacks.get(name) or getattr(win.controller, name, None)
                if callable(cb):
                    callbacks[name] = cb
                    return cb
            return None

        progress_cb = _first_callable(
            (
                "progress",
                "progress_callback",
                "on_progress",
                "update_progress",
            )
        )
        eta_cb = _first_callable(("eta", "eta_callback", "progress_eta_callback", "on_eta"))
        reset_cb = _first_callable(
            (
                "reset",
                "reset_callback",
                "progress_reset_callback",
                "cancel_callback",
                "on_cancel",
            )
        )

        assert callable(progress_cb), "Progress callback was not registered"
        assert callable(eta_cb), "ETA callback was not registered"
        assert callable(reset_cb), "Cancel/reset callback was not registered"

        initial_status = status_var.get()
        initial_eta = eta_var.get()

        progress_cb(0.5, "Generating batch 1 of 2")
        win.root.update()
        progress_value = float(progress_bar["value"])
        # Progress bars now consume percentages (0-100). Keep the tolerance for float drift.
        assert math.isclose(progress_value, 50.0, rel_tol=1e-3, abs_tol=1e-3)
        assert "Generating batch 1 of 2" in status_var.get()

        eta_cb("00:30 remaining")
        win.root.update()
        assert "00:30" in eta_var.get()

        reset_cb()
        win.root.update()
        assert status_var.get() == initial_status
        assert eta_var.get() == initial_eta
        assert math.isclose(float(progress_bar["value"]), 0.0, abs_tol=1e-3)
    except tk.TclError:
        pytest.skip("Tk/Tcl unavailable in this environment")
    finally:
        if win is not None:
            try:
                win.root.destroy()
            except Exception:
                # Ignore errors during Tk root destruction in test teardown.
                pass
