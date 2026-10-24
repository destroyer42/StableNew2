from __future__ import annotations

import time
import tkinter as tk
from unittest.mock import Mock, patch

import pytest
from PIL import Image

from src.gui.views.photo_optimize_editors import pipeline_copy_dialog, review_dialog
from src.gui.views.photo_optimize_tab_frame_v2 import PhotoOptimizeTabFrameV2
from src.photo_optimize.models import PhotoOptimizeHistoryEntry
from tests.controller.test_app_controller_photo_optimize import _build_controller
from tests.photo_optimize.test_scope_editing_222 import make_photos


@pytest.fixture
def photos(tmp_path):
    return make_photos(tmp_path)


@pytest.fixture(autouse=True)
def guard_dialogs(monkeypatch):
    def unexpected(*args, **kwargs):
        raise AssertionError(f"Unexpected dialog: {args}")

    monkeypatch.setattr("src.gui.views.photo_optimize_scope.messagebox.showerror", unexpected)
    monkeypatch.setattr("src.gui.views.photo_optimize_scope.messagebox.showwarning", unexpected)
    monkeypatch.setattr("src.gui.views.photo_optimize_scope.messagebox.showinfo", Mock())


def pump(root, tab):
    until = time.monotonic() + 10
    while time.monotonic() < until:
        root.update()
        if (
            tab._operation_future is None
            and tab._operation_poll_id is None
            and tab._result_preview_poll_id is None
        ):
            root.update()
            if tab._operation_future is None and tab._result_preview_poll_id is None:
                return
        time.sleep(0.01)
    raise AssertionError("Photo worker failed to settle")


def select(tab, ids):
    tab.assets_list.selection_clear(0, "end")
    for identity in ids:
        tab.assets_list.selection_set(tab._asset_index_by_row.index(identity))
    tab._on_asset_select(None)


def test_operator_journey_batch_single_review_queue(tk_root, photos):
    store, ids = photos
    controller = _build_controller()
    tab = PhotoOptimizeTabFrameV2(tk_root, app_controller=controller, store=store)
    try:
        select(tab, ids)
        before = [store.sidecar_path(i).read_bytes() for i in ids]
        active = tab._current_asset_id
        tab.edit_workspaces.select(tab.batch_workspace)
        tk_root.update()
        assert tab._current_asset_id == active
        assert set(tab._selected_asset_ids(batch_all=False)) == set(ids)
        assert [store.sidecar_path(i).read_bytes() for i in ids] == before
        assert tab.batch_editor.mixed_labels["model"].cget("text") == "Mixed"
        tab.batch_editor.masks["stage.adetailer"].set(True)
        tab.batch_editor.values["stage.adetailer"].set("False")
        tab.batch_editor.masks["config.img2img.scheduler"].set(True)
        tab.batch_editor.values["config.img2img.scheduler"].set("karras")
        with patch("src.gui.views.photo_optimize_scope.review_dialog", return_value=False):
            tab._review_batch_edit()
            pump(tk_root, tab)
        assert [store.sidecar_path(i).read_bytes() for i in ids] == before
        with patch(
            "src.gui.views.photo_optimize_scope.review_dialog", return_value=True
        ) as confirm:
            tab._review_batch_edit()
            pump(tk_root, tab)
        assert all(i in confirm.call_args.args[2] for i in ids)
        assert all(not store.get_asset(i).baseline.stage_defaults["adetailer"] for i in ids)
        tab.edit_workspaces.select(tab.single_workspace)
        tk_root.update()
        other_before = {i: store.sidecar_path(i).read_bytes() for i in ids if i != active}
        tab.img2img_steps_var.set(29)
        assert (
            store.get_asset(active).baseline.config["img2img"]["steps"] == 20
        )  # debounced, not per keystroke
        tab._flush_baseline_now()  # what the debounce timer or FocusOut does; the write runs on the save worker
        assert store.get_asset(active).baseline.config["img2img"]["steps"] == 29
        assert {i: store.sidecar_path(i).read_bytes() for i in other_before} == other_before
        assert tab._edit_target_ids() == [active]
        controller.job_service.submit_njrs.assert_not_called()
        reviews = []

        def review(parent, title, text, **kwargs):
            controller.job_service.submit_njrs.assert_not_called()
            reviews.append(text)
            return True

        with (
            patch("src.controller.app_controller.get_photo_optimize_store", return_value=store),
            patch("src.gui.views.photo_optimize_scope.review_dialog", side_effect=review),
        ):
            tab._optimize(batch_all=False)
            pump(tk_root, tab)
        controller.job_service.submit_njrs.assert_called_once()
        assert all(i in reviews[0] for i in ids)
        jobs = controller.job_service.submit_njrs.call_args.args[0]
        assert len(jobs) == 3
        assert all(job.stage_chain[0].scheduler == "karras" for job in jobs)
        assert sum(len(job.input_image_paths) for job in jobs) == 3
    finally:
        tab.destroy()


