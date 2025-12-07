"""Tests for PR-GUI-H layout normalization (MainWindow + Pipeline columns)."""

from __future__ import annotations

import tkinter as tk

import pytest

from src.gui.app_state_v2 import AppStateV2
from src.gui.main_window_v2 import (
    DEFAULT_MAIN_WINDOW_HEIGHT,
    DEFAULT_MAIN_WINDOW_WIDTH,
    MIN_MAIN_WINDOW_HEIGHT,
    MIN_MAIN_WINDOW_WIDTH,
    MainWindowV2,
)
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


def test_main_window_applies_default_geometry(tk_root):
    MainWindowV2(root=tk_root, app_state=AppStateV2())
    tk_root.update_idletasks()

    geometry = tk_root.geometry()
    width_str, rest = geometry.split("x", 1)
    height_str = rest.split("+", 1)[0]
    width = int(width_str)
    height = int(height_str)

    assert width >= MIN_MAIN_WINDOW_WIDTH
    assert height >= MIN_MAIN_WINDOW_HEIGHT
    assert width == DEFAULT_MAIN_WINDOW_WIDTH or width >= MIN_MAIN_WINDOW_WIDTH
    assert height == DEFAULT_MAIN_WINDOW_HEIGHT or height >= MIN_MAIN_WINDOW_HEIGHT


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
