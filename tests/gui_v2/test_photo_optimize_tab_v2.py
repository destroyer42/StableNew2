from __future__ import annotations

import tkinter as tk
from pathlib import Path
from unittest.mock import Mock, patch

import pytest
from PIL import Image

from src.api.webui_resources import WebUIResource, WebUIResourceType
from src.gui.app_state_v2 import AppStateV2
from src.gui.views.photo_optimize_tab_frame_v2 import PhotoOptimizeTabFrameV2
from src.photo_optimize.editing import pipeline_mask
from src.photo_optimize.store import PhotoOptimizeStore


@pytest.fixture(autouse=True)
def unexpected_dialogs_fail(monkeypatch):
    def unexpected(*args, **kwargs):
        raise AssertionError(f"Unexpected GUI dialog: {args}")
    monkeypatch.setattr("src.gui.views.photo_optimize_scope.messagebox.showerror", unexpected)
    monkeypatch.setattr("src.gui.views.photo_optimize_scope.messagebox.showwarning", unexpected)


def _write_image(path: Path, color: tuple[int, int, int] = (80, 100, 120)) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    Image.new("RGB", (32, 32), color).save(path)


def test_photo_optimize_tab_restores_selected_asset(tk_root: tk.Tk, tmp_path: Path) -> None:
    store = PhotoOptimizeStore(tmp_path / "photo_optimize")
    image_a = tmp_path / "source" / "a.png"
    image_b = tmp_path / "source" / "b.png"
    _write_image(image_a, (255, 0, 0))
    _write_image(image_b, (0, 255, 0))
    asset_a = store.import_photo(image_a)
    asset_b = store.import_photo(image_b)

    tab = PhotoOptimizeTabFrameV2(tk_root, store=store)
    try:
        tab.restore_photo_optimize_state({"selected_asset_id": asset_b.asset_id})
        assert tab.get_photo_optimize_state()["selected_asset_id"] == asset_b.asset_id
        assert asset_a.asset_id in tab._asset_index_by_row
    finally:
        tab.destroy()


def test_photo_optimize_use_current_pipeline_settings_updates_baseline(
    tk_root: tk.Tk, tmp_path: Path
) -> None:
    store = PhotoOptimizeStore(tmp_path / "photo_optimize")
    image_path = tmp_path / "source" / "portrait.png"
    _write_image(image_path)
    asset = store.import_photo(image_path)
    controller = Mock()
    controller.build_photo_optimize_defaults.return_value = {
        "model": "realisticVision",
        "vae": "vae-ft-mse",
        "config": {"img2img": {"denoising_strength": 0.3}},
        "stage_defaults": {"img2img": True, "adetailer": True, "upscale": False},
    }

    tab = PhotoOptimizeTabFrameV2(tk_root, app_controller=controller, store=store)
    try:
        tab._show_asset(asset.asset_id)
        tab._run_photo_operation = lambda operation, completed: completed(operation())
        tab.after_idle = lambda callback: callback()
        with (
            patch("src.gui.views.photo_optimize_scope.pipeline_copy_dialog",
                  side_effect=lambda parent, snapshot, scope, review: review(pipeline_mask(snapshot, {"model", "vae", "stages", "img2img", "adetailer", "upscale"}))),
            patch("src.gui.views.photo_optimize_scope.review_dialog", return_value=True),
            patch("src.gui.views.photo_optimize_scope.messagebox.showinfo"),
        ):
            tab._use_current_pipeline_settings()
        reloaded = store.get_asset(asset.asset_id)
        assert reloaded is not None
        assert reloaded.baseline.model == "realisticVision"
        assert reloaded.baseline.vae == "vae-ft-mse"
        assert reloaded.baseline.config["img2img"]["denoising_strength"] == 0.3
        assert reloaded.baseline.stage_defaults["adetailer"] is True
    finally:
        tab.destroy()


