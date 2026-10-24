"""Headless form/selection contracts: no Tk root, display or real controller."""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import Mock, patch

import pytest

from src.controller.app_controller_services.background_task_coordinator import (
    BackgroundTaskCoordinator,
)
from src.gui.view_contracts.edit_work_runner import EditWorkRunner
from src.gui.view_contracts.photo_baseline_save_contract import PhotoBaselineSaveSession
from src.gui.views.photo_optimize_tab_frame_v2 import PhotoOptimizeTabFrameV2
from src.photo_optimize.editing import pipeline_mask
from src.photo_optimize.store import PhotoOptimizeStore

from .test_photo_220 import image


@pytest.fixture(autouse=True)
def unexpected_dialogs_fail(monkeypatch):
    def unexpected(*args, **kwargs):
        raise AssertionError(f"Unexpected headless dialog: {args}")

    monkeypatch.setattr("src.gui.views.photo_optimize_scope.messagebox.showerror", unexpected)
    monkeypatch.setattr("src.gui.views.photo_optimize_scope.messagebox.showwarning", unexpected)


class Variable:
    def __init__(self, value="", callback=None):
        self.value = value
        self.callback = callback

    def get(self):
        return self.value

    def set(self, value):
        self.value = value
        if self.callback:
            self.callback()


class Listbox:
    def __init__(self):
        self.selected = set()
        self.rows = []

    def curselection(self):
        return sorted(self.selected)

    def delete(self, *args):
        self.rows = []
        self.selected = set()

    def insert(self, index, label):
        self.rows.append(label)

    def selection_set(self, index):
        self.selected.add(index)

    def selection_clear(self, *args):
        self.selected = set()

    def activate(self, index):
        pass


def form(tmp_path):
    tab = PhotoOptimizeTabFrameV2.__new__(PhotoOptimizeTabFrameV2)
    tab.store = PhotoOptimizeStore(tmp_path / "photos")
    asset = tab.store.import_photo(image(tmp_path / "photo.png"))
    asset.baseline.config["keep"] = {"extension": 1}
    asset.notes = "notes"
    asset.tags = ["tag"]
    tab.store.save_asset(asset)
    tab._current_asset = asset
    tab._current_asset_id = asset.asset_id
    tab._suspend_asset_persist = False
    tab._content_visibility_mode = "nsfw"
    tab.show_image_previews_var = Variable(True)
    tab.edit_scope_var = Variable("Batch Edit")
    tab.edit_workspaces = Mock()
    tab.single_workspace = Mock()
    tab.batch_workspace = Mock()
    tab._model_name_map = {}
    tab._vae_name_map = {"Automatic": ""}
    for name in (
        "model",
        "vae",
        "tags",
        "stage_img2img",
        "stage_adetailer",
        "stage_upscale",
        "geometry_mode",
        "settings_error",
        "prompt_mode",
        "negative_mode",
        "batch_size",
        "show_archived",
        "submission_summary",
        "img2img_sampler",
        "img2img_scheduler",
        "img2img_steps",
        "img2img_cfg",
        "img2img_denoise",
        "img2img_width",
        "img2img_height",
        "adetailer_model",
        "adetailer_confidence",
        "adetailer_steps",
        "adetailer_cfg",
        "adetailer_denoise",
        "adetailer_sampler",
        "adetailer_scheduler",
        "upscale_upscaler",
        "upscale_factor",
        "upscale_steps",
        "upscale_denoise",
        "upscale_sampler",
        "upscale_scheduler",
        "upscale_tile_size",
        "upscale_face_restore",
        "upscale_face_restore_method",
    ):
        setattr(tab, f"{name}_var", Variable())
    tab.geometry_mode_var.set("auto")
    tab.vae_var.set("Automatic")
    tab.tags_var.set("tag")
    tab.stage_img2img_var.set(True)
    tab.stage_adetailer_var.set(False)
    tab.stage_upscale_var.set(False)
    tab.prompt_mode_var.set("append")
    tab.negative_mode_var.set("append")
    tab.batch_size_var.set(4)
    tab.show_archived_var.set(False)
    tab.geometry_width_entry = Mock()
    tab.geometry_height_entry = Mock()
    for name, value in (
        ("baseline_prompt", "portrait"),
        ("baseline_negative", ""),
        ("notes", "notes"),
        ("prompt_delta", "delta"),
        ("negative_delta", ""),
    ):
        setattr(tab, f"{name}_text", SimpleNamespace(value=value))
    tab._get_text = lambda widget: widget.value
    tab._apply_content_visibility_mode = Mock()
    tab._refresh_prompt_diff = Mock()
    tab._refresh_preview = Mock()
    tab._load_baseline_config_form(asset.baseline.config)
    tab.assets_list = Listbox()
    tab._asset_index_by_row = [asset.asset_id]
    tab.assets_list.rows = [asset.source_filename]
    tab.assets_list.selection_set(0)
    tab.selection_label = Mock()
    tab.active_photo_combo = Mock()
    tab._restored_asset_id = None
    tab._restored_asset_ids = None
    tab._run_photo_operation = lambda operation, completed: completed(operation())
    tab.after_idle = lambda callback: callback()
    tab._show_asset = Mock(side_effect=lambda asset_id: setattr(tab, "_current_asset_id", asset_id))
    tab._clear_selection = Mock(side_effect=lambda: setattr(tab, "_current_asset_id", None))
    tab.winfo_ismapped = lambda: True
    # The headless tab skips __init__, so give it the edit-work wiring it would have built (workers run inline).
    tab.baseline_save_status_var = Variable()
    tab._work = EditWorkRunner(BackgroundTaskCoordinator(run_inline=True), is_alive=lambda: True)
    tab._baseline_saves = PhotoBaselineSaveSession(
        get_store=lambda: tab.store, runner=tab._work, on_change=tab._render_baseline_save_status
    )
    tab._baseline_saves.rebase(asset.asset_id, tab.store.get_asset(asset.asset_id).baseline)
    tab._baseline_debounce_id = None
    tab._asset_load_seq = 0
    tab.after = lambda _ms, callback: "after#1"
    tab.after_cancel = lambda _identifier: None
    return tab


