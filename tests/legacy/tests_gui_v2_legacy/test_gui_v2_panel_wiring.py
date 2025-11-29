from __future__ import annotations

import tkinter as tk

import pytest

from src.gui.panels_v2 import PipelinePanelV2, PreviewPanelV2, RandomizerPanelV2, SidebarPanelV2, StatusBarV2


def test_panel_wrappers_construct():
    try:
        root = tk.Tk()
    except Exception:
        pytest.skip("Tkinter/Tcl not available")
    sidebar = SidebarPanelV2(root, controller=None, theme=None)
    pipeline = PipelinePanelV2(root, controller=None, theme=None)
    randomizer = RandomizerPanelV2(root, controller=None, theme=None)
    preview = PreviewPanelV2(root, controller=None, theme=None)
    status = StatusBarV2(root, controller=None, theme=None)

    assert sidebar is not None
    assert pipeline is not None
    assert randomizer is not None
    assert preview is not None
    assert status is not None
    root.destroy()
