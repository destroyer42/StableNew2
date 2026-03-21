from __future__ import annotations

import tkinter as tk
from types import SimpleNamespace

import pytest
from tkinter import ttk

from src.gui.panels_v2.reprocess_panel_v2 import ReprocessPanelV2
from src.gui.views.review_tab_frame_v2 import ReviewTabFrame


@pytest.mark.gui
def test_reprocess_panel_is_launcher_only(tk_root: tk.Tk) -> None:
    panel = ReprocessPanelV2(tk_root)
    panel.pack(fill="both", expand=True)

    assert panel.open_review_button.cget("text") == "Open Review Workspace"
    assert not hasattr(panel, "select_images_button")
    assert not hasattr(panel, "reprocess_button")

    panel.destroy()


@pytest.mark.gui
def test_reprocess_panel_launcher_selects_review_tab_via_notebook(tk_root: tk.Tk) -> None:
    notebook = ttk.Notebook(tk_root)
    notebook.pack(fill="both", expand=True)
    pipeline_frame = ttk.Frame(notebook)
    review_frame = ttk.Frame(notebook)
    notebook.add(pipeline_frame, text="Pipeline")
    notebook.add(review_frame, text="Review")
    notebook.select(pipeline_frame)

    panel = ReprocessPanelV2(pipeline_frame)
    panel.pack(fill="both", expand=True)

    panel.open_review_button.invoke()

    assert notebook.tab(notebook.select(), "text") == "Review"

    panel.destroy()


@pytest.mark.gui
def test_reprocess_panel_prefers_controller_main_window_review_tab(tk_root: tk.Tk) -> None:
    notebook = ttk.Notebook(tk_root)
    notebook.pack(fill="both", expand=True)
    pipeline_frame = ttk.Frame(notebook)
    review_frame = ttk.Frame(notebook)
    notebook.add(pipeline_frame, text="Pipeline")
    notebook.add(review_frame, text="Review")
    notebook.select(pipeline_frame)

    controller = SimpleNamespace(
        main_window=SimpleNamespace(center_notebook=notebook, review_tab=review_frame)
    )
    panel = ReprocessPanelV2(pipeline_frame, controller=controller)
    panel.pack(fill="both", expand=True)

    panel.open_review_button.invoke()

    assert notebook.tab(notebook.select(), "text") == "Review"

    panel.destroy()


@pytest.mark.gui
def test_review_tab_marks_itself_as_canonical_reprocess_workspace(tk_root: tk.Tk) -> None:
    tab = ReviewTabFrame(tk_root)

    assert "canonical advanced reprocess" in tab.workflow_hint_label.cget("text").lower()

    tab.destroy()
