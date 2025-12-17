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
    finally:
        harness.cleanup()
