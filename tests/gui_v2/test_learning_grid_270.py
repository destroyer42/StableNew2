"""Real-Tk coverage: design, preview, run, select, view and export a Two-Axis Grid with fake services."""

from __future__ import annotations

import time
import tkinter as tk
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace
from unittest.mock import patch

import pytest
from PIL import Image

from src.gui.app_state_v2 import AppStateV2
from src.gui.views.experiment_design_panel import ExperimentDesignPanel
from src.gui.views.learning_grid_view import LearningGridView
from src.gui.views.learning_tab_frame_v2 import LearningTabFrame
from src.learning.execution_controller import LearningExecutionController
from src.learning.experiment_execution import thaw_snapshot
from src.queue.job_repository import JobRepository
from src.services.ui_state_store import UIStateStore
from tests.learning_v2.test_learning_recovery_260 import RepositoryService
from tests.learning_v2.test_two_axis_grid_270 import grid_controller, grid_experiment


def pump(root, until, timeout=6.0):
    end = time.monotonic() + timeout
    while time.monotonic() < end:
        root.update()
        if until():
            return True
        time.sleep(0.01)
    return False


def finish_cells(controller, folder, *, images=2):
    plan = controller.learning_state.plan
    for index, variant in enumerate(plan):
        row, col = divmod(index, 3)
        variant.status, variant.job_id = "completed", variant.job_id or f"job-{index}"
        variant.image_refs = []
        for sample in range(images):
            path = folder / f"c{index}s{sample}.png"
            Image.new("RGB", (60, 40), (40 + 60 * col, 40 + 80 * row, 60 + 30 * sample)).save(path)
            variant.image_refs.append(str(path))
        variant.completed_images = images
        variant.execution_metadata = {
            "controlled_evidence_valid": True,
            "actual_all_seeds": [7, 8][:images],
        }


def pending_thumbnails(view):
    return bool(view._pending)


@pytest.fixture
def errors(tk_root):
    captured = []
    tk_root.report_callback_exception = lambda *exc: captured.append(exc)
    yield captured
    assert captured == []


def test_design_preview_run_select_view_and_export_flow(tk_root, tmp_path, errors):
    repo = JobRepository(tmp_path / "jobs.sqlite3")
    try:
        controller = grid_controller(grid_experiment(), build=False)
        service = RepositoryService(repo)
        controller.pipeline_controller = SimpleNamespace(_job_service=service)
        controller.execution_controller = LearningExecutionController(
            controller.learning_state, service
        )
        controller.execution_controller.set_completion_callback(
            controller._apply_variant_completion_evidence
        )
        controller.execution_controller.set_presentation_callback(
            controller._on_variant_completion_published
        )
        panel = ExperimentDesignPanel(tk_root, learning_controller=controller, packs_dir=tmp_path)
        panel.study_type_var.set("Two-Axis Grid")
        panel._on_study_type_changed()
        panel.name_var.set("grid study")
        panel.prompt_source_var.set("custom")
        panel._on_prompt_source_changed()
        panel.custom_prompt_text.config(state="normal")
        panel.custom_prompt_text.delete("1.0", tk.END)
        panel.custom_prompt_text.insert("1.0", "portrait, detailed")
        panel.images_var.set(2)
        tk_root.update()
        assert (
            "9 cells" in panel.grid_frame.summary_var.get()
            and "18 images" in panel.grid_frame.summary_var.get()
        )
        assert (
            str(panel.run_button.cget("state")) == "disabled"
            and str(panel.build_button.cget("state")) == "normal"
        )
        panel._on_build_preview()
        snapshot = thaw_snapshot(
            controller.learning_state.current_experiment.execution_snapshot_json
        )
        assert snapshot["two_axis_grid"]["total_cells"] == 9 and service.calls == []
        assert "R1C1" in panel.summary_var.get() and str(panel.run_button.cget("state")) == "normal"
        # Any execution-relevant edit invalidates the Preview.
        panel.grid_frame.x_axis.values_var.set("5, 7, 8")
        assert (
            str(panel.run_button.cget("state")) == "disabled"
            and "Build Preview again" in panel.feedback_var.get()
        )
        panel._on_run_experiment()
        assert service.calls == []
        panel.grid_frame.x_axis.values_var.set("5, 7, 9")
        panel._on_build_preview()
        panel._on_run_experiment()
        panel._on_run_experiment()
        assert len(service.calls) == 1 and len(service.calls[0]) == 9

        finish_cells(controller, tmp_path)
        exported, messages = [], []
        out = tmp_path / "sheet.png"
        shell = tk.Toplevel(tk_root)
        shell.geometry("900x600")
        view = LearningGridView(
            shell,
            learning_controller=controller,
            on_cell_selected=controller.on_variant_selected,
            save_dialog=lambda **_kw: str(out),
            notify=lambda title, text: messages.append((title, text)),
        )
        view.pack(fill="both", expand=True)
        controller._grid_view = view
        view.refresh()
        assert pump(tk_root, lambda: len(view.tiles) == 9)
        assert pump(
            tk_root,
            lambda: not pending_thumbnails(view)
            and all(
                getattr(holder, "image", None) is not None
                for tile in view.tiles.values()
                for holder in tile.images
            ),
        )
        assert list(view.tiles) == list(range(9))
        view.tiles[4].images[0].event_generate("<Button-1>")
        tk_root.update()
        assert controller.learning_state.selected_variant is controller.learning_state.plan[4]
        assert view.selected_index == 4
        assert "completed" in view.summary_var.get() or "18/18" in view.summary_var.get()
        view.export_button.invoke()
        assert pump(tk_root, lambda: bool(messages))
        assert (
            messages[0][0] == "Contact sheet exported"
            and out.is_file()
            and out.with_suffix(".json").is_file()
        )
        assert Image.open(out).size[0] > 400
        panel.destroy()
        shell.destroy()
        exported.append(1)
    finally:
        repo.close()