def test_run_only_transform_is_shared_without_rewriting_saved_prompts(tk_root, photos):
    store, ids = photos
    tab = PhotoOptimizeTabFrameV2(tk_root, store=store)
    try:
        select(tab, [ids[0]])
        before = [store.sidecar_path(i).read_bytes() for i in ids]
        tab.prompt_delta_text.insert("1.0", "studio")
        select(tab, [ids[1]])
        tab.active_photo_combo.current(tab._asset_index_by_row.index(ids[1]))
        tab.active_photo_combo.event_generate("<<ComboboxSelected>>")
        tk_root.update()
        assert tab._current_asset_id == ids[1]
        assert tab._get_text(tab.prompt_delta_text) == "studio"
        tab._refresh_prompt_diff()
        assert "studio" in tab.diff_after_label.cget("text")
        assert [store.sidecar_path(i).read_bytes() for i in ids] == before
    finally:
        tab.destroy()


def test_preview_preference_and_scope_restart_do_not_change_assets(tk_root, photos):
    store, ids = photos
    active = store.list_assets()[0]
    active.history = [
        PhotoOptimizeHistoryEntry(
            "retained", "today", str(active.current_input_path), effective_prompt="portrait"
        )
    ]
    store.save_asset(active)
    before = [store.sidecar_path(i).read_bytes() for i in ids]
    tab = PhotoOptimizeTabFrameV2(tk_root, store=store)
    try:
        select(tab, ids)
        tab.show_image_previews_var.set(False)
        tab._toggle_image_previews()
        assert tab.preview_frame.winfo_manager() == "grid"
        assert tab.meta_label.winfo_manager() == "grid"
        assert tab.meta_label.cget("text").startswith("Asset:")
        assert tab.history_list.winfo_manager() == "grid"
        assert tab.history_list.size() == 3  # original, working, retained empty history entry
        assert tab.image_previews_frame.winfo_manager() == ""
        tab.edit_workspaces.select(tab.batch_workspace)
        tk_root.update()
        state = tab.get_photo_optimize_state()
    finally:
        tab.destroy()
    restarted = PhotoOptimizeTabFrameV2(tk_root, store=store)
    try:
        assert restarted.restore_photo_optimize_state(state)
        tk_root.update()
        assert restarted.show_image_previews_var.get() is False
        assert restarted.preview_frame.winfo_manager() == "grid"
        assert restarted.meta_label.winfo_manager() == "grid"
        assert restarted.meta_label.cget("text").startswith("Asset:")
        assert restarted.history_list.winfo_manager() == "grid"
        assert restarted.history_list.size() == 3
        assert restarted.image_previews_frame.winfo_manager() == ""
        assert restarted.edit_scope_var.get() == "Batch Edit"
        assert set(restarted._selected_asset_ids(batch_all=False)) == set(ids)
        assert [store.sidecar_path(i).read_bytes() for i in ids] == before
        asset = store.get_asset(ids[0])
        asset.baseline.prompt = "nsfw"
        store.save_asset(asset)
        restarted._show_asset(ids[0])
        with patch.object(restarted.original_preview, "set_image") as load:
            restarted.show_image_previews_var.set(True)
            restarted.on_content_visibility_mode_changed("sfw")
            pump(tk_root, restarted)
            load.assert_not_called()
        assert restarted.image_previews_frame.winfo_manager() == "grid"
        assert restarted.preview_frame.winfo_manager() == "grid"
    finally:
        restarted.destroy()


