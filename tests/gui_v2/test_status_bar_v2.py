from __future__ import annotations

import tkinter as tk

import pytest

from src.gui.status_bar_v2 import StatusBarV2


@pytest.mark.gui
def test_status_bar_transitions(tk_root: tk.Tk):
    bar = StatusBarV2(tk_root)
    try:
        assert bar.status_label.cget("text") == "Idle"
        bar.set_running()
        assert "Running" in bar.status_label.cget("text")
        bar.set_completed()
        assert "Completed" in bar.status_label.cget("text")

        bar.set_error("boom")
        assert "Error" in bar.status_label.cget("text")
        # clear_validation_error only clears if set_validation_error was called
        # Use set_idle to reset after set_error
        bar.set_idle()
        assert bar.status_label.cget("text") == "Idle"

        bar.update_progress(0.5)
        assert 0 < bar.progress_bar["value"] <= 50

        bar.update_eta(90)
        assert "ETA: 01:30" in bar.eta_label.cget("text") or bar.eta_label.cget("text") == "ETA: 01:30"
        bar.update_eta(None)
        assert bar.eta_label.cget("text") == ""

        bar.update_status(text="Testing", progress=0.75, eta=30)
        assert "Testing" in bar.status_label.cget("text")
        assert bar.progress_bar["value"] > 0
    finally:
        bar.destroy()
