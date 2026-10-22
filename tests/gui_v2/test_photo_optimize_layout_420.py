"""Photo Optimize reachability and responsive structure in real Tk (PR-GUI-420).

Tk geometry is measured, not assumed: each case builds the real tab at a tab-viewport size and font scaling that
stand in for a Windows window (shell chrome already subtracted), lets geometry settle and asserts bounding boxes.
This is a partial substitute for manual Windows screenshots; it does not prove DPI-aware rendering of the real shell.
"""

from __future__ import annotations

import time
import tkinter as tk
from pathlib import Path
from tkinter import ttk
from unittest.mock import Mock, patch

import pytest
from PIL import Image

from src.gui.theme_v2 import apply_theme
from src.gui.view_contracts.photo_optimize_layout_contract import (
    BODY_SPLIT,
    BODY_STACKED,
    BODY_WIDE,
    PREVIEW_MIN_EDGE,
)
from src.gui.views.photo_optimize_tab_frame_v2 import PhotoOptimizeTabFrameV2
from src.photo_optimize.store import PhotoOptimizeStore
from src.photo_optimize.submission import prepare_photo_plan

PX = 96 / 72
# (tab viewport width, height, tk scaling). The viewport is the 1366x768 / 1920x1080 window minus shell chrome.
CASES = {
    "1366x768@100": (1350, 538, PX),
    "1366x768@150": (1350, 538, PX * 1.5),
    "1920x1080@100": (1904, 850, PX),
    "1920x1080@150": (1904, 850, PX * 1.5),
}
NARROW = (760, 538, PX * 1.5)


@pytest.fixture(autouse=True)
def unexpected_dialogs_fail(monkeypatch):
    def unexpected(*args, **kwargs):
        raise AssertionError(f"Unexpected GUI dialog: {args}")

    monkeypatch.setattr("src.gui.views.photo_optimize_scope.messagebox.showerror", unexpected)
    monkeypatch.setattr("src.gui.views.photo_optimize_scope.messagebox.showwarning", unexpected)


def _pump(root: tk.Misc, ms: int = 200) -> None:
    deadline = time.monotonic() + ms / 1000
    root.update_idletasks()
    while time.monotonic() < deadline:
        root.update()
        time.sleep(0.01)


def _store(tmp_path: Path, count: int = 3) -> tuple[PhotoOptimizeStore, list]:
    store = PhotoOptimizeStore(tmp_path / "photo_optimize")
    assets = []
    for index in range(count):
        path = tmp_path / "source" / f"photo_{index}.png"
        path.parent.mkdir(parents=True, exist_ok=True)
        Image.new("RGB", (64, 48), (30 * index, 90, 150)).save(path)
        assets.append(store.import_photo(path))
    return store, assets


def _make_tab(root: tk.Tk, store, viewport, *, controller=None) -> PhotoOptimizeTabFrameV2:
    width, height, scaling = viewport
    root.tk.call("tk", "scaling", scaling)
    apply_theme(root)
    root.geometry(f"{width}x{height + 40}+0+0")
    root.deiconify()  # a withdrawn root is never given real geometry
    root.rowconfigure(0, weight=1)
    root.columnconfigure(0, weight=1)
    tab = PhotoOptimizeTabFrameV2(root, app_controller=controller, store=store)
    tab.grid(row=0, column=0, sticky="nw")
    tab.configure(width=width, height=height)
    tab.grid_propagate(False)
    deadline = time.monotonic() + 3
    while time.monotonic() < deadline and tab.winfo_width() <= 1:
        root.update()
        time.sleep(0.01)
    _pump(root)
    return tab


def _resize(root: tk.Tk, tab, width: int, height: int) -> None:
    tab.configure(width=width, height=height)
    _pump(root)


def _rect(widget: tk.Misc, origin: tk.Misc) -> tuple[int, int, int, int]:
    return (
        widget.winfo_rootx() - origin.winfo_rootx(),
        widget.winfo_rooty() - origin.winfo_rooty(),
        widget.winfo_width(),
        widget.winfo_height(),
    )


def _inside_width(widget: tk.Misc, origin: tk.Misc, limit: int) -> bool:
    x, _y, w, _h = _rect(widget, origin)
    return w > 1 and x >= 0 and x + w <= limit


def _char(tab) -> int:
    return tab._layout_char_width()


