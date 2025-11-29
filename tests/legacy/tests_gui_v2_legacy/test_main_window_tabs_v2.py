from __future__ import annotations

import tkinter as tk

import pytest

from src.gui.main_window_v2 import MainWindow


def test_main_window_tabs_are_prompt_pipeline_learning():
    try:
        root = tk.Tk()
    except tk.TclError:
        pytest.skip("Tkinter not available in this environment")

    root.withdraw()
    try:
        window = MainWindow(root)
        tab_ids = window.pipeline_notebook.tabs()
        labels = {window.pipeline_notebook.tab(tab_id, option="text") for tab_id in tab_ids}
        assert labels == {"Prompt", "Pipeline", "Learning"}
        assert "Run" not in labels
    finally:
        try:
            root.destroy()
        except Exception:
            pass
