from __future__ import annotations

import json
import time
from unittest.mock import Mock, patch

import pytest

from src.gui.views.photo_optimize_tab_frame_v2 import PhotoOptimizeTabFrameV2
from tests.controller.test_app_controller_photo_optimize import _build_controller
from tests.photo_optimize.test_historical_results_223 import make_library


@pytest.fixture
def library(tmp_path):
    return make_library(tmp_path)


def settle(root, tab):
    deadline = time.monotonic() + 10
    while time.monotonic() < deadline:
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
    raise AssertionError("Photo result GUI workers did not settle")


def choose(root, tab, *, kind="history", history_index=0, output_index=1):
    row = next(
        i
        for i, c in enumerate(tab._result_candidates)
        if c.kind == kind
        and (
            kind != "history" or (c.history_index, c.output_index) == (history_index, output_index)
        )
    )
    tab.history_list.selection_clear(0, "end")
    tab.history_list.selection_set(row)
    tab._on_history_select(None)
    settle(root, tab)
    return tab._result_candidates[row]


def test_browse_every_output_cancel_confirm_restore_and_queue(tk_root, library):
    store, asset = library
    controller = _build_controller()
    tab = PhotoOptimizeTabFrameV2(tk_root, store=store, app_controller=controller)
    try:
        settle(tk_root, tab)
        assert len(tab._result_candidates) == 5  # original, working, one latest, two older
        before = store.sidecar_path(asset.asset_id).read_bytes()
        candidate = choose(tk_root, tab)
        assert store.sidecar_path(asset.asset_id).read_bytes() == before
        assert "older" in tab.result_status_var.get()
        tab.promotion_mode_var.set("recorded")
        with patch("src.gui.views.photo_optimize_results.review_dialog", return_value=False):
            tab._promote_selected_result()
            settle(tk_root, tab)
        assert store.sidecar_path(asset.asset_id).read_bytes() == before
        with (
            patch(
                "src.gui.views.photo_optimize_results.review_dialog", return_value=True
            ) as review,
            patch("src.gui.views.photo_optimize_results.messagebox.showinfo"),
        ):
            tab._promote_selected_result()
            settle(tk_root, tab)
        assert "Before:" in review.call_args.args[2] and "After:" in review.call_args.args[2]
        assert candidate.path in review.call_args.args[2] and "older" in review.call_args.args[2]
        updated = store.get_asset(asset.asset_id)
        assert updated.baseline.working_image_path == candidate.path
        assert updated.baseline.prompt == "portrait older"
        with (
            patch("src.controller.app_controller.get_photo_optimize_store", return_value=store),
            patch("src.gui.views.photo_optimize_scope.review_dialog", return_value=True),
            patch("src.gui.views.photo_optimize_scope.messagebox.showinfo"),
        ):
            tab._optimize(batch_all=False)
            settle(tk_root, tab)
        jobs = controller.job_service.submit_njrs.call_args.args[0]
        assert tuple(jobs[0].input_image_paths) == (candidate.path,)
        with patch("src.gui.views.photo_optimize_results.messagebox.showinfo"):
            tab._revert_baseline()
            settle(tk_root, tab)
        assert (
            store.get_asset(asset.asset_id).baseline.working_image_path
            == asset.baseline.working_image_path
        )
    finally:
        tab.destroy()


def test_preview_missing_and_flagged_results_keeps_metadata_history(tk_root, library):
    store, asset = library
    asset.history[0].effective_prompt = "nude portrait"
    store.save_asset(asset)
    tab = PhotoOptimizeTabFrameV2(tk_root, store=store)
    try:
        tab.on_content_visibility_mode_changed("sfw")
        settle(tk_root, tab)
        with patch.object(tab.latest_preview, "set_image", Mock()) as load:
            choose(tk_root, tab)
            load.assert_not_called()
            tab.show_image_previews_var.set(False)
            tab._toggle_image_previews()
            settle(tk_root, tab)
            assert tab.meta_label.winfo_manager() == "grid"
            assert tab.history_list.size() == 5
            tab.show_image_previews_var.set(True)
            tab._toggle_image_previews()
            settle(tk_root, tab)
            load.assert_not_called()
        from pathlib import Path

        Path(asset.history[1].output_paths[0]).unlink()  # disposable fixture only
        tab.on_content_visibility_mode_changed("nsfw")
        choose(tk_root, tab, history_index=1, output_index=0)
        assert "missing" in tab.result_status_var.get().lower()
        assert (
            store.get_asset(asset.asset_id).baseline.working_image_path
            == asset.baseline.working_image_path
        )
    finally:
        tab.destroy()


def test_legacy_asset_filename_still_gates_working_and_history_previews(tk_root, library):
    store, asset = library
    asset.source_filename = "nsfw.png"
    asset.original_baseline = None
    asset.baseline.working_image_path = asset.history[0].output_paths[0]
    store.save_asset(asset)
    sidecar = store.sidecar_path(asset.asset_id)
    legacy_payload = json.loads(sidecar.read_text(encoding="utf-8"))
    legacy_payload.pop("original_baseline", None)
    sidecar.write_text(json.dumps(legacy_payload), encoding="utf-8")
    tab = PhotoOptimizeTabFrameV2(tk_root, store=store)
    try:
        with patch.object(tab.latest_preview, "set_image") as load:
            tab.on_content_visibility_mode_changed("sfw")
            settle(tk_root, tab)
            load.assert_not_called()
            choose(tk_root, tab)
            load.assert_not_called()
    finally:
        tab.destroy()
