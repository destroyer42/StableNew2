from __future__ import annotations

import tkinter as tk

import pytest

from tests.helpers.gui_harness_v2 import GuiV2Harness


@pytest.mark.gui
def test_main_window_v2_smoke(tk_root: tk.Tk) -> None:
    harness = GuiV2Harness(tk_root)
    try:
        notebook = harness.window.center_notebook
        tab_texts = [notebook.tab(idx, "text") for idx in range(notebook.index("end"))]
        assert "Prompt" in tab_texts
        assert "Pipeline" in tab_texts
        assert "Learning" in tab_texts
        assert "Photo Optomize" in tab_texts
        assert "SVD Img2Vid" in tab_texts
        assert harness.window.header_zone.help_button.cget("text") == "Help Mode: Off"
    finally:
        harness.cleanup()


@pytest.mark.gui
def test_main_window_help_button_toggles_help_mode(tk_root: tk.Tk) -> None:
    harness = GuiV2Harness(tk_root)
    try:
        assert harness.controller.app_state.help_mode_enabled is False
        harness.window.header_zone.help_button.invoke()
        tk_root.update()
        assert harness.controller.app_state.help_mode_enabled is True
        assert harness.window.header_zone.help_button.cget("text") == "Help Mode: On"
    finally:
        harness.cleanup()
