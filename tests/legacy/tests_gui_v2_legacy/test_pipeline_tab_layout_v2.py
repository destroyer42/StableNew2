from __future__ import annotations

import tkinter as tk

import pytest

from src.gui.views.pipeline_tab_frame_v2 import PipelineTabFrame
from src.gui.sidebar_panel_v2 import SidebarPanelV2
from src.gui.preview_panel_v2 import PreviewPanelV2


def test_pipeline_tab_has_sidebar_and_preview_no_top_bar():
    try:
        root = tk.Tk()
    except tk.TclError:
        pytest.skip("Tkinter not available in this environment")
    root.withdraw()
    try:
        tab = PipelineTabFrame(root)
        # No run_bar attribute in the new layout
        assert not hasattr(tab, "run_bar")
        # Sidebar and preview present
        assert isinstance(tab.sidebar, SidebarPanelV2)
        assert isinstance(tab.preview_panel, PreviewPanelV2)
    finally:
        try:
            root.destroy()
        except Exception:
            pass