@pytest.mark.parametrize("batch_selection", ["all", "others", "one", "empty"])
def test_explicit_active_photo_preserves_batch_across_scope_refresh_restart(
    tk_root, photos, batch_selection
):
    store, _ = photos
    tab = PhotoOptimizeTabFrameV2(tk_root, store=store)
    ids = list(tab._asset_index_by_row)
    active = ids[1]
    selected = {"all": ids, "others": [ids[0], ids[2]], "one": [ids[0]], "empty": []}[
        batch_selection
    ]
    before = {i: store.sidecar_path(i).read_bytes() for i in ids}
    try:
        select(tab, selected)
        assert tab._current_asset_id == ids[0]
        tab._show_asset(active)
        tab._on_asset_select(None)
        assert tab._current_asset_id == active  # reviewed head resets this to first highlighted A
        tab._show_asset(ids[0])
        tab.active_photo_combo.current(tab._asset_index_by_row.index(active))
        tab.active_photo_combo.event_generate("<<ComboboxSelected>>")
        tk_root.update()
        assert tab._current_asset_id == active
        assert set(tab._selected_asset_ids(batch_all=False)) == set(selected)
        # A selection notification must not reset an explicitly chosen active editor to A.
        tab._on_asset_select(None)
        for workspace in (tab.batch_workspace, tab.single_workspace):
            tab.edit_workspaces.select(workspace)
            tk_root.update()
            assert tab._current_asset_id == active
            assert set(tab._selected_asset_ids(batch_all=False)) == set(selected)
        tab._refresh_assets()
        assert tab._current_asset_id == active
        assert tab.active_photo_combo.current() == tab._asset_index_by_row.index(active)
        assert set(tab._selected_asset_ids(batch_all=False)) == set(selected)
        assert {i: store.sidecar_path(i).read_bytes() for i in ids} == before
        state = tab.get_photo_optimize_state()
    finally:
        tab.destroy()
    restarted = PhotoOptimizeTabFrameV2(tk_root, store=store)
    try:
        assert restarted.restore_photo_optimize_state(state)
        tk_root.update()
        assert restarted._current_asset_id == active
        assert restarted.active_photo_combo.current() == restarted._asset_index_by_row.index(active)
        assert set(restarted._selected_asset_ids(batch_all=False)) == set(selected)
        assert {i: store.sidecar_path(i).read_bytes() for i in ids} == before
        restarted.img2img_steps_var.set(29)
        restarted._flush_baseline_now()
        assert store.get_asset(active).baseline.config["img2img"]["steps"] == 29
        assert {i: store.sidecar_path(i).read_bytes() for i in ids if i != active} == {
            i: value for i, value in before.items() if i != active
        }
        assert set(restarted._selected_asset_ids(batch_all=False)) == set(selected)
    finally:
        restarted.destroy()


def test_pipeline_copy_dialog_can_select_exactly_one_field(tk_root, photos):
    store, _ = photos
    tab = PhotoOptimizeTabFrameV2(tk_root, store=store)
    callback = Mock()
    snapshot = {
        "model": "live",
        "config": {"img2img": {"scheduler": "karras"}},
        "stage_defaults": {},
    }
    try:
        pipeline_copy_dialog(tab, snapshot, "Single Photo", callback)
        window = next(w for w in tab.winfo_children() if isinstance(w, tk.Toplevel))

        def descendants(widget):
            for child in widget.winfo_children():
                yield child
                yield from descendants(child)

        widgets = list(descendants(window))
        next(
            w
            for w in widgets
            if w.winfo_class() == "TCheckbutton" and w.cget("text") == "config.img2img.scheduler"
        ).invoke()
        next(
            w for w in widgets if w.winfo_class() == "TButton" and w.cget("text") == "Review copy…"
        ).invoke()
        callback.assert_called_once_with({"config.img2img.scheduler": "karras"})
    finally:
        tab.destroy()


def test_history_previews_use_effective_prompts_and_selected_entry(tk_root, photos):
    store, ids = photos
    asset = store.get_asset(ids[0])
    safe = store.outputs_dir(asset.asset_id) / "safe-output.png"
    flagged = store.outputs_dir(asset.asset_id) / "output.png"
    Image.new("RGB", (16, 16), "blue").save(safe)
    Image.new("RGB", (16, 16), "red").save(flagged)
    asset.history = [
        PhotoOptimizeHistoryEntry(
            "safe",
            "today",
            str(asset.current_input_path),
            output_paths=[str(safe)],
            effective_prompt="landscape",
        ),
        PhotoOptimizeHistoryEntry(
            "flagged",
            "today",
            str(asset.current_input_path),
            output_paths=[str(flagged)],
            effective_prompt="nude portrait",
        ),
    ]
    store.save_asset(asset)
    before = store.sidecar_path(ids[0]).read_bytes()
    tab = PhotoOptimizeTabFrameV2(tk_root, store=store)
    try:
        select(tab, [ids[0]])
        tab.active_photo_combo.current(tab._asset_index_by_row.index(ids[0]))
        tab.active_photo_combo.event_generate("<<ComboboxSelected>>")
        tk_root.update()
        assert tab._current_asset_id == ids[0]
        with (
            patch.object(tab.latest_preview, "set_image") as load,
            patch.object(tab.latest_preview, "clear") as clear,
        ):

            def select_history(index):
                row = next(
                    i
                    for i, c in enumerate(tab._result_candidates)
                    if c.kind == "history" and c.history_index == index
                )
                tab.history_list.selection_clear(0, "end")
                tab.history_list.selection_set(row)

            select_history(1)
            tab.on_content_visibility_mode_changed("sfw")
            pump(tk_root, tab)
            load.assert_not_called()
            clear.assert_called()
            tab.show_image_previews_var.set(False)
            tab._toggle_image_previews()
            tab.show_image_previews_var.set(True)
            tab._toggle_image_previews()
            pump(tk_root, tab)
            load.assert_not_called()
            # Selecting the safe entry permits only its validated output.
            select_history(0)
            tab._on_history_select(None)
            pump(tk_root, tab)
            load.assert_called_once()
            assert load.call_args.args[0].getpixel((0, 0)) == (0, 0, 255)
            load.reset_mock()
            tab.show_image_previews_var.set(False)
            tab._toggle_image_previews()
            load.assert_not_called()
            tab.show_image_previews_var.set(True)
            tab._toggle_image_previews()
            pump(tk_root, tab)
            load.assert_called_once()
            assert load.call_args.args[0].getpixel((0, 0)) == (0, 0, 255)
            load.reset_mock()
            select_history(1)
            tab._on_history_select(None)
            pump(tk_root, tab)
            load.assert_not_called()
        assert store.sidecar_path(ids[0]).read_bytes() == before
    finally:
        tab.destroy()


