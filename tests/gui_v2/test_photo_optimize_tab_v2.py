from __future__ import annotations

from pathlib import Path
from unittest.mock import Mock

import tkinter as tk
from PIL import Image

from src.gui.views.photo_optimize_tab_frame_v2 import PhotoOptimizeTabFrameV2
from src.photo_optimize.store import PhotoOptimizeStore


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
        tab._use_current_pipeline_settings()
        reloaded = store.get_asset(asset.asset_id)
        assert reloaded is not None
        assert reloaded.baseline.model == "realisticVision"
        assert reloaded.baseline.vae == "vae-ft-mse"
        assert reloaded.baseline.config["img2img"]["denoising_strength"] == 0.3
        assert reloaded.baseline.stage_defaults["adetailer"] is True
    finally:
        tab.destroy()
