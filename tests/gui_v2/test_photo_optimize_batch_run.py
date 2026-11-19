"""Photo Optimize batch runs and the active photo, driven through the real Tk tab.

Operator report 2026-11-19: with several photos selected, a checked Batch Edit ``stage.img2img = True`` did not count
when the selection was reviewed for the queue ("requires at least one valid stage"), and clicking another photo in the
list left Preview & Asset Metadata on the first one. Fake JobService, temporary store; no backend or GPU.
"""

from __future__ import annotations

import time
import tkinter as tk
from unittest.mock import Mock, patch

import pytest

from src.gui.views.photo_optimize_tab_frame_v2 import PhotoOptimizeTabFrameV2
from src.photo_optimize.store import PhotoOptimizeStore
from tests.controller.test_app_controller_photo_optimize import _build_controller
from tests.photo_optimize.test_photo_220 import image

ALL_OFF = {"img2img": False, "adetailer": False, "upscale": False}
QUEUE_REVIEW = "Review Photo Optimize → Queue"


@pytest.fixture
def stageless(tmp_path):
    """Three photos whose saved settings turn every stage off, as a txt2img Pipeline import used to leave them."""

    store = PhotoOptimizeStore(tmp_path / "photos")
    ids = []
    for index in range(3):
        asset = store.import_photo(image(tmp_path / f"photo-{index}.png", (320 + 64 * index, 480)))
        asset.baseline.stage_defaults = dict(ALL_OFF)
        store.save_asset(asset)
        ids.append(asset.asset_id)
    return store, ids


@pytest.fixture(autouse=True)
def no_real_dialogs(monkeypatch):
    def unexpected(*args, **kwargs):
        raise AssertionError(f"Unexpected dialog: {args}")

    for module in ("photo_optimize_scope", "photo_optimize_tab_frame_v2"):
        monkeypatch.setattr(f"src.gui.views.{module}.messagebox.showerror", unexpected)
        monkeypatch.setattr(f"src.gui.views.{module}.messagebox.showwarning", unexpected)
        monkeypatch.setattr(f"src.gui.views.{module}.messagebox.showinfo", Mock())


def settle(root, tab, done=lambda: True):
    """Pump Tk until no photo operation is pending, nothing is scheduled and ``done`` holds."""

    until = time.monotonic() + 15
    while time.monotonic() < until:
        root.update()
        if tab._operation_future is None and tab._operation_poll_id is None and done():
            root.update()
            if tab._operation_future is None and done():
                return
        time.sleep(0.01)
    raise AssertionError("Photo worker failed to settle")


def select(tab, ids):
    tab.assets_list.selection_clear(0, "end")
    for identity in ids:
        tab.assets_list.selection_set(tab._asset_index_by_row.index(identity))
    tab._on_asset_select(None)


def batch_edit_img2img_on(root, tab, ids):
    select(tab, ids)
    tab.edit_workspaces.select(tab.batch_workspace)
    root.update()
    tab.batch_editor.masks["stage.img2img"].set(True)
    tab.batch_editor.values["stage.img2img"].set("True")


@pytest.mark.gui
def test_a_checked_batch_edit_stage_counts_when_the_selection_is_reviewed(tk_root, stageless):
    store, ids = stageless
    controller = _build_controller()
    tab = PhotoOptimizeTabFrameV2(tk_root, app_controller=controller, store=store)
    try:
        batch_edit_img2img_on(tk_root, tab, ids)
        titles: list[str] = []
        texts: list[str] = []

        def review(parent, title, text, **kwargs):
            titles.append(title)
            texts.append(text)
            return True

        with (
            patch("src.controller.app_controller.get_photo_optimize_store", return_value=store),
            patch("src.gui.views.photo_optimize_scope.review_dialog", side_effect=review),
        ):
            tab._optimize(batch_all=False)
            settle(tk_root, tab, lambda: controller.job_service.submit_njrs.called)

        # First the checked Batch Edit fields are reviewed and saved, then the queue plan is reviewed.
        assert len(titles) == 2 and titles[-1] == QUEUE_REVIEW
        assert all(i in texts[0] for i in ids) and "stage.img2img: False -> True" in texts[0]
        assert all(store.get_asset(i).baseline.stage_defaults["img2img"] is True for i in ids)
        controller.job_service.submit_njrs.assert_called_once()
        jobs = controller.job_service.submit_njrs.call_args.args[0]
        assert sum(len(job.input_image_paths) for job in jobs) == 3
        assert {stage.stage_type for job in jobs for stage in job.stage_chain} == {"img2img"}
    finally:
        tab.destroy()


@pytest.mark.gui
def test_cancelling_the_batch_edit_review_saves_and_queues_nothing(tk_root, stageless):
    store, ids = stageless
    controller = _build_controller()
    tab = PhotoOptimizeTabFrameV2(tk_root, app_controller=controller, store=store)
    try:
        batch_edit_img2img_on(tk_root, tab, ids)
        before = {i: store.sidecar_path(i).read_bytes() for i in ids}
        with (
            patch("src.controller.app_controller.get_photo_optimize_store", return_value=store),
            patch("src.gui.views.photo_optimize_scope.review_dialog", return_value=False) as asked,
        ):
            tab._optimize(batch_all=False)
            settle(tk_root, tab)

        assert asked.call_count == 1  # the queue plan is never reached
        assert {i: store.sidecar_path(i).read_bytes() for i in ids} == before
        controller.job_service.submit_njrs.assert_not_called()
    finally:
        tab.destroy()


