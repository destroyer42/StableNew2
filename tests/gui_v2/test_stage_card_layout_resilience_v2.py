from __future__ import annotations

from src.gui.stage_cards_v2.adetailer_stage_card_v2 import ADetailerStageCardV2
from src.gui.stage_cards_v2.advanced_txt2img_stage_card_v2 import AdvancedTxt2ImgStageCardV2
from src.gui.view_contracts.pipeline_layout_contract import (
    PRIMARY_CONTROL_MIN_WIDTH,
    get_stage_card_min_width,
)


def test_adetailer_card_uses_shared_width_baseline(tk_root) -> None:
    card = ADetailerStageCardV2(tk_root, theme=None)

    assert card.body_frame.columnconfigure(0)["minsize"] == get_stage_card_min_width()
    assert card._overall_frame.columnconfigure(1)["minsize"] == PRIMARY_CONTROL_MIN_WIDTH
    assert card._face_tab.columnconfigure(1)["minsize"] == PRIMARY_CONTROL_MIN_WIDTH
    assert card._hand_prompt_frame.columnconfigure(1)["minsize"] == PRIMARY_CONTROL_MIN_WIDTH


def test_txt2img_refiner_and_hires_forms_keep_control_widths(tk_root) -> None:
    card = AdvancedTxt2ImgStageCardV2(tk_root, controller=None, theme=None)

    assert card._refiner_frame.columnconfigure(1)["minsize"] == PRIMARY_CONTROL_MIN_WIDTH
    assert card._refiner_options_frame.columnconfigure(1)["minsize"] == PRIMARY_CONTROL_MIN_WIDTH
    assert card._hires_frame.columnconfigure(1)["minsize"] == PRIMARY_CONTROL_MIN_WIDTH
    assert card._hires_options_frame.columnconfigure(1)["minsize"] == PRIMARY_CONTROL_MIN_WIDTH