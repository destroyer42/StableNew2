from __future__ import annotations

import tkinter as tk

import pytest

from src.app_factory import build_v2_app
from src.gui.preview_panel_v2 import PreviewPanelV2
from src.gui.sidebar_panel_v2 import SidebarPanelV2
from src.gui.views.stage_cards_panel import StageCardsPanel


@pytest.mark.gui
def test_pipeline_tab_three_column_layout_v2() -> None:
    try:
        root, app_state, controller, window = build_v2_app()
    except Exception as exc:
        pytest.skip(f"Tkinter not available: {exc}")
        return

    try:
        pipeline_tab = getattr(window, "pipeline_tab", None)
        assert pipeline_tab is not None, "Pipeline tab should exist"

        assert hasattr(pipeline_tab, "left_column"), "Pipeline tab should expose left column frame"
        assert hasattr(pipeline_tab, "center_column"), "Pipeline tab should expose center column frame"
        assert hasattr(pipeline_tab, "right_column"), "Pipeline tab should expose right column frame"

        left_column = pipeline_tab.left_column
        center_column = pipeline_tab.center_column
        right_column = pipeline_tab.right_column

        assert left_column.grid_info().get("column", None) == 0
        assert center_column.grid_info().get("column", None) == 1
        assert right_column.grid_info().get("column", None) == 2

        assert isinstance(getattr(pipeline_tab, "sidebar", None), SidebarPanelV2)
        assert isinstance(getattr(pipeline_tab, "stage_cards_panel", None), StageCardsPanel)
        assert isinstance(getattr(pipeline_tab, "preview_panel", None), PreviewPanelV2)
    finally:
        try:
            root.destroy()
        except Exception:
            pass