def test_photo_optimize_interrogate_updates_baseline_prompt(tk_root: tk.Tk, tmp_path: Path) -> None:
    store = PhotoOptimizeStore(tmp_path / "photo_optimize")
    image_path = tmp_path / "source" / "portrait.png"
    _write_image(image_path)
    asset = store.import_photo(image_path, baseline_defaults={"prompt": "old prompt"})
    controller = Mock()
    controller.interrogate_photo_path.return_value = "clean portrait, natural lighting"

    tab = PhotoOptimizeTabFrameV2(tk_root, app_controller=controller, store=store)
    try:
        tab._show_asset(asset.asset_id)
        tab._interrogate_current_asset()
        reloaded = store.get_asset(asset.asset_id)
        assert reloaded is not None
        assert reloaded.baseline.prompt == "clean portrait, natural lighting"
        assert reloaded.baseline.source == "interrogated"
    finally:
        tab.destroy()


def test_photo_optimize_stage_config_fields_persist_to_sidecar(
    tk_root: tk.Tk, tmp_path: Path
) -> None:
    store = PhotoOptimizeStore(tmp_path / "photo_optimize")
    image_path = tmp_path / "source" / "portrait.png"
    _write_image(image_path)
    asset = store.import_photo(image_path)

    tab = PhotoOptimizeTabFrameV2(tk_root, store=store)
    try:
        tab._show_asset(asset.asset_id)
        tab.img2img_sampler_var.set("DPM++ 2M Karras")
        tab.img2img_steps_var.set(32)
        tab.img2img_cfg_var.set(6.5)
        tab.img2img_denoise_var.set(0.42)
        tab.geometry_mode_var.set("custom")
        tab.img2img_width_var.set(768)
        tab.img2img_height_var.set(1024)
        tab.adetailer_model_var.set("face_yolov8n.pt")
        tab.adetailer_confidence_var.set(0.61)
        tab.adetailer_steps_var.set(18)
        tab.adetailer_cfg_var.set(5.9)
        tab.adetailer_denoise_var.set(0.27)
        tab.adetailer_sampler_var.set("Euler a")
        tab.adetailer_scheduler_var.set("Karras")
        tab.upscale_upscaler_var.set("R-ESRGAN 4x+")
        tab.upscale_factor_var.set(2.5)
        tab.upscale_steps_var.set(14)
        tab.upscale_denoise_var.set(0.18)
        tab.upscale_sampler_var.set("Euler a")
        tab.upscale_scheduler_var.set("normal")
        tab.upscale_tile_size_var.set(768)
        tab.upscale_face_restore_var.set(True)
        tab.upscale_face_restore_method_var.set("GFPGAN")
        tab._persist_current_asset_baseline()

        reloaded = store.get_asset(asset.asset_id)
        assert reloaded is not None
        config = reloaded.baseline.config
        assert config["img2img"]["steps"] == 32
        assert config["img2img"]["width"] == 768
        assert config["img2img_denoising_strength"] == 0.42
        assert config["adetailer"]["adetailer_model"] == "face_yolov8n.pt"
        assert config["adetailer_cfg_scale"] == 5.9
        assert config["upscale"]["upscaling_resize"] == 2.5
        assert config["upscale"]["face_restore"] is True
        assert config["upscale_sampler_name"] == "Euler a"
    finally:
        tab.destroy()


def test_photo_optimize_header_exposes_submit_buttons(tk_root: tk.Tk, tmp_path: Path) -> None:
    store = PhotoOptimizeStore(tmp_path / "photo_optimize")
    image_path = tmp_path / "source" / "portrait.png"
    _write_image(image_path)
    asset = store.import_photo(image_path)
    controller = Mock()
    controller.on_optimize_photo_assets.return_value = 1
    controller.build_photo_optimize_defaults.return_value = {"config": {"img2img": {}}}
    from src.photo_optimize.submission import prepare_photo_plan
    plan = prepare_photo_plan(assets=[asset.to_dict()], stages=["img2img"], fallback_config={"img2img": {}},
                              store=store, batch_size=1)
    controller.prepare_photo_optimize_plan.return_value = plan
    controller.submit_prepared_photo_plan.return_value = len(plan.jobs)

    tab = PhotoOptimizeTabFrameV2(tk_root, app_controller=controller, store=store)
    try:
        tab._show_asset(asset.asset_id)
        with (patch("src.gui.views.photo_optimize_tab_frame_v2.messagebox.showinfo"),
              patch("src.gui.views.photo_optimize_scope.review_dialog", return_value=True)):
            tab._run_photo_operation = lambda operation, completed: completed(operation())
            tab.after_idle = lambda callback: callback()
            tab.optimize_selected_header_btn.invoke()
        controller.prepare_photo_optimize_plan.assert_called_once()
        controller.submit_prepared_photo_plan.assert_called_once_with(plan)
    finally:
        tab.destroy()