def _expand_more(root, tab) -> None:
    if not tab.header_more_var.get():
        tab.header_more_btn.invoke()
    _pump(root)


# -- header --------------------------------------------------------------------------------------------------------


@pytest.mark.parametrize("case", CASES)
def test_primary_actions_and_status_stay_inside_the_tab(tk_root, tmp_path, case) -> None:
    store, _ = _store(tmp_path)
    tab = _make_tab(tk_root, store, CASES[case])
    try:
        width = tab.winfo_width()
        primary = (
            tab.import_photos_btn,
            tab.optimize_selected_header_btn,
            tab.optimize_all_header_btn,
            tab.selection_label,
            tab.header_more_btn,
        )
        for widget in primary:
            assert _inside_width(widget, tab, width), (case, str(widget), _rect(widget, tab))
        header = tab.header_frame
        assert header.winfo_height() <= tab.winfo_height() * 0.45, (
            "header must leave the body usable"
        )
        assert tab.optimize_selected_header_btn.cget("style") == "Primary.TButton"
    finally:
        tab.destroy()


@pytest.mark.parametrize("case", CASES)
def test_secondary_actions_are_reachable_in_a_labelled_section(tk_root, tmp_path, case) -> None:
    store, _ = _store(tmp_path)
    tab = _make_tab(tk_root, store, CASES[case])
    try:
        assert tab.header_more_var.get() is False and tab.header_secondary.winfo_manager() == ""
        _expand_more(tk_root, tab)
        width = tab.winfo_width()
        assert "More actions" in str(tab.header_secondary.cget("text"))
        for widget in (
            tab.refresh_btn,
            tab.pipeline_copy_btn,
            tab.interrogate_btn,
            tab.batch_size_spin,
            tab.migration_details_btn,
            tab.retry_migration_btn,
        ):
            assert _inside_width(widget, tab, width), (case, str(widget), _rect(widget, tab))
        assert tab.header_frame.winfo_height() <= tab.winfo_height() * 0.6
    finally:
        tab.destroy()


def test_review_buttons_keep_review_wording(tk_root, tmp_path) -> None:
    store, _ = _store(tmp_path)
    tab = _make_tab(tk_root, store, CASES["1366x768@100"])
    try:
        for button in (tab.optimize_selected_header_btn, tab.optimize_all_header_btn):
            text = str(button.cget("text"))
            assert text.startswith("Review") and "Queue" not in text and "Generate" not in text
        assert "Review Pipeline Copy" in str(tab.pipeline_copy_btn.cget("text"))
    finally:
        tab.destroy()


@pytest.mark.parametrize("case", ["1366x768@150", "1366x768@100"])
def test_long_errors_wrap_inside_the_tab_and_failed_migration_opens_actions(
    tk_root, tmp_path, case
) -> None:
    store, _ = _store(tmp_path)
    tab = _make_tab(tk_root, store, CASES[case])
    try:
        tab.submission_summary_var.set("Queue validation failed: " + "stage config invalid; " * 25)
        tab.migration_status_var.set(
            "Legacy migration incomplete: 1 migrated, 0 already verified, 2 failed/skipped. " * 3
        )
        _pump(tk_root)
        header_width = tab.header_frame.winfo_width()
        for label in tab.header_status_labels:
            assert label.winfo_reqwidth() <= header_width, (
                str(label),
                label.winfo_reqwidth(),
                header_width,
            )
            assert int(label.cget("wraplength")) <= header_width
        assert tab.header_more_var.get(), "an incomplete migration must expose Retry/Details"
        assert _inside_width(tab.retry_migration_btn, tab, tab.winfo_width())
        assert "Queue validation failed" in tab.submission_summary_var.get()
    finally:
        tab.destroy()


def test_selection_summary_names_single_photo_and_batch(tk_root, tmp_path) -> None:
    store, assets = _store(tmp_path)
    tab = _make_tab(tk_root, store, CASES["1366x768@100"])
    try:
        tab.assets_list.selection_clear(0, tk.END)
        for row in (0, 2):
            tab.assets_list.selection_set(row)
        tab._show_asset(assets[1].asset_id)
        text = str(tab.selection_label.cget("text"))
        assert "Single Photo: photo_1.png" in text
        assert "Batch: 2 selected" in text
        assert "3 visible" in text
    finally:
        tab.destroy()


# -- body ----------------------------------------------------------------------------------------------------------


