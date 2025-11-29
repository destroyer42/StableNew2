from __future__ import annotations

import tkinter as tk
import pytest

from src.gui.stage_cards_v2.advanced_txt2img_stage_card_v2 import AdvancedTxt2ImgStageCardV2
from src.gui.stage_cards_v2.advanced_img2img_stage_card_v2 import AdvancedImg2ImgStageCardV2
from src.gui.stage_cards_v2.advanced_upscale_stage_card_v2 import AdvancedUpscaleStageCardV2


def test_txt2img_validation():
    try:
        root = tk.Tk()
    except Exception:
        pytest.skip("Tkinter/Tcl not available")
    card = AdvancedTxt2ImgStageCardV2(root)
    card.steps_var.set("0")
    result = card.validate()
    assert not result.ok
    card.steps_var.set("10")
    card.width_var.set("510")
    result = card.validate()
    assert not result.ok
    card.width_var.set("512")
    card.height_var.set("512")
    card.cfg_var.set("9")
    assert card.validate().ok
    root.destroy()


def test_img2img_validation():
    try:
        root = tk.Tk()
    except Exception:
        pytest.skip("Tkinter/Tcl not available")
    card = AdvancedImg2ImgStageCardV2(root)
    card.denoise_var.set("1.2")
    assert not card.validate().ok
    card.denoise_var.set("0.5")
    assert card.validate().ok
    root.destroy()


def test_upscale_validation():
    try:
        root = tk.Tk()
    except Exception:
        pytest.skip("Tkinter/Tcl not available")
    card = AdvancedUpscaleStageCardV2(root)
    card.factor_var.set("0")
    assert not card.validate().ok
    card.factor_var.set("2")
    assert card.validate().ok
    root.destroy()
