from tkinter import ttk

import pytest

from src.gui.main_window import StableNewGUI
from src.gui.state import GUIState


@pytest.fixture
def gui_app(monkeypatch, tk_root):
    """Headless-safe GUI app fixture using shared Tk root to skip when Tk is unavailable."""
    # Avoid heavy initialization that relies on full panel state; we only test status bar progress
    monkeypatch.setattr(StableNewGUI, "_initialize_ui_state", lambda self: None)
    monkeypatch.setattr(StableNewGUI, "_launch_webui", lambda self: None)
    monkeypatch.setattr("src.gui.main_window.messagebox.showinfo", lambda *args, **kwargs: None)
    # Force StableNewGUI to reuse the shared Tk root instead of creating a new one
    monkeypatch.setattr("src.gui.main_window.tk.Tk", lambda: tk_root)

    app = StableNewGUI()
    try:
        yield app
    finally:
        if app.root is not tk_root:
            try:
                app.root.destroy()
            except Exception:
                pass
        for child in list(tk_root.winfo_children()):
            try:
                child.destroy()
            except Exception:
                pass


def test_status_bar_initializes_progress_and_eta(gui_app):
    assert isinstance(gui_app.progress_bar, ttk.Progressbar)
    assert gui_app.progress_bar["value"] == pytest.approx(0)
    assert gui_app.progress_bar["maximum"] == pytest.approx(100)
    assert gui_app.eta_var.get() == gui_app._progress_eta_default
    assert gui_app.progress_message_var.get() == gui_app._progress_idle_message


def test_update_progress_updates_ui(gui_app):
    gui_app._update_progress("txt2img", 45, "00:30")
    gui_app.root.update()

    assert gui_app.progress_bar["value"] == pytest.approx(45)
    assert gui_app.progress_message_var.get() == "txt2img (45%)"
    assert gui_app.eta_var.get() == "ETA: 00:30"


def test_idle_transition_resets_progress(gui_app):
    gui_app._update_progress("img2img", 80, "01:15")
    gui_app.root.update()

    assert gui_app.progress_bar["value"] == pytest.approx(80)
    assert gui_app.eta_var.get() == "ETA: 01:15"

    gui_app.state_manager.transition_to(GUIState.RUNNING)
    gui_app.state_manager.transition_to(GUIState.IDLE)
    gui_app.root.update()

    assert gui_app.progress_bar["value"] == pytest.approx(0)
    assert gui_app.eta_var.get() == gui_app._progress_eta_default
    assert gui_app.progress_message_var.get() == gui_app._progress_idle_message
