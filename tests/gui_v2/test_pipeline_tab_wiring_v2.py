from __future__ import annotations

import tkinter as tk

import pytest

from tests.helpers.gui_harness_v2 import GuiV2Harness


@pytest.mark.gui
def test_pipeline_tab_frame_v2_wiring(tk_root: tk.Tk) -> None:
    harness = GuiV2Harness(tk_root)
    tab = harness.pipeline_tab
    assert tab is not None
    try:
        assert hasattr(tab, "sidebar")
        assert hasattr(tab, "stage_cards_panel")
        assert hasattr(tab, "preview_panel")
        assert tab.left_column.winfo_exists()
        assert tab.center_column.winfo_exists()
        assert tab.right_column.winfo_exists()
    finally:
        harness.cleanup()
