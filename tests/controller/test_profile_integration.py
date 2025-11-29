import pytest
from unittest.mock import patch, MagicMock
from src.controller.pipeline_controller import PipelineController
from src.learning.model_profiles import SuggestedPreset

def make_suggested_preset():
    return SuggestedPreset(
        sampler="DPM++ 2M Karras",
        scheduler="Karras",
        steps=40,
        cfg=7.0,
        resolution=(1280, 1280),
        lora_weights={"TestLora": 0.8},
        source="internet_prior",
        preset_id="best"
    )

def test_build_pipeline_config_with_profiles_applies_suggested_preset():
    controller = PipelineController()
    with patch("src.learning.model_profiles.find_model_profile_for_checkpoint", return_value=MagicMock()), \
         patch("src.learning.model_profiles.find_lora_profile_for_name", return_value=MagicMock()), \
         patch("src.learning.model_profiles.suggest_preset_for", return_value=make_suggested_preset()):
        config = controller.build_pipeline_config_with_profiles(
            base_model_name="TestModel",
            lora_names=["TestLora"],
            user_overrides={}
        )
        assert config["txt2img"]["sampler_name"] == "DPM++ 2M Karras"
        assert config["txt2img"]["steps"] == 40
        assert config["txt2img"]["cfg_scale"] == 7.0
        assert (config["txt2img"]["width"], config["txt2img"]["height"]) == (1280, 1280)
        assert any(lora["name"] == "TestLora" and lora["weight"] == 0.8 for lora in config["txt2img"]["loras"])

def test_build_pipeline_config_with_profiles_respects_user_overrides():
    controller = PipelineController()
    with patch("src.learning.model_profiles.find_model_profile_for_checkpoint", return_value=MagicMock()), \
         patch("src.learning.model_profiles.find_lora_profile_for_name", return_value=MagicMock()), \
         patch("src.learning.model_profiles.suggest_preset_for", return_value=make_suggested_preset()):
        config = controller.build_pipeline_config_with_profiles(
            base_model_name="TestModel",
            lora_names=["TestLora"],
            user_overrides={"cfg": 5.5, "steps": 22}
        )
        assert config["txt2img"]["cfg_scale"] == 5.5
        assert config["txt2img"]["steps"] == 22
        assert config["txt2img"]["sampler_name"] == "DPM++ 2M Karras"  # unchanged

def test_build_pipeline_config_with_profiles_falls_back_without_profiles():
    controller = PipelineController()
    with patch("src.learning.model_profiles.find_model_profile_for_checkpoint", return_value=None), \
         patch("src.learning.model_profiles.find_lora_profile_for_name", return_value=None), \
         patch("src.learning.model_profiles.suggest_preset_for", return_value=None):
        config = controller.build_pipeline_config_with_profiles(
            base_model_name="TestModel",
            lora_names=["TestLora"],
            user_overrides={}
        )
        # Should match default config values (example: sampler, steps, cfg)
        assert "txt2img" in config
        assert "sampler_name" in config["txt2img"]
        assert "steps" in config["txt2img"]
        assert "cfg_scale" in config["txt2img"]
