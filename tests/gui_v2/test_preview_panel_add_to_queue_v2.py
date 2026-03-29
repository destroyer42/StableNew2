from __future__ import annotations

import tkinter as tk

import pytest

from src.gui.preview_panel_v2 import PreviewPanelV2


class _Controller:
    def __init__(self) -> None:
        self.v2_calls = 0
        self.legacy_calls = 0

    def on_add_job_to_queue_v2(self) -> None:
        self.v2_calls += 1

    def on_add_to_queue(self) -> None:
        self.legacy_calls += 1


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


@pytest.mark.gui
def test_preview_panel_prefers_v2_add_to_queue_handler(tk_root: tk.Tk) -> None:
    controller = _Controller()
    panel = PreviewPanelV2(tk_root, controller=controller)

    panel._on_add_to_queue()

    assert controller.v2_calls == 1
    assert controller.legacy_calls == 0