def _assert_body_structure(tab, mode: str) -> None:
    body = tab.body_scroll.inner
    canvas_width = tab.body_scroll.viewport_width()
    regions = {
        "assets": tab.assets_frame,
        "preview": tab.preview_frame,
        "editor": tab.controls_frame,
    }
    rects = {name: _rect(widget, body) for name, widget in regions.items()}
    for name, (x, _y, w, _h) in rects.items():
        assert x >= 0 and x + w <= canvas_width, (mode, name, rects[name], canvas_width)
    assets, preview, editor = rects["assets"], rects["preview"], rects["editor"]
    if mode == BODY_WIDE:
        assert assets[0] + assets[2] <= preview[0] and preview[0] + preview[2] <= editor[0]
        assert abs(assets[1] - preview[1]) < 4 and abs(preview[1] - editor[1]) < 4
    elif mode == BODY_SPLIT:
        assert preview[1] >= assets[1] + assets[3]
        assert editor[0] >= max(assets[0] + assets[2], preview[0] + preview[2])
    else:
        assert assets[1] + assets[3] <= preview[1] and preview[1] + preview[3] <= editor[1]
    # Regions are never stretched to the tallest sibling: that pushed the list actions ~2000px down.
    assert tab.assets_frame.winfo_height() <= tab.assets_frame.winfo_reqheight() + 2
    assert tab.preview_frame.winfo_height() <= tab.preview_frame.winfo_reqheight() + 2


def _assert_controls_usable(tab) -> None:
    char = _char(tab)
    canvas_width = tab.body_scroll.viewport_width()
    body = tab.body_scroll.inner
    for name in (
        "assets_list",
        "active_photo_combo",
        "original_preview",
        "latest_preview",
        "edit_workspaces",
        "model_combo",
        "vae_combo",
        "baseline_prompt_text",
        "baseline_negative_text",
        "prompt_delta_text",
        "history_list",
    ):
        widget = getattr(tab, name)
        assert _inside_width(widget, body, canvas_width), (name, _rect(widget, body), canvas_width)
    assert tab.baseline_prompt_text.winfo_width() >= 20 * char
    assert tab.model_combo.winfo_width() >= 10 * char
    assert tab.assets_list.winfo_width() >= 14 * char
    for preview in (tab.original_preview, tab.latest_preview):
        assert preview.fitted_edge() >= PREVIEW_MIN_EDGE
        assert preview.winfo_width() >= PREVIEW_MIN_EDGE
    # Every body control can be scrolled to: the scroll region covers the whole inner frame.
    first, last = tab.body_scroll._canvas.yview()
    assert first == 0.0
    region = [int(v) for v in str(tab.body_scroll._canvas.cget("scrollregion")).split()]
    assert region[3] >= body.winfo_reqheight() - 2


@pytest.mark.parametrize("case", CASES)
def test_body_regions_fit_and_controls_are_usable(tk_root, tmp_path, case) -> None:
    store, assets = _store(tmp_path)
    tab = _make_tab(tk_root, store, CASES[case])
    try:
        tab._show_asset(assets[0].asset_id)
        _pump(tk_root)
        _assert_body_structure(tab, tab.body_mode)
        _assert_controls_usable(tab)
        if case.startswith("1920"):
            assert tab.body_mode == BODY_WIDE, (
                "source, previews and editor sit side by side when they fit"
            )
    finally:
        tab.destroy()


def test_batch_edit_workspace_is_usable_at_compact_width(tk_root, tmp_path) -> None:
    store, assets = _store(tmp_path)
    tab = _make_tab(tk_root, store, CASES["1366x768@150"])
    try:
        tab.edit_workspaces.select(tab.batch_workspace)
        tab.assets_list.selection_set(0, 1)
        tab._on_workspace_changed()
        _pump(tk_root)
        editor = tab.batch_editor
        width = tab.controls_frame.winfo_width()
        assert _inside_width(editor.review_button, tab.controls_frame, width)
        for key, combo in editor.combos.items():
            assert _inside_width(combo, tab.controls_frame, width), key
            assert combo.winfo_width() >= 10 * _char(tab), key
        for label in editor.wrapped_labels:
            assert int(label.cget("wraplength")) <= width
        assert "2 selected" in editor.summary.get()
    finally:
        tab.destroy()


