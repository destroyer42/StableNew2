from __future__ import annotations

import tkinter as tk
from datetime import datetime
from pathlib import Path
from types import SimpleNamespace

import pytest
from tkinter import ttk

from src.gui.panels_v2.reprocess_panel_v2 import ReprocessPanelV2
from src.gui.views.review_tab_frame_v2 import ReviewTabFrame
from src.queue.job_history_store import JobHistoryEntry
from src.queue.job_model import JobStatus
from src.utils.image_metadata import ReadPayloadResult


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


@pytest.mark.gui
def test_review_tab_imports_selected_images_to_staged_curation(
    tk_root: tk.Tk, tmp_path: Path
) -> None:
    imported: list[tuple[list[str], str | None]] = []

    class _LearningController:
        def import_review_images_to_staged_curation(self, image_paths, *, display_name=None, source_label="review_tab"):
            imported.append((list(image_paths), display_name))
            return "curation-import-1"

    app_controller = SimpleNamespace(
        main_window=SimpleNamespace(
            learning_tab=SimpleNamespace(learning_controller=_LearningController())
        )
    )
    image_a = tmp_path / "a.png"
    image_b = tmp_path / "b.png"
    image_a.write_text("placeholder", encoding="utf-8")
    image_b.write_text("placeholder", encoding="utf-8")

    tab = ReviewTabFrame(tk_root, app_controller=app_controller)
    try:
        with pytest.MonkeyPatch.context() as mp:
            mp.setattr(tab.preview, "set_image_from_path", lambda path: None)
            mp.setattr(
                "src.gui.views.review_tab_frame_v2.extract_embedded_metadata",
                lambda _path: ReadPayloadResult(payload=None, status="missing"),
            )
            mp.setattr("src.gui.views.review_tab_frame_v2.messagebox.showinfo", lambda *args, **kwargs: None)
            mp.setattr("src.gui.views.review_tab_frame_v2.messagebox.showerror", lambda *args, **kwargs: None)
            mp.setattr("src.gui.views.review_tab_frame_v2.messagebox.showwarning", lambda *args, **kwargs: None)
            tab._set_selected_images([image_a, image_b])  # noqa: SLF001
            tab.images_list.selection_set(0, 1)
            tab._on_import_selected_to_staged_curation()  # noqa: SLF001
    finally:
        tab.destroy()

    assert imported
    assert imported[0][0] == [str(image_a), str(image_b)]
    assert imported[0][1] == "Review Import - 2 images"


@pytest.mark.gui
def test_review_tab_imports_selected_history_job_to_staged_curation(
    tk_root: tk.Tk, tmp_path: Path
) -> None:
    imported: list[str] = []

    class _LearningController:
        def import_history_entry_to_staged_curation(self, entry):
            imported.append(entry.job_id)
            return "curation-history-1"

    entry = JobHistoryEntry(
        job_id="history-1",
        created_at=datetime.utcnow(),
        status=JobStatus.COMPLETED,
        prompt_pack_id="History Pack",
        result={"output_dir": str(tmp_path)},
    )
    app_controller = SimpleNamespace(
        main_window=SimpleNamespace(
            learning_tab=SimpleNamespace(learning_controller=_LearningController())
        )
    )
    app_state = SimpleNamespace(history_items=[entry])

    tab = ReviewTabFrame(tk_root, app_controller=app_controller, app_state=app_state)
    try:
        with pytest.MonkeyPatch.context() as mp:
            mp.setattr("src.gui.views.review_tab_frame_v2.messagebox.showinfo", lambda *args, **kwargs: None)
            mp.setattr("src.gui.views.review_tab_frame_v2.messagebox.showerror", lambda *args, **kwargs: None)
            mp.setattr("src.gui.views.review_tab_frame_v2.messagebox.showwarning", lambda *args, **kwargs: None)
            picker = ttk.Treeview(tk_root, columns=("status", "pack", "job_id"), show="headings")
            picker.insert("", "end", iid="history-1", values=("completed", "History Pack", "history-1"))
            picker.selection_set("history-1")
            tab._import_selected_history_job(picker)  # noqa: SLF001
    finally:
        picker.destroy()
        tab.destroy()

    assert imported == ["history-1"]
