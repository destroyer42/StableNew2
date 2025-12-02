"""Layout tests for stage cards inside PipelinePanelV2."""

from __future__ import annotations

from src.gui.pipeline_panel_v2 import PipelinePanelV2
from src.gui.stage_cards_v2.advanced_txt2img_stage_card_v2 import AdvancedTxt2ImgStageCardV2
from src.gui.stage_cards_v2.advanced_img2img_stage_card_v2 import AdvancedImg2ImgStageCardV2
from src.gui.stage_cards_v2.advanced_upscale_stage_card_v2 import AdvancedUpscaleStageCardV2


def test_stage_cards_present(gui_app_with_dummies):
    gui, _controller, _cfg = gui_app_with_dummies
    panel = gui.pipeline_panel_v2
    assert isinstance(panel, PipelinePanelV2)
    assert isinstance(panel.txt2img_card, AdvancedTxt2ImgStageCardV2)
    assert isinstance(panel.img2img_card, AdvancedImg2ImgStageCardV2)
    assert isinstance(panel.upscale_card, AdvancedUpscaleStageCardV2)
