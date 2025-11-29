from __future__ import annotations

import tkinter as tk

import pytest

from src.gui.pipeline_panel_v2 import PipelinePanelV2
from src.gui.widgets.scrollable_frame_v2 import ScrollableFrame
from src.gui.views.pipeline_tab_frame_v2 import PipelineTabFrame


def test_pipeline_panel_uses_scrollable_center():
    try:
        root = tk.Tk()
    except tk.TclError:
        pytest.skip("Tkinter not available in this environment")
    root.withdraw()
    try:
        panel = PipelinePanelV2(root)
        assert isinstance(panel._scroll, ScrollableFrame)
        # Stage cards should be children of the scrollable inner frame
        assert panel.txt2img_card.master == panel.body or panel.txt2img_card.master == panel._scroll.inner
    finally:
        try:
            root.destroy()
        except Exception:
            pass


def test_pipeline_tab_center_has_scrollable_frame():
    try:
        root = tk.Tk()
    except tk.TclError:
        pytest.skip("Tkinter not available in this environment")
    root.withdraw()
    try:
        tab = PipelineTabFrame(root)
        assert isinstance(tab.stage_scroll, ScrollableFrame)
        assert tab.stage_cards_panel.master == tab.stage_cards_frame
    finally:
        try:
            root.destroy()
        except Exception:
            pass
