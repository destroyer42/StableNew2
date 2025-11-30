from __future__ import annotations

import tkinter as tk

import pytest

from src.gui.stage_cards_v2.adetailer_stage_card_v2 import ADetailerStageCardV2


@pytest.mark.gui
def test_adetailer_stage_card_roundtrip(tk_root: tk.Tk) -> None:
    card = ADetailerStageCardV2(tk_root)
    sample = {
        "adetailer_model": "adetailer_v1.pt",
        "detector": "hand",
        "adetailer_confidence": 0.45,
        "max_detections": 12,
        "mask_blur": 6,
        "mask_merge_mode": "replace",
        "only_faces": False,
        "only_hands": True,
    }

    card.load_from_dict(sample)
    exported = card.to_config_dict()

    assert exported["adetailer_model"] == sample["adetailer_model"]
    assert exported["detector"] == sample["detector"]
    assert abs(exported["adetailer_confidence"] - sample["adetailer_confidence"]) < 1e-6
    assert exported["max_detections"] == sample["max_detections"]
    assert exported["mask_merge_mode"] == sample["mask_merge_mode"]
    assert exported["only_faces"] == sample["only_faces"]
    assert exported["only_hands"] == sample["only_hands"]


@pytest.mark.gui
def test_adetailer_stage_card_applies_webui_resources(tk_root: tk.Tk) -> None:
    card = ADetailerStageCardV2(tk_root)
    resources = {
        "adetailer_models": ["face_yolov8n.pt", "adetailer_v2.pt"],
        "adetailer_detectors": ["face", "hand"],
    }

    card.apply_webui_resources(resources)

    assert tuple(card._model_combo["values"]) == tuple(resources["adetailer_models"])
    assert tuple(card._detector_combo["values"]) == tuple(resources["adetailer_detectors"])
    assert card.model_var.get() == "face_yolov8n.pt"
    assert card.detector_var.get() == "face"
