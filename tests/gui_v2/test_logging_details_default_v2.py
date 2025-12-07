"""Tests for PreviewPanelV2 Details button defaulting to logging view."""

from __future__ import annotations

import tkinter as tk
import pytest


@pytest.fixture
def tk_root():
    try:
        root = tk.Tk()
        root.withdraw()
    except tk.TclError as exc:
        pytest.skip(f"Tkinter/Tcl not available: {exc}")
        return

    yield root
    try:
        root.destroy()
    except Exception:
        pass


class DetailsController:
    def __init__(self):
        self.called = False

    def show_log_trace_panel(self) -> None:
        self.called = True


@pytest.fixture
def preview_panel(tk_root):
    from src.gui.preview_panel_v2 import PreviewPanelV2

    panel = PreviewPanelV2(tk_root, controller=DetailsController())
    panel.pack()
    tk_root.update_idletasks()
    return panel


def test_details_button_invokes_log_panel(preview_panel):
    controller = preview_panel.controller
    assert controller is not None

    preview_panel.details_button.invoke()
    assert getattr(controller, "called", False) is True
