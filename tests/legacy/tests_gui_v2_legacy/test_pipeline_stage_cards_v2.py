from __future__ import annotations

import tkinter as tk

import pytest

from src.gui.stage_cards_v2.advanced_txt2img_stage_card_v2 import AdvancedTxt2ImgStageCardV2
from src.gui.stage_cards_v2.advanced_img2img_stage_card_v2 import AdvancedImg2ImgStageCardV2
from src.gui.stage_cards_v2.advanced_upscale_stage_card_v2 import AdvancedUpscaleStageCardV2


@pytest.fixture
def tk_root():
    try:
        root = tk.Tk()
    except tk.TclError:
        pytest.skip("Tkinter not available in this environment")
    root.withdraw()
    yield root
    try:
        root.destroy()
    except Exception:
        pass


def test_txt2img_roundtrip(tk_root):
    card = AdvancedTxt2ImgStageCardV2(tk_root)
    cfg_in = {
        "txt2img": {
            "model": "sdxl",
            "vae": "sdxl_vae",
            "sampler_name": "Euler",
            "steps": 30,
            "cfg_scale": 9.5,
            "width": 768,
            "height": 640,
            "clip_skip": 2,
        }
    }
    card.load_from_config(cfg_in)
    out = card.to_config_dict()["txt2img"]
    assert out["model_name"] == "sdxl"
    assert out["sampler_name"] == "Euler"
    assert out["steps"] == 30
    assert out["width"] == 768
    assert out["height"] == 640


def test_img2img_roundtrip(tk_root):
    card = AdvancedImg2ImgStageCardV2(tk_root)
    cfg_in = {
        "img2img": {
            "sampler_name": "DPM",
            "cfg_scale": 6.0,
            "denoising_strength": 0.4,
            "mask_mode": "keep",
            "width": 512,
            "height": 512,
        }
    }
    card.load_from_config(cfg_in)
    out = card.to_config_dict()["img2img"]
    assert out["sampler_name"] == "DPM"
    assert abs(out["denoising_strength"] - 0.4) < 1e-6
    assert out["mask_mode"] == "keep"


def test_upscale_roundtrip(tk_root):
    card = AdvancedUpscaleStageCardV2(tk_root)
    cfg_in = {
        "upscale": {
            "upscaler": "R-ESRGAN 4x+",
            "upscale_mode": "batch",
            "steps": 15,
            "denoising_strength": 0.5,
            "upscaling_resize": 3.0,
            "tile_size": 256,
            "face_restore": True,
        }
    }
    card.load_from_config(cfg_in)
    out = card.to_config_dict()["upscale"]
    assert out["upscaler"] == "R-ESRGAN 4x+"
    assert out["upscale_mode"] == "batch"
    assert out["steps"] == 15
    assert abs(out["upscaling_resize"] - 3.0) < 1e-6
    assert out["tile_size"] == 256
    assert out["face_restore"] is True
