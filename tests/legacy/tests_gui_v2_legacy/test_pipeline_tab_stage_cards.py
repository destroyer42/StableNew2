from __future__ import annotations

import tkinter as tk

import pytest

from src.gui.state import StateManager
from src.gui.stage_cards_v2.advanced_img2img_stage_card_v2 import AdvancedImg2ImgStageCardV2
from src.gui.stage_cards_v2.advanced_txt2img_stage_card_v2 import AdvancedTxt2ImgStageCardV2
from src.gui.stage_cards_v2.advanced_upscale_stage_card_v2 import AdvancedUpscaleStageCardV2
from src.gui.views.pipeline_tab_frame_v2 import PipelineTabFrame


def test_pipeline_tab_hosts_advanced_stage_cards():
    try:
        root = tk.Tk()
    except tk.TclError:
        pytest.skip("Tkinter not available in this environment")

    root.withdraw()
    try:
        tab = PipelineTabFrame(root)
        panel = tab.stage_cards_panel

        assert isinstance(panel.txt2img_card._child, AdvancedTxt2ImgStageCardV2)
        assert isinstance(panel.img2img_card._child, AdvancedImg2ImgStageCardV2)
        assert isinstance(panel.upscale_card._child, AdvancedUpscaleStageCardV2)

        # Spot-check a couple of expected controls on the txt2img and img2img cards
        assert hasattr(panel.txt2img_card._child, "sampler_section")
        assert hasattr(panel.img2img_card._child, "denoise_var")
    finally:
        try:
            root.destroy()
        except Exception:
            pass


def test_pipeline_tab_syncs_overrides_into_state_manager():
    try:
        root = tk.Tk()
    except tk.TclError:
        pytest.skip("Tkinter not available in this environment")

    root.withdraw()
    try:
        dummy_ctrl = type("C", (), {"state_manager": StateManager()})()
        tab = PipelineTabFrame(root, pipeline_controller=dummy_ctrl)
        # Simulate user edits
        tab.stage_cards_panel.txt2img_card._child.model_var.set("sdxl")
        tab.stage_cards_panel.txt2img_card._child.width_var.set("768")
        tab._sync_state_overrides()
        overrides = dummy_ctrl.state_manager.get_pipeline_overrides()
        assert overrides.get("model_name") == "sdxl"
        assert overrides.get("width") == 768
    finally:
        try:
            root.destroy()
        except Exception:
            pass
