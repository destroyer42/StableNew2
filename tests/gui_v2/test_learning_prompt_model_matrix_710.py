"""Real-Tk coverage for the Prompt x Model matrix: design panel mode, Preview/Run gating and the results grid."""

from __future__ import annotations

import tkinter as tk

import pytest
from PIL import Image

from src.gui.views.experiment_design_panel import ExperimentDesignPanel
from src.gui.views.learning_grid_view import LearningGridView
from src.learning.experiment_execution import thaw_snapshot
from src.learning.prompt_model_matrix import SETTINGS_NOTICE
from tests.gui_v2.test_learning_grid_270 import pending_thumbnails, pump
from tests.learning_v2.test_learning_independent_baseline_650 import PEER, Bench
from tests.learning_v2.test_model_comparison_140 import SDXL
from tests.learning_v2.test_prompt_model_matrix_710 import CANDIDATES, preview


@pytest.fixture
def errors(tk_root):
    captured = []
    tk_root.report_callback_exception = lambda *exc: captured.append(exc)
    yield captured
    assert captured == []


def test_design_mode_shows_the_settings_notice_and_enforces_bounds(tk_root, tmp_path, errors):
    bench = Bench(tmp_path)
    panel = ExperimentDesignPanel(tk_root, learning_controller=bench.controller, packs_dir=tmp_path)
    panel.study_type_var.set("Prompt x Model Matrix")
    panel._on_study_type_changed()
    tk_root.update()
    assert panel.matrix_frame.winfo_manager() == "grid"
    assert SETTINGS_NOTICE in _all_text(panel.matrix_frame)
    assert str(panel.run_button.cget("state")) == "disabled"
    panel.study_type_var.set("Two-Axis Grid")
    panel._on_study_type_changed()
    tk_root.update()
    assert panel.matrix_frame.winfo_manager() == ""
    panel.destroy()


def _all_text(widget):
    texts = []
    for child in widget.winfo_children():
        try:
            texts.append(str(child.cget("text")))
        except tk.TclError:
            pass
        texts.append(_all_text(child))
    return " ".join(texts)


def test_matrix_results_render_in_the_grid_view_and_select_cells(tk_root, tmp_path, errors):
    bench = Bench(tmp_path)
    bench.pipeline["prompt_optimizer"] = {"enabled": False}
    preview(bench)
    plan = bench.state.plan
    for index, cell in enumerate(plan):
        path = tmp_path / f"m{index}.png"
        Image.new("RGB", (60, 40), (30 * index, 80, 120)).save(path)
        cell.status, cell.job_id, cell.image_refs, cell.completed_images = (
            "completed",
            f"job-{index}",
            [str(path)],
            1,
        )
    top = tk.Toplevel(tk_root)
    top.geometry("700x500")
    view = LearningGridView(
        top,
        learning_controller=bench.controller,
        on_cell_selected=bench.controller.on_variant_selected,
    )
    view.pack(fill="both", expand=True)
    bench.controller._grid_view = view
    view.refresh()
    assert pump(tk_root, lambda: len(view.tiles) == 6)
    assert pump(tk_root, lambda: not pending_thumbnails(view))
    assert view.model.rows == 3 and view.model.cols == 2
    view.tiles[3].images[0].event_generate("<Button-1>")
    tk_root.update()
    assert bench.state.selected_variant is plan[3]
    snapshot = thaw_snapshot(bench.state.current_experiment.execution_snapshot_json)
    assert snapshot["study_type"] == "prompt_model_matrix"
    shown = " ".join(str(getattr(t, "text", "")) for t in view.model.cells)
    assert SDXL not in shown and PEER not in shown and CANDIDATES[0] not in shown
    top.destroy()