def test_narrow_tab_stacks_with_headings_instead_of_clipping(tk_root, tmp_path) -> None:
    store, assets = _store(tmp_path)
    tab = _make_tab(tk_root, store, NARROW)
    try:
        assert tab.body_mode == BODY_STACKED
        _assert_body_structure(tab, BODY_STACKED)
        _assert_controls_usable(tab)
        for frame, heading in (
            (tab.assets_frame, "Assets"),
            (tab.preview_frame, "Preview"),
        ):
            assert heading in str(frame.cget("text"))
        for widget in (
            tab.import_photos_btn,
            tab.optimize_selected_header_btn,
            tab.optimize_all_header_btn,
            tab.header_more_btn,
        ):
            assert _inside_width(widget, tab, tab.winfo_width())
    finally:
        tab.destroy()


# -- state preservation --------------------------------------------------------------------------------------------


def test_resize_round_trip_keeps_selection_text_and_widgets(tk_root, tmp_path) -> None:
    store, assets = _store(tmp_path)
    tab = _make_tab(tk_root, store, CASES["1920x1080@100"])
    try:
        assert tab.body_mode == BODY_WIDE
        rows = tab._asset_index_by_row
        tab.assets_list.selection_clear(0, tk.END)
        for row in (0, 2):
            tab.assets_list.selection_set(row)
        tab.active_photo_combo.current(1)
        tab._on_active_photo_choice(None)
        active_id = rows[1]
        tab.prompt_delta_text.insert("1.0", "run only text")
        tab.tags_var.set("kept")
        sidecar = store.sidecar_path(active_id).read_bytes()
        selected_before = tab._selected_asset_ids(batch_all=False)
        assert selected_before == [rows[0], rows[2]]
        parents = {w: w.master for w in (tab.assets_frame, tab.preview_frame, tab.controls_frame)}
        widgets = (tab.assets_list, tab.original_preview, tab.edit_workspaces, tab.model_combo)

        modes = []
        for width in (NARROW[0], CASES["1366x768@150"][0], CASES["1920x1080@100"][0]):
            _resize(tk_root, tab, width, 538)
            modes.append(tab.body_mode)
            assert tab._selected_asset_ids(batch_all=False) == selected_before
            assert tab._current_asset_id == active_id
            assert tab.prompt_delta_text.get("1.0", "end").strip() == "run only text"
            assert tab.tags_var.get() == "kept"
        assert modes[0] == BODY_STACKED and modes[-1] == BODY_WIDE
        assert len(set(modes)) >= 2
        assert {w: w.master for w in parents} == parents, (
            "regions must be re-gridded, never reparented"
        )
        assert (
            tab.assets_list,
            tab.original_preview,
            tab.edit_workspaces,
            tab.model_combo,
        ) == widgets
        assert store.sidecar_path(active_id).read_bytes() == sidecar, (
            "layout must not write baselines"
        )
    finally:
        tab.destroy()


def test_choosing_active_photo_does_not_change_batch_selection(tk_root, tmp_path) -> None:
    store, assets = _store(tmp_path)
    tab = _make_tab(tk_root, store, CASES["1366x768@100"])
    try:
        tab.assets_list.selection_clear(0, tk.END)
        tab.assets_list.selection_set(0, 1)
        before = tab._selected_asset_ids(batch_all=False)
        tab.active_photo_combo.current(2)
        tab._on_active_photo_choice(None)
        _resize(tk_root, tab, NARROW[0], 538)
        assert tab._selected_asset_ids(batch_all=False) == before
        assert tab._current_asset_id == tab._asset_index_by_row[2]
    finally:
        tab.destroy()


def test_archive_restore_and_toggles_survive_layout_changes(tk_root, tmp_path) -> None:
    store, assets = _store(tmp_path)
    tab = _make_tab(tk_root, store, CASES["1366x768@150"])
    try:
        target = tab._asset_index_by_row[0]
        tab.assets_list.selection_clear(0, tk.END)
        tab.assets_list.selection_set(0)
        tab._archive_assets(clear_all=False)
        _resize(tk_root, tab, NARROW[0], 538)
        assert target not in tab._asset_index_by_row
        tab.show_archived_var.set(True)
        tab._refresh_assets()
        assert target in tab._asset_index_by_row
        tab.assets_list.selection_clear(0, tk.END)
        tab.assets_list.selection_set(tab._asset_index_by_row.index(target))
        tab._restore_assets()
        tab.show_image_previews_var.set(False)
        tab._toggle_image_previews()
        assert not tab.image_previews_frame.winfo_manager()
        tab.show_image_previews_var.set(True)
        tab._toggle_image_previews()
        assert tab.image_previews_frame.winfo_manager() == "grid"
        assert not store.get_asset(target).archived
    finally:
        tab.destroy()