def test_grid_scrolls_loads_thumbnails_lazily_and_rejects_stale_results(tk_root, tmp_path, errors):
    controller = grid_controller(grid_experiment())
    finish_cells(controller, tmp_path)
    top = tk.Toplevel(tk_root)
    top.geometry("300x200")
    view = LearningGridView(top, learning_controller=controller)
    view.pack(fill="both", expand=True)
    controller._grid_view = view
    view.canvas.configure(width=260, height=120)
    view.refresh()
    top.update()
    assert pump(tk_root, lambda: len(view.tiles) == 9)
    view.update_idletasks()
    region = view.canvas.bbox("all")
    assert (
        region[2] - region[0] > view.canvas.winfo_width()
        or region[3] - region[1] > view.canvas.winfo_height()
    )
    assert view.hbar.get()[1] < 1.0 or view.vbar.get()[1] < 1.0
    assert pump(tk_root, lambda: not pending_thumbnails(view))
    first_wave = {path for path, _ in view._cache}
    assert 0 < len(first_wave) < 18  # only the visible tiles were decoded
    view.canvas.yview_moveto(1.0)
    view.canvas.xview_moveto(1.0)
    assert pump(tk_root, lambda: len({path for path, _ in view._cache}) > len(first_wave))
    # A response from an older render is dropped without touching any widget.
    stale_generation = view._generation
    controller.learning_state.plan[0].status = "failed"
    view._render()
    assert view._generation == stale_generation + 1
    picture = Image.new("RGB", (8, 8), (1, 2, 3))
    before = dict(view._cache)
    assert (
        view.accept_thumbnail(
            stale_generation, controller.learning_state.plan[0].image_refs[0], picture
        )
        is False
    )
    assert dict(view._cache) == before
    # Destroying the view with work in flight is harmless and later responses are inert.
    view.canvas.yview_moveto(0.0)
    view._schedule_visible()
    top.update()
    generation = view._generation
    top.destroy()
    pump(tk_root, lambda: False, timeout=0.3)
    assert view.accept_thumbnail(generation, "x.png", Image.new("RGB", (4, 4))) is False


