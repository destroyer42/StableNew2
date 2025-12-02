from __future__ import annotations

import tkinter as tk
import pytest

from src.gui.stage_cards_v2.advanced_txt2img_stage_card_v2 import AdvancedTxt2ImgStageCardV2
from src.gui.stage_cards_v2.advanced_img2img_stage_card_v2 import AdvancedImg2ImgStageCardV2
from src.gui.stage_cards_v2.advanced_upscale_stage_card_v2 import AdvancedUpscaleStageCardV2


def test_stage_cards_build_and_vars():
    try:
        root = tk.Tk()
    except Exception:
        pytest.skip("Tkinter/Tcl not available")
    txt = AdvancedTxt2ImgStageCardV2(root)
    img = AdvancedImg2ImgStageCardV2(root)
    up = AdvancedUpscaleStageCardV2(root)

    assert hasattr(txt, "model_var")
    assert hasattr(img, "denoise_var")
    assert hasattr(up, "upscaler_var")

    root.destroy()
