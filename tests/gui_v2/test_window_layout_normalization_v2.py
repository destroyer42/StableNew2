"""Tests for PR-GUI-H layout normalization (MainWindow + Pipeline columns)."""

from __future__ import annotations

import tkinter as tk

import pytest

from src.gui.app_state_v2 import AppStateV2
from src.gui.main_window_v2 import MainWindowV2
from src.gui.view_contracts.pipeline_layout_contract import get_stage_card_min_width
from src.gui.views.pipeline_tab_frame_v2 import PipelineTabFrame
from src.gui.widgets.scrollable_frame_v2 import ScrollableFrame


@pytest.fixture
def tk_root():
    try:
        root = tk.Tk()
        root.withdraw()
    except tk.TclError as exc:
        pytest.skip(f"Tkinter unavailable: {exc}")
        return
    yield root
    try:
        root.destroy()
    except Exception:
        pass


def test_main_window_applies_screen_aware_default_geometry(tk_root):
    window = MainWindowV2(root=tk_root, app_state=AppStateV2())
    tk_root.update_idletasks()
    layout = window._layout()

    geometry = tk_root.geometry()
    width_str, rest = geometry.split("x", 1)
    height_str = rest.split("+", 1)[0]
    width = int(width_str)
    height = int(height_str)

    # never smaller than the minimum and never larger than the display it is on (PR-GUI-100)
    assert layout.min_width <= width <= tk_root.winfo_screenwidth()
    assert layout.min_height <= height <= tk_root.winfo_screenheight()
    assert tk_root.minsize() == (layout.min_width, layout.min_height)
    assert layout.min_width <= tk_root.winfo_screenwidth() - 24


def test_pipeline_columns_use_single_scrollable_frame(tk_root):
    tab = PipelineTabFrame(
        tk_root,
        app_state=AppStateV2(),
    )
    tk_root.update_idletasks()

    assert isinstance(tab.left_scroll, ScrollableFrame)
    assert isinstance(tab.stage_scroll, ScrollableFrame)
    assert isinstance(tab.right_scroll, ScrollableFrame)

    assert len(tab.left_scroll.inner.winfo_children()) >= 2
    assert len(tab.stage_scroll.inner.winfo_children()) == 1
    assert len(tab.right_scroll.inner.winfo_children()) >= 3

    for idx in range(3):
        assert tab.columnconfigure(idx)["minsize"] == tab.MIN_COLUMN_WIDTH

    assert tab.stage_scroll.inner.columnconfigure(0)["minsize"] == get_stage_card_min_width()
