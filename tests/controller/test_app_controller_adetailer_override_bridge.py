from src.controller.app_controller import AppController


def test_build_stage_overrides_from_current_config_preserves_adetailer_pass_local_fields() -> None:
    controller = AppController.__new__(AppController)

    current_config = {
        "adetailer": {
            "adetailer_enabled": True,
            "adetailer_checkpoint_model": "juggernautXL_ragnarokBy.safetensors",
            "adetailer_model": "mediapipe_face_full",
            "adetailer_confidence": 0.29,
            "adetailer_denoise": 0.13,
            "adetailer_steps": 7,
            "adetailer_cfg": 4.0,
            "adetailer_sampler": "DPM++ 2M",
            "adetailer_scheduler": "inherit",
            "enable_face_pass": False,
            "ad_inpaint_only_masked": False,
            "ad_use_inpaint_width_height": True,
            "ad_inpaint_width": 768,
            "ad_inpaint_height": 1024,
            "adetailer_hands_model": "hand_yolov8s.pt",
            "enable_hands_pass": False,
            "ad_hands_enabled": False,
            "ad_hands_inpaint_only_masked": True,
            "ad_hands_use_inpaint_width_height": True,
            "ad_hands_inpaint_width": 768,
            "ad_hands_inpaint_height": 1024,
        }
    }

    bundle = controller._build_stage_overrides_from_current_config(current_config)

    assert bundle.adetailer is not None
    assert bundle.adetailer.checkpoint_model == "juggernautXL_ragnarokBy.safetensors"
    assert bundle.adetailer.enable_face_pass is False
    assert bundle.adetailer.use_inpaint_width_height is True
    assert bundle.adetailer.inpaint_width == 768
    assert bundle.adetailer.inpaint_height == 1024
    assert bundle.adetailer.hands_model == "hand_yolov8s.pt"
    assert bundle.adetailer.enable_hands_pass is False
    assert bundle.adetailer.hands_inpaint_only_masked is True
    assert bundle.adetailer.hands_use_inpaint_width_height is True
    assert bundle.adetailer.hands_inpaint_width == 768
    assert bundle.adetailer.hands_inpaint_height == 1024
