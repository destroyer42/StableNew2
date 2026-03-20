from __future__ import annotations

from src.pipeline.config_normalizer import normalize_pipeline_config, normalize_stage_payload_config


def test_normalize_pipeline_config_promotes_flat_generation_keys() -> None:
    config = {
        "prompt": "flat prompt",
        "negative_prompt": "flat negative",
        "model_name": "flat-model",
        "sampler": "DPM++ 2M",
        "scheduler_name": "Karras",
        "steps": 28,
        "cfg_scale": 6.5,
        "width": 896,
        "height": 1152,
    }

    normalized = normalize_pipeline_config(config)

    assert normalized["txt2img"]["model"] == "flat-model"
    assert normalized["txt2img"]["sampler_name"] == "DPM++ 2M"
    assert normalized["txt2img"]["scheduler"] == "Karras"
    assert normalized["txt2img"]["width"] == 896
    assert normalized["pipeline"]["txt2img_enabled"] is True


def test_normalize_stage_payload_config_handles_hires_and_upscale_aliases() -> None:
    config = {
        "enable_hr": True,
        "hr_scale": 1.8,
        "hr_upscaler": "Latent",
        "denoising_strength": 0.35,
        "hr_second_pass_steps": 12,
        "upscaler_name": "4x-UltraSharp",
        "scale": 2.0,
        "iterations": 3,
    }

    normalized = normalize_stage_payload_config(config, stage_type="upscale")

    assert normalized["hires_enabled"] is True
    assert normalized["hires_scale_factor"] == 1.8
    assert normalized["hires_upscaler_name"] == "Latent"
    assert normalized["hires_denoise"] == 0.35
    assert normalized["hires_steps"] == 12
    assert normalized["upscaler"] == "4x-UltraSharp"
    assert normalized["upscale_factor"] == 2.0
    assert normalized["upscale_iterations"] == 3


def test_normalize_pipeline_config_moves_disabled_txt2img_hires_settings_to_hires_fix() -> None:
    config = {
        "txt2img": {
            "enable_hr": False,
            "hr_scale": 1.8,
            "hr_upscaler": "Latent",
            "denoising_strength": 0.35,
            "hr_second_pass_steps": 12,
        }
    }

    normalized = normalize_pipeline_config(config)

    assert normalized["txt2img"]["enable_hr"] is False
    assert "hr_scale" not in normalized["txt2img"]
    assert "hr_upscaler" not in normalized["txt2img"]
    assert "denoising_strength" not in normalized["txt2img"]
    assert "hr_second_pass_steps" not in normalized["txt2img"]
    assert normalized["hires_fix"]["enabled"] is False
    assert normalized["hires_fix"]["upscale_factor"] == 1.8
    assert normalized["hires_fix"]["upscaler_name"] == "Latent"
    assert normalized["hires_fix"]["denoise"] == 0.35
    assert normalized["hires_fix"]["steps"] == 12