def test_state_survives_switching_to_another_notebook_tab_and_back(tk_root, tmp_path) -> None:
    store, assets = _store(tmp_path)
    tk_root.tk.call("tk", "scaling", CASES["1366x768@100"][2])
    apply_theme(tk_root)
    tk_root.geometry("1366x640+0+0")
    tk_root.deiconify()
    notebook = ttk.Notebook(tk_root)
    notebook.pack(fill="both", expand=True)
    tab = PhotoOptimizeTabFrameV2(notebook, store=store)
    other = ttk.Frame(notebook)
    notebook.add(tab, text="Photo Optimize")
    notebook.add(other, text="Other")
    try:
        _pump(tk_root)
        tab.assets_list.selection_set(0, 1)
        tab._show_asset(assets[1].asset_id)
        tab.edit_workspaces.select(tab.batch_workspace)
        tab._on_workspace_changed()
        state = tab.get_photo_optimize_state()
        notebook.select(other)
        _pump(tk_root)
        notebook.select(tab)
        _pump(tk_root)
        assert tab.get_photo_optimize_state() == state
        assert state["editing_scope"] == "Batch Edit"
        assert tab.body_mode in {BODY_WIDE, BODY_SPLIT}
    finally:
        tab.destroy()


# -- submission ----------------------------------------------------------------------------------------------------


@pytest.mark.parametrize("viewport", [CASES["1366x768@150"], NARROW, CASES["1920x1080@100"]])
def test_review_buttons_reach_the_one_review_and_submit_path(tk_root, tmp_path, viewport) -> None:
    store, assets = _store(tmp_path)
    controller = Mock()
    controller.build_photo_optimize_defaults.return_value = {"config": {"img2img": {}}}
    plans = []

    def prepare(**kwargs):
        plan = prepare_photo_plan(
            assets=[store.get_asset(row["asset_id"]).to_dict() for row in kwargs["assets"]],
            stages=kwargs["stages"],
            fallback_config={"img2img": {}},
            store=store,
            batch_size=1,
        )
        plans.append((len(kwargs["assets"]), plan))
        return plan

    controller.prepare_photo_optimize_plan.side_effect = prepare
    controller.submit_prepared_photo_plan.side_effect = lambda plan: len(plan.jobs)
    tab = _make_tab(tk_root, store, viewport, controller=controller)
    try:
        tab.assets_list.selection_clear(0, tk.END)
        tab.assets_list.selection_set(1)
        tab._show_asset(assets[1].asset_id)
        tab._run_photo_operation = lambda operation, completed: completed(operation())
        tab.after_idle = lambda callback: callback()
        with (
            patch("src.gui.views.photo_optimize_tab_frame_v2.messagebox.showinfo"),
            patch("src.gui.views.photo_optimize_scope.messagebox.showinfo"),
            patch("src.gui.views.photo_optimize_scope.review_dialog", return_value=True),
        ):
            tab.optimize_selected_header_btn.invoke()
            tab.optimize_all_header_btn.invoke()
        assert [count for count, _plan in plans] == [1, 3]
        assert controller.prepare_photo_optimize_plan.call_count == 2
        submitted = [call.args[0] for call in controller.submit_prepared_photo_plan.call_args_list]
        assert submitted == [plan for _count, plan in plans]
        assert len(plans[0][1].jobs) == 1, "one chosen photo stays one source"
    finally:
        tab.destroy()


def test_body_scroll_keeps_the_shared_wheel_router(tk_root, tmp_path) -> None:
    store, _ = _store(tmp_path)
    tab = _make_tab(tk_root, store, CASES["1366x768@100"])
    try:
        assert tab.body_scroll._wheel_router.installed
        assert tab.body_scroll in tab.body_scroll._wheel_router._frames
        # Text/listbox widgets keep their own wheel behaviour: they must stay such widgets, not frames.
        assert (
            tab.assets_list.winfo_class() == "Listbox"
            and tab.baseline_prompt_text.winfo_class() == "Text"
        )
    finally:
        tab.destroy()
