"""Tests for StatusBarV2 progress/ETA wiring."""

from __future__ import annotations


def test_status_bar_initial_state(gui_app_with_dummies):
    gui, _controller, _cfg = gui_app_with_dummies
    gui.root.update_idletasks()
    assert gui.status_bar_v2.status_label["text"] == "Idle"
    assert float(gui.status_bar_v2.progress_bar["value"]) == 0.0
    assert gui.status_bar_v2.eta_label["text"] == ""


def test_progress_callback_updates_progress_and_eta(gui_app_with_dummies):
    gui, controller, _cfg = gui_app_with_dummies
    progress_cb = controller.progress_callbacks["on_progress"]
    progress_cb(progress=5, total=10, eta_seconds=30)
    gui.root.update_idletasks()
    assert 49.0 <= float(gui.status_bar_v2.progress_bar["value"]) <= 51.0
    assert gui.status_bar_v2.eta_label["text"] == "ETA: 00:30"


def test_state_change_callback_updates_status_text(gui_app_with_dummies):
    gui, controller, _cfg = gui_app_with_dummies
    state_cb = controller.progress_callbacks["on_state_change"]

    state_cb("RUNNING")
    gui.root.update_idletasks()
    assert gui.status_bar_v2.status_label["text"] == "Running..."

    state_cb("COMPLETED")
    gui.root.update_idletasks()
    assert gui.status_bar_v2.status_label["text"] == "Completed"

    state_cb("ERROR")
    gui.root.update_idletasks()
    assert "Error" in gui.status_bar_v2.status_label["text"]