def test_review_dialog_displays_full_selection_and_cancel(tk_root):
    text = "photo-a\n" + "x" * 20000 + "\nphoto-b\nphoto-c"

    def inspect_and_cancel():
        window = next(w for w in tk_root.winfo_children() if isinstance(w, tk.Toplevel))
        body = next(w for w in window.winfo_children() if isinstance(w, tk.Text))
        assert body.get("1.0", "end-1c") == text
        window.destroy()

    tk_root.after(20, inspect_and_cancel)
    assert review_dialog(tk_root, "Review", text) is False


@pytest.mark.parametrize("scope", ["Single Photo", "Batch Edit"])
def test_live_pipeline_copy_applies_only_scoped_ids_and_checked_field(tk_root, photos, scope):
    store, ids = photos
    controller = _build_controller()
    controller.build_photo_optimize_defaults = Mock(
        return_value={
            "config": {"img2img": {"scheduler": "uniform", "steps": 41}},
            "stage_defaults": {},
            "model": "live-model",
        }
    )
    tab = PhotoOptimizeTabFrameV2(tk_root, app_controller=controller, store=store)
    try:
        select(tab, ids)
        active = tab._current_asset_id
        tab.edit_workspaces.select(
            tab.single_workspace if scope == "Single Photo" else tab.batch_workspace
        )
        tk_root.update()
        before = {i: store.get_asset(i).to_dict() for i in ids}
        with (
            patch(
                "src.gui.views.photo_optimize_scope.pipeline_copy_dialog",
                side_effect=lambda parent, snapshot, label, callback: callback(
                    {"config.img2img.scheduler": snapshot["config"]["img2img"]["scheduler"]}
                ),
            ),
            patch("src.gui.views.photo_optimize_scope.review_dialog", return_value=True),
        ):
            tab._use_current_pipeline_settings()
            pump(tk_root, tab)
        targets = ids if scope == "Batch Edit" else [active]
        for identity in ids:
            after = store.get_asset(identity).to_dict()
            expected = before[identity]
            if identity in targets:
                expected["baseline"]["config"]["img2img"]["scheduler"] = "uniform"
                expected["baseline"]["config"]["img2img_scheduler"] = "uniform"
                expected["baseline"]["config"]["scheduler"] = "uniform"
            assert after == expected
        controller.job_service.submit_njrs.assert_not_called()
    finally:
        tab.destroy()


def test_all_visible_excludes_archived_and_selected_archived_refuses(tk_root, photos):
    store, ids = photos
    store.archive_assets([ids[1]])
    controller = _build_controller()
    tab = PhotoOptimizeTabFrameV2(tk_root, app_controller=controller, store=store)
    try:
        tab.show_archived_var.set(True)
        tab._refresh_assets()
        select(tab, [ids[0]])
        with (
            patch("src.controller.app_controller.get_photo_optimize_store", return_value=store),
            patch("src.gui.views.photo_optimize_scope.review_dialog", return_value=True),
        ):
            tab._optimize(batch_all=True)
            pump(tk_root, tab)
        assert len(controller.job_service.submit_njrs.call_args.args[0]) == 2
        controller.job_service.submit_njrs.reset_mock()
        select(tab, [ids[1]])
        with (
            patch("src.controller.app_controller.get_photo_optimize_store", return_value=store),
            patch("src.gui.views.photo_optimize_tab_frame_v2.messagebox.showerror") as error,
        ):
            tab._optimize(batch_all=False)
            pump(tk_root, tab)
        controller.job_service.submit_njrs.assert_not_called()
        assert "archived" in error.call_args.args[1].lower()
    finally:
        tab.destroy()