def test_programmatic_load_preserves_zero_and_performs_no_write(tmp_path):
    tab = form(tmp_path)
    before = tab.store.sidecar_path(tab._current_asset_id).read_bytes()
    for value in vars(tab).values():
        if isinstance(value, Variable):
            value.callback = tab._persist_current_asset_baseline
    tab._load_baseline_config_form(
        {
            "img2img": {"cfg_scale": 0.0, "denoising_strength": 0.0},
            "img2img_denoising_strength": 0.8,
        }
    )
    assert tab.img2img_denoise_var.get() == 0.0
    assert tab.img2img_cfg_var.get() == 0.0
    assert tab.store.sidecar_path(tab._current_asset_id).read_bytes() == before
    assert tab._suspend_asset_persist is False


def test_form_zero_and_custom_geometry_roundtrip_without_losing_fields(tmp_path):
    tab = form(tmp_path)
    tab.geometry_mode_var.set("custom")
    tab.img2img_width_var.set(768)
    tab.img2img_height_var.set(1024)
    tab.img2img_denoise_var.set(0.0)
    tab.adetailer_confidence_var.set(0.0)
    tab.upscale_face_restore_var.set(False)
    assert tab._persist_current_asset_baseline()
    asset = tab.store.get_asset(tab._current_asset_id)
    assert asset.baseline.geometry_policy == "custom"
    assert asset.baseline.config["img2img"]["width"] == 768
    assert asset.baseline.config["img2img_denoising_strength"] == 0.0
    assert asset.baseline.config["adetailer"]["ad_confidence"] == 0.0
    assert asset.baseline.config["keep"] == {"extension": 1}
    assert asset.notes == "notes" and asset.tags == ["tag"]


@pytest.mark.parametrize("bad", ["invalid", -1, 1.5, 0])
def test_invalid_form_edit_keeps_sidecar_unchanged(tmp_path, bad):
    tab = form(tmp_path)
    before = tab.store.sidecar_path(tab._current_asset_id).read_bytes()
    tab.img2img_steps_var.set(bad)
    accepted = tab._persist_current_asset_baseline()
    if bad in ("invalid", 1.5):
        assert (
            accepted is False
        )  # not even a number of steps: refused before anything is sent to the worker
    # A range error is found by the save worker's validation; either way the edit is refused with a visible
    # reason, reported as not saved, and the sidecar is untouched.
    assert tab.settings_error_var.get()
    assert tab.baseline_save_status_var.get().startswith("Not saved") or accepted is False
    assert tab.store.sidecar_path(tab._current_asset_id).read_bytes() == before


