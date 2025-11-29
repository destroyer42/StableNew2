from __future__ import annotations

import tkinter as tk

import pytest

from src.gui.preview_panel_v2 import PreviewPanelV2
from src.gui.sidebar_panel_v2 import SidebarPanelV2


@pytest.fixture
def tk_root():
    try:
        root = tk.Tk()
    except tk.TclError:
        pytest.skip("Tkinter not available in this environment")
    root.withdraw()
    yield root
    try:
        root.destroy()
    except Exception:
        pass


def test_preview_updates_from_sidebar(tk_root):
    sidebar = SidebarPanelV2(tk_root)
    preview = PreviewPanelV2(tk_root)
    sidebar.stage_states["img2img"].set(False)
    sidebar.run_mode_var.set("queue")
    sidebar.run_scope_var.set("selected")
    preview.update_from_controls(sidebar)
    assert "Txt2Img" in preview.summary_label.cget("text")
    assert "Img2Img" not in preview.summary_label.cget("text")
    assert "queue" in preview.mode_label.cget("text")
    assert "selected" in preview.scope_label.cget("text")
