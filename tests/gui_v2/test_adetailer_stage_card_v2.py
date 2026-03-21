from __future__ import annotations

import tkinter as tk

import pytest

from src.gui.stage_cards_v2.adetailer_stage_card_v2 import ADetailerStageCardV2


@pytest.mark.gui
def test_adetailer_stage_card_roundtrip_includes_face_hand_and_stage_model(tk_root: tk.Tk) -> None:
    card = ADetailerStageCardV2(tk_root)
    sample = {
        "adetailer_checkpoint_model": "juggernautXL_ragnarokBy.safetensors",
        "enable_face_pass": False,
        "adetailer_model": "mediapipe_face_full",
        "adetailer_confidence": 0.45,
        "adetailer_scheduler": "Use same scheduler",
        "ad_mask_filter_method": "all",
        "ad_hands_enabled": True,
        "adetailer_hands_model": "hand_yolov8s.pt",
        "adetailer_hands_confidence": 0.61,
        "adetailer_hands_scheduler": "Karras",
        "ad_hands_inpaint_only_masked": False,
        "ad_hands_use_inpaint_width_height": True,
        "ad_hands_inpaint_width": 768,
        "ad_hands_inpaint_height": 896,
    }

    card.load_from_dict(sample)
    exported = card.to_config_dict()

    assert card.stage_model_override_var.get() == "juggernautXL_ragnarokBy.safetensors"
    assert card.enable_face_pass_var.get() is False
    assert card.enable_hands_pass_var.get() is True
    assert exported["adetailer_checkpoint_model"] == "juggernautXL_ragnarokBy.safetensors"
    assert exported["adetailer_model"] == "mediapipe_face_full"
    assert exported["adetailer_scheduler"] == "inherit"
    assert exported["enable_hands_pass"] is True
    assert exported["adetailer_hands_model"] == "hand_yolov8s.pt"
    assert exported["adetailer_hands_scheduler"] == "Karras"
    assert exported["ad_hands_inpaint_only_masked"] is False
    assert exported["ad_hands_inpaint_width"] == 768
    assert exported["ad_hands_inpaint_height"] == 896


@pytest.mark.gui
def test_adetailer_stage_card_applies_webui_resources_to_models_and_sampler_lists(
    tk_root: tk.Tk,
) -> None:
    card = ADetailerStageCardV2(tk_root)
    resources = {
        "adetailer_models": ["face_yolov8n.pt", "face_yolov8s.pt", "hand_yolov8n.pt"],
        "models": ["base-model.safetensors", "juggernautXL_ragnarokBy.safetensors"],
        "samplers": ["Euler a", "DPM++ 2M Karras"],
    }

    card.apply_webui_resources(resources)

    assert "face_yolov8s.pt" in tuple(card._face_model_combo["values"])
    assert "hand_yolov8n.pt" in tuple(card._hands_model_combo["values"])
    assert "juggernautXL_ragnarokBy.safetensors" in tuple(card._stage_model_combo["values"])
    assert "DPM++ 2M Karras" in tuple(card._sampler_combo["values"])


@pytest.mark.gui
def test_adetailer_stage_card_watchables_include_new_hand_controls(tk_root: tk.Tk) -> None:
    card = ADetailerStageCardV2(tk_root)

    watchable = list(card.watchable_vars())

    assert card.stage_model_override_var in watchable
    assert card.enable_face_pass_var in watchable
    assert card.enable_hands_pass_var in watchable
    assert card.hands_inpaint_masked_var in watchable
    assert card.hands_inpaint_width_var in watchable
    assert card.hands_inpaint_height_var in watchable
