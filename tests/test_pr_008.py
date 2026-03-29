from __future__ import annotations

from src.gui.stage_cards_v2.adetailer_stage_card_v2 import ADetailerStageCardV2


def test_pr_008_adetailer_card_defaults(tk_root) -> None:
    try:
        card = ADetailerStageCardV2(tk_root)

        assert card.enable_face_pass_var.get() is True
        assert card.enable_hands_pass_var.get() is False
        assert card.face_model_var.get() == "face_yolov8n.pt"
        assert card.hands_model_var.get() == "hand_yolov8n.pt"
        assert card.face_padding_var.get() == 32
        assert card.hands_padding_var.get() == 16
        assert card.mask_filter_method_var.get() == "Area"
        assert card.scheduler_var.get() == "inherit"
    finally:
        card.destroy()


def test_pr_008_adetailer_card_exports_two_pass_config(tk_root) -> None:
    try:
        card = ADetailerStageCardV2(tk_root)
        card.enable_hands_pass_var.set(True)
        card.hands_model_var.set("hand_yolov8s.pt")
        card.hands_inpaint_masked_var.set(False)
        card.hands_scheduler_var.set("Karras")
        card.stage_model_override_var.set("juggernautXL_ragnarokBy.safetensors")

        config = card.to_config_dict()

        assert config["enable_hands_pass"] is True
        assert config["adetailer_hands_model"] == "hand_yolov8s.pt"
        assert config["ad_hands_inpaint_only_masked"] is False
        assert config["adetailer_hands_scheduler"] == "Karras"
        assert config["adetailer_checkpoint_model"] == "juggernautXL_ragnarokBy.safetensors"
    finally:
        card.destroy()