def test_resources_reload_cannot_persist_draft(tmp_path):
    tab = form(tmp_path)
    before = tab.store.sidecar_path(tab._current_asset_id).read_bytes()
    tab.model_var.callback = tab._persist_current_asset_baseline
    tab._project_resource_options = lambda resources: tab.model_var.set("another model")
    tab._refresh_resource_options({})
    assert tab.store.sidecar_path(tab._current_asset_id).read_bytes() == before


@pytest.mark.parametrize("mapped", [True, False])
def test_multi_selection_survives_refresh_and_other_photo_completion(tmp_path, mapped):
    tab = form(tmp_path)
    second = tab.store.import_photo(image(tmp_path / "second.png"))
    third = tab.store.import_photo(image(tmp_path / "third.png"))
    tab._asset_index_by_row.extend([second.asset_id, third.asset_id])
    tab.assets_list.selection_set(1)
    selected = set(tab._selected_asset_ids(batch_all=False))
    active = tab._current_asset_id
    tab.winfo_ismapped = lambda: mapped
    tab._pending_asset_refresh_target = None
    tab._pending_resources_payload = None
    tab._pending_visibility_refresh = False
    callbacks = []
    tab.after_idle = callbacks.append
    tab._refresh_assets = Mock(wraps=tab._refresh_assets)
    tab.on_assets_updated([third.asset_id])
    if not mapped:
        tab._refresh_assets.assert_not_called()
        assert tab._pending_asset_refresh_target == active
        tab._on_map()
        tab._refresh_assets.assert_not_called()
        assert len(callbacks) == 1
        callbacks[0]()
    tab._refresh_assets.assert_called_once_with()
    assert tab._pending_asset_refresh_target is None
    assert set(tab._selected_asset_ids(batch_all=False)) == selected
    assert tab._current_asset_id == active


def test_empty_gui_selection_does_not_submit_active_photo(tmp_path):
    tab = form(tmp_path)
    tab.assets_list.selection_clear()
    tab.app_controller = SimpleNamespace(on_optimize_photo_assets=Mock())
    with patch("src.gui.views.photo_optimize_tab_frame_v2.messagebox.showwarning"):
        tab._optimize(batch_all=False)
    tab.app_controller.on_optimize_photo_assets.assert_not_called()


def test_pipeline_copy_targets_all_selected_preserving_notes_and_prompts(tmp_path):
    tab = form(tmp_path)
    second = tab.store.import_photo(image(tmp_path / "second.png", (800, 600)))
    second.baseline.prompt = "second prompt"
    tab.store.save_asset(second)
    tab._asset_index_by_row.append(second.asset_id)
    tab.assets_list.selection_set(1)
    tab.app_controller = SimpleNamespace(
        build_photo_optimize_defaults=lambda: {
            "model": "copied",
            "vae": "",
            "config": {"img2img": {"steps": 25}},
            "stage_defaults": {"img2img": True, "adetailer": True, "upscale": False},
        }
    )
    with (
        patch(
            "src.gui.views.photo_optimize_scope.pipeline_copy_dialog",
            side_effect=lambda parent, snapshot, scope, review: review(
                pipeline_mask(
                    snapshot, {"model", "vae", "stages", "img2img", "adetailer", "upscale"}
                )
            ),
        ),
        patch("src.gui.views.photo_optimize_scope.review_dialog", return_value=True),
        patch("src.gui.views.photo_optimize_scope.messagebox.showinfo"),
    ):
        tab._use_current_pipeline_settings()
    assert tab.store.get_asset(second.asset_id).baseline.prompt == "second prompt"
    assert tab.store.get_asset(second.asset_id).baseline.model == "copied"
    assert tab.store.get_asset(second.asset_id).baseline.config["width"] == 800
    first = tab.store.get_asset(tab._current_asset.asset_id)
    assert first.notes == "notes" and first.tags == ["tag"]
    assert first.baseline.model == "copied"