def test_photo_optimize_resources_populate_model_and_vae_dropdowns(
    tk_root: tk.Tk, tmp_path: Path
) -> None:
    store = PhotoOptimizeStore(tmp_path / "photo_optimize")
    image_path = tmp_path / "source" / "portrait.png"
    _write_image(image_path)
    asset = store.import_photo(image_path)
    app_state = AppStateV2()
    app_state.set_resources(
        {
            "models": [
                WebUIResource(
                    type=WebUIResourceType.MODEL,
                    name="juggernautXL_ragnarokBy.safetensors [dd08fa32f9]",
                    display_name="Juggernaut XL Ragnarok",
                )
            ],
            "vaes": [
                WebUIResource(
                    type=WebUIResourceType.VAE,
                    name="vae-ft-mse-840000-ema-pruned",
                    display_name="VAE FT MSE",
                )
            ],
            "samplers": [],
            "schedulers": [],
            "upscalers": [],
            "adetailer_models": [],
            "adetailer_detectors": [],
        }
    )

    tab = PhotoOptimizeTabFrameV2(tk_root, app_state=app_state, store=store)
    try:
        tab._show_asset(asset.asset_id)
        assert "Juggernaut XL Ragnarok" in list(tab.model_combo.cget("values"))
        assert "VAE FT MSE" in list(tab.vae_combo.cget("values"))
        assert hasattr(tab, "body_scroll")

        tab.model_var.set("Juggernaut XL Ragnarok")
        tab.vae_var.set("VAE FT MSE")
        tab._persist_current_asset_baseline()

        reloaded = store.get_asset(asset.asset_id)
        assert reloaded is not None
        assert reloaded.baseline.model == "juggernautXL_ragnarokBy.safetensors [dd08fa32f9]"
        assert reloaded.baseline.vae == "vae-ft-mse-840000-ema-pruned"
    finally:
        tab.destroy()


def test_photo_optimize_defers_asset_refresh_until_mapped(tk_root: tk.Tk, tmp_path: Path) -> None:
    store = PhotoOptimizeStore(tmp_path / "photo_optimize")
    image_path = tmp_path / "source" / "portrait.png"
    _write_image(image_path)
    asset = store.import_photo(image_path)
    selected_photo = tmp_path / "source" / "selected.png"
    completed_photo = tmp_path / "source" / "completed.png"
    _write_image(selected_photo)
    _write_image(completed_photo)
    selected_asset = store.import_photo(selected_photo)
    completed_asset = store.import_photo(completed_photo)

    tab = PhotoOptimizeTabFrameV2(tk_root, store=store)
    try:
        tab.assets_list.selection_clear(0, tk.END)
        for asset_id in (asset.asset_id, selected_asset.asset_id):
            tab.assets_list.selection_set(tab._asset_index_by_row.index(asset_id))
        tab._show_asset(asset.asset_id)
        tab._refresh_assets = Mock(wraps=tab._refresh_assets)

        tab.on_assets_updated([completed_asset.asset_id])

        tab._refresh_assets.assert_not_called()
        assert tab._pending_asset_refresh_target == asset.asset_id

        tab._on_map()
        tk_root.update_idletasks()
        tk_root.update()

        tab._refresh_assets.assert_called_once_with()
        assert tab._pending_asset_refresh_target is None
        assert set(tab._selected_asset_ids(batch_all=False)) == {
            asset.asset_id, selected_asset.asset_id,
        }
        assert tab._current_asset_id == asset.asset_id
    finally:
        tab.destroy()