@pytest.mark.gui
def test_an_already_applied_batch_edit_goes_straight_to_the_queue_review(tk_root, stageless):
    store, ids = stageless
    for identity in ids:
        asset = store.get_asset(identity)
        asset.baseline.stage_defaults["img2img"] = True
        store.save_asset(asset)
    controller = _build_controller()
    tab = PhotoOptimizeTabFrameV2(tk_root, app_controller=controller, store=store)
    try:
        batch_edit_img2img_on(tk_root, tab, ids)  # still checked, but nothing would change
        titles: list[str] = []
        with (
            patch("src.controller.app_controller.get_photo_optimize_store", return_value=store),
            patch(
                "src.gui.views.photo_optimize_scope.review_dialog",
                side_effect=lambda parent, title, text, **kw: titles.append(title) or True,
            ),
        ):
            tab._optimize(batch_all=False)
            settle(tk_root, tab, lambda: controller.job_service.submit_njrs.called)

        assert titles == [QUEUE_REVIEW]
    finally:
        tab.destroy()


@pytest.mark.gui
def test_single_photo_scope_does_not_apply_pending_batch_edit_fields(tk_root, stageless):
    store, ids = stageless
    controller = _build_controller()
    tab = PhotoOptimizeTabFrameV2(tk_root, app_controller=controller, store=store)
    try:
        batch_edit_img2img_on(tk_root, tab, ids)
        tab.edit_workspaces.select(tab.single_workspace)
        tk_root.update()
        before = {i: store.sidecar_path(i).read_bytes() for i in ids}
        errors: list[str] = []
        with (
            patch("src.controller.app_controller.get_photo_optimize_store", return_value=store),
            patch("src.gui.views.photo_optimize_scope.review_dialog") as asked,
            patch(
                "src.gui.views.photo_optimize_tab_frame_v2.messagebox.showerror",
                side_effect=lambda title, text, **kw: errors.append(text),
            ),
        ):
            tab._optimize(batch_all=False)
            settle(tk_root, tab, lambda: bool(errors))

        asked.assert_not_called()
        assert {i: store.sidecar_path(i).read_bytes() for i in ids} == before
        assert "no stage turned on" in errors[0]
        controller.job_service.submit_njrs.assert_not_called()
    finally:
        tab.destroy()


def _click_row(root, tab, row, *, modifiers=""):
    """A real pointer press on ``row``; Tk's own Listbox bindings change the selection."""

    try:
        root.attributes("-alpha", 0.0)
    except tk.TclError:
        pass
    tab.pack(fill="both", expand=True)
    root.deiconify()
    root.update()
    try:
        tab.assets_list.see(row)
        root.update()
        x, y, _w, h = tab.assets_list.bbox(row)
        state = {"": 0, "Control": 0x0004, "Shift": 0x0001}[modifiers]
        tab.assets_list.event_generate("<ButtonPress-1>", x=x + 4, y=y + h // 2, state=state)
        tab.assets_list.event_generate("<ButtonRelease-1>", x=x + 4, y=y + h // 2, state=state)
        root.update()
    finally:
        root.withdraw()


def _metadata(tab) -> str:
    return str(tab.meta_label.cget("text"))


@pytest.mark.gui
def test_clicking_another_photo_shows_its_preview_and_metadata(tk_root, stageless):
    store, _ = stageless
    tab = PhotoOptimizeTabFrameV2(tk_root, store=store)
    ids = list(tab._asset_index_by_row)  # list order, not import order
    names = {i: store.get_asset(i).source_filename for i in ids}
    try:
        select(tab, ids)  # all three highlighted, the first is active
        settle(tk_root, tab)
        assert tab._current_asset_id == ids[0]
        assert names[ids[0]] in _metadata(tab)

        _click_row(tk_root, tab, 2)
        settle(tk_root, tab, lambda: tab._current_asset_id == ids[2])
        assert tab._selected_asset_ids(batch_all=False) == [ids[2]]
        assert names[ids[2]] in _metadata(tab)
        assert names[ids[0]] not in _metadata(tab)

        # Ctrl-click adds a photo to the batch, and it becomes the shown one.
        _click_row(tk_root, tab, 1, modifiers="Control")
        settle(tk_root, tab, lambda: tab._current_asset_id == ids[1])
        assert set(tab._selected_asset_ids(batch_all=False)) == {ids[1], ids[2]}
        assert names[ids[1]] in _metadata(tab)

        # Ctrl-click on a highlighted row removes the highlight and keeps the shown photo.
        _click_row(tk_root, tab, 2, modifiers="Control")
        settle(tk_root, tab)
        assert tab._selected_asset_ids(batch_all=False) == [ids[1]]
        assert tab._current_asset_id == ids[1]
    finally:
        tab.destroy()


@pytest.mark.gui
def test_a_selection_notification_without_a_click_keeps_the_chosen_active_photo(tk_root, stageless):
    store, _ = stageless
    tab = PhotoOptimizeTabFrameV2(tk_root, store=store)
    ids = list(tab._asset_index_by_row)
    try:
        select(tab, ids)
        settle(tk_root, tab)
        tab.active_photo_combo.current(2)
        tab.active_photo_combo.event_generate("<<ComboboxSelected>>")
        settle(tk_root, tab, lambda: tab._current_asset_id == ids[2])
        tab._on_asset_select(None)
        settle(tk_root, tab)
        assert tab._current_asset_id == ids[2]
        assert set(tab._selected_asset_ids(batch_all=False)) == set(ids)
    finally:
        tab.destroy()