def test_missing_pipeline_source_shows_error_and_writes_nothing(tmp_path):
    tab = form(tmp_path)
    tab.app_controller = None
    before = tab.store.sidecar_path(tab._current_asset_id).read_bytes()
    with patch("src.gui.views.photo_optimize_tab_frame_v2.messagebox.showerror") as error:
        tab._use_current_pipeline_settings()
    assert "unavailable" in error.call_args.args[1]
    assert tab.store.sidecar_path(tab._current_asset_id).read_bytes() == before


def test_migration_completion_is_projected_only_by_gui_poll(tmp_path):
    tab = form(tmp_path)
    tab._workspace_future = Mock()
    tab._workspace_future.done.return_value = True
    tab._workspace_future.result.return_value = tab.store
    tab._workspace_executor = Mock()
    tab._poll_workspace()
    tab._workspace_executor.shutdown.assert_called_once_with(wait=False)
    assert "Workspace ready" in tab.submission_summary_var.get()


def test_operation_runs_on_worker_and_result_waits_for_gui_poll(tmp_path):
    from concurrent.futures import Future

    tab = form(tmp_path)
    tab._operation_future = None
    future = Future()
    executor = Mock()
    executor.submit.return_value = future
    callbacks = []
    tab.after = lambda delay, callback: callbacks.append(callback)
    operation = Mock(return_value=3)
    completed = Mock()
    with patch(
        "src.gui.views.photo_optimize_tab_frame_v2.ThreadPoolExecutor", return_value=executor
    ):
        PhotoOptimizeTabFrameV2._run_photo_operation(tab, operation, completed)
    executor.submit.assert_called_once_with(operation)
    completed.assert_not_called()
    future.set_result(3)
    callbacks[0]()
    completed.assert_called_once_with(3)
    assert tab._operation_future is None


def test_pipeline_img2img_projection_preserves_zero_without_tk():
    from src.gui.stage_cards_v2.advanced_img2img_stage_card_v2 import AdvancedImg2ImgStageCardV2

    card = SimpleNamespace(
        **{
            name + "_var": Variable(value)
            for name, value in {
                "vae": "Automatic",
                "model": "photoModel",
                "sampler": "Euler a",
                "steps": 20,
                "cfg": 0.0,
                "denoise": 0.0,
                "width": 640,
                "height": 960,
                "mask_mode": "",
            }.items()
        }
    )
    projection = AdvancedImg2ImgStageCardV2.to_config_dict(card)["img2img"]
    assert projection["cfg_scale"] == 0.0
    assert projection["denoising_strength"] == 0.0


def test_pipeline_upscale_projection_preserves_zero_without_tk():
    from src.gui.stage_cards_v2.advanced_upscale_stage_card_v2 import AdvancedUpscaleStageCardV2

    card = SimpleNamespace(
        **{
            name + "_var": Variable(value)
            for name, value in {
                "upscaler": "R-ESRGAN 4x+",
                "mode": "single",
                "steps": 20,
                "denoise": 0.0,
                "factor": 2.0,
                "tile_size": 0,
                "face_restore": False,
                "face_restore_method": "CodeFormer",
                "sampler": "Euler a",
                "scheduler": "normal",
            }.items()
        }
    )
    card._upscaler_name_map = {}
    projection = AdvancedUpscaleStageCardV2.to_config_dict(card)["upscale"]
    assert projection["denoising_strength"] == 0.0
    assert projection["face_restore"] is False


def test_multiselection_restore_waits_for_deferred_store(tmp_path):
    tab = form(tmp_path)
    second = tab.store.import_photo(image(tmp_path / "second.png"))
    store = tab.store
    first_id = tab._current_asset_id
    tab.store = None
    assert tab.restore_photo_optimize_state(
        {
            "selected_asset_id": first_id,
            "selected_asset_ids": [first_id, second.asset_id],
            "show_archived": True,
        }
    )
    tab.store = store
    tab._refresh_assets(select_asset_id=first_id)
    assert set(tab._selected_asset_ids(batch_all=False)) == {first_id, second.asset_id}
    assert tab._current_asset_id == first_id
