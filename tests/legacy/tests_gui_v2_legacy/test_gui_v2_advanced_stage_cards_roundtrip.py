from __future__ import annotations

import tkinter as tk
import pytest

from src.gui.stage_cards_v2.advanced_txt2img_stage_card_v2 import AdvancedTxt2ImgStageCardV2
from src.gui.stage_cards_v2.advanced_img2img_stage_card_v2 import AdvancedImg2ImgStageCardV2
from src.gui.stage_cards_v2.advanced_upscale_stage_card_v2 import AdvancedUpscaleStageCardV2


def test_roundtrip_txt2img():
    try:
        root = tk.Tk()
    except Exception:
        pytest.skip("Tkinter/Tcl not available")
    card = AdvancedTxt2ImgStageCardV2(root)
    cfg = {"txt2img": {"model": "m", "vae": "v", "sampler_name": "Euler", "scheduler": "Normal", "steps": 25, "cfg_scale": 8.0, "width": 512, "height": 768, "clip_skip": 2}}
    card.load_from_config(cfg)
    out = card.to_config_dict()
    assert out["txt2img"]["model"] == "m"
    assert out["txt2img"]["scheduler"] == "Normal"
    root.destroy()


def test_roundtrip_img2img():
    try:
        root = tk.Tk()
    except Exception:
        pytest.skip("Tkinter/Tcl not available")
    card = AdvancedImg2ImgStageCardV2(root)
    cfg = {"img2img": {"sampler_name": "Euler", "cfg_scale": 7.5, "denoising_strength": 0.4, "width": 640, "height": 480}}
    card.load_from_config(cfg)
    out = card.to_config_dict()
    assert out["img2img"]["sampler_name"] == "Euler"
    assert out["img2img"]["denoising_strength"] == 0.4
    root.destroy()


def test_roundtrip_upscale():
    try:
        root = tk.Tk()
    except Exception:
        pytest.skip("Tkinter/Tcl not available")
    card = AdvancedUpscaleStageCardV2(root)
    cfg = {"upscale": {"upscaler": "R-ESRGAN", "upscaling_resize": 3, "tile_size": 64, "face_restore": True}}
    card.load_from_config(cfg)
    out = card.to_config_dict()
    assert out["upscale"]["upscaler"] == "R-ESRGAN"
    assert out["upscale"]["upscaling_resize"] == 3
    root.destroy()