def test_tab_integration_switching_visibility_and_failed_cell_position(tk_root, tmp_path, errors):
    with TemporaryDirectory() as tmp_dir:
        store = UIStateStore(Path(tmp_dir) / "ui_state.json")
        with (
            patch("src.gui.views.learning_tab_frame_v2.get_ui_state_store", return_value=store),
            patch(
                "src.gui.views.learning_tab_frame_v2.get_learning_experiments_root",
                return_value=Path(tmp_dir) / "e",
            ),
        ):
            tab = LearningTabFrame(
                tk_root, app_state=AppStateV2(), pipeline_controller=SimpleNamespace()
            )
            controller = tab.learning_controller
            from src.image_backends.forge_klein_lora import KleinLoraDecision, KleinLoraStatus
            from tests.learning_v2.test_model_comparison_140 import baseline, policy

            controller._get_baseline_config = lambda: baseline()
            controller._learning_policy_resolver = policy
            controller._learning_lora_resolver = lambda n: KleinLoraDecision(
                n, KleinLoraStatus.COMPATIBLE, "f"
            )
            assert str(tab.grid_view) not in [str(p) for p in tab.workspace_panes.panes()]
            controller.build_plan(grid_experiment(prompt="nude portrait"))
            pump(
                tk_root, lambda: str(tab.grid_view) in [str(p) for p in tab.workspace_panes.panes()]
            )
            assert str(tab.grid_view) in [str(p) for p in tab.workspace_panes.panes()]
            finish_cells(controller, tmp_path, images=1)
            plan = controller.learning_state.plan
            plan[2].status, plan[2].image_refs, plan[2].completed_images = "failed", [], 0
            controller._update_plan_table()
            tab.on_content_visibility_mode_changed("nsfw")
            tab._mode_notebook.select(1)
            tab._mode_notebook.select(0)
            pump(
                tk_root,
                lambda: tab.grid_view.model is not None
                and tab.grid_view.model.cells[2].status == "failed",
            )
            model = tab.grid_view.model
            assert (
                model.cells[2].status == "failed"
                and model.cells[2].placeholder == "Failed"
                and model.cells[2].col == 2
            )
            assert model.cells[3].job_id == "job-3" and model.cells[3].row == 1
            tab.on_content_visibility_mode_changed("sfw")
            pump(tk_root, lambda: tab.grid_view.model is not None and tab.grid_view.model.hidden)
            assert tab.grid_view.model.hidden and all(
                not cell.images for cell in tab.grid_view.model.cells
            )
            assert not tab.grid_view._cache
            controller.new_experiment_draft()
            pump(
                tk_root,
                lambda: str(tab.grid_view) not in [str(p) for p in tab.workspace_panes.panes()],
            )
            tab.destroy()


def test_design_panel_restores_a_saved_grid_with_a_range_axis_as_a_fresh_preview(
    tk_root, tmp_path, errors
):
    controller = grid_controller(grid_experiment(), build=False)
    panel = ExperimentDesignPanel(tk_root, learning_controller=controller, packs_dir=tmp_path)
    panel.study_type_var.set("Two-Axis Grid")
    panel._on_study_type_changed()
    panel.name_var.set("ranged")
    panel.prompt_source_var.set("custom")
    panel._on_prompt_source_changed()
    panel.custom_prompt_text.config(state="normal")
    panel.custom_prompt_text.delete("1.0", tk.END)
    panel.custom_prompt_text.insert("1.0", "portrait")
    panel.grid_frame.y_axis.mode_var.set("Range")
    panel.grid_frame.y_axis._sync()
    panel.grid_frame.y_axis.start_var.set("20")
    panel.grid_frame.y_axis.end_var.set("40")
    panel.grid_frame.y_axis.step_var.set("10")
    panel._on_build_preview()
    experiment = controller.learning_state.current_experiment
    assert experiment.execution_snapshot_json and str(panel.run_button.cget("state")) == "normal"

    reopened = ExperimentDesignPanel(tk_root, learning_controller=controller, packs_dir=tmp_path)
    reopened.restore_state(experiment)
    assert reopened.study_type_var.get() == "Two-Axis Grid"
    assert reopened.grid_frame.y_axis.mode_var.get() == "Range"
    assert reopened.grid_frame.spec() == panel.grid_frame.spec()
    assert str(reopened.run_button.cget("state")) == "normal"
    reopened.grid_frame.y_axis.end_var.set("30")
    assert str(reopened.run_button.cget("state")) == "disabled"


def test_export_worker_failure_always_reports_and_corrupt_grid_is_explained(
    tk_root, tmp_path, errors
):
    controller = grid_controller(grid_experiment())
    finish_cells(controller, tmp_path)
    messages = []
    shell = tk.Toplevel(tk_root)
    view = LearningGridView(
        shell,
        learning_controller=controller,
        save_dialog=lambda **_kw: str(tmp_path / "x.png"),
        notify=lambda title, text: messages.append((title, text)),
    )
    view.pack()
    view.refresh()
    assert pump(tk_root, lambda: len(view.tiles) == 9)
    with patch(
        "src.gui.views.learning_grid_view.export_contact_sheet", side_effect=KeyError("boom")
    ):
        view.export_button.invoke()
        assert pump(tk_root, lambda: bool(messages))
    assert (
        messages[0][0] == "Contact sheet not exported"
        and str(view.export_button.cget("state")) == "normal"
    )
    controller.learning_state.plan[1].param_value = dict(
        controller.learning_state.plan[1].param_value, y_value=99
    )
    view.model = None
    view._render()
    assert "cannot be shown" in view.summary_var.get()
    shell.destroy()
