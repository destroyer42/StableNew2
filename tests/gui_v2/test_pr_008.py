from __future__ import annotations

import tkinter as tk

from src.gui.stage_cards_v2.adetailer_stage_card_v2 import ADetailerStageCardV2


def test_pr_008_gui_card_smoke() -> None:
    root = tk.Tk()
    root.withdraw()
    try:
        card = ADetailerStageCardV2(root)

        assert card._face_model_combo is not None
        assert card._hands_model_combo is not None
        assert card._stage_model_combo is not None
        assert "inherit" in tuple(card._scheduler_combo["values"])
        assert "Karras" in tuple(card._scheduler_combo["values"])
    finally:
        root.destroy()


def test_pr_008_load_roundtrip() -> None:
    root = tk.Tk()
    root.withdraw()
    try:
        card = ADetailerStageCardV2(root)
        card.load_from_dict(
            {
                "enable_face_pass": False,
                "enable_hands_pass": True,
                "adetailer_model": "mediapipe_face_full",
                "adetailer_hands_model": "hand_yolov8s.pt",
                "adetailer_scheduler": "Use same scheduler",
                "adetailer_hands_scheduler": "Exponential",
                "ad_hands_inpaint_only_masked": False,
            }
        )

        exported = card.to_config_dict()

        assert card.enable_face_pass_var.get() is False
        assert card.enable_hands_pass_var.get() is True
        assert exported["adetailer_model"] == "mediapipe_face_full"
        assert exported["adetailer_hands_model"] == "hand_yolov8s.pt"
        assert exported["adetailer_scheduler"] == "inherit"
        assert exported["adetailer_hands_scheduler"] == "Exponential"
        assert exported["ad_hands_inpaint_only_masked"] is False
    finally:
        root.destroy()
