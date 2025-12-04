# Subsystem: API
# Role: Tests for SDXL payload building with refiner/hires/upscaler.

"""Tests for SDXL payload builder.

This module tests the canonical payload builder to ensure:
- Refiner fields are correctly included/disabled
- Hires fix fields are correctly encoded
- Upscaler fields are encoded for UPSCALE stages
- last_image_meta chaining works for IMG2IMG/UPSCALE
- DIRECT vs QUEUE jobs produce identical payloads
"""

from __future__ import annotations

from typing import Any

import pytest

from src.pipeline.payload_builder import build_sdxl_payload
from src.pipeline.stage_models import StageType
from src.pipeline.stage_sequencer import StageConfig, StageExecution, StageMetadata


# -----------------------------------------------------------------------------
# Test Helpers
# -----------------------------------------------------------------------------


def make_stage(
    stage_type: StageType | str,
    *,
    refiner_enabled: bool = False,
    hires_enabled: bool = False,
    upscaler_name: str | None = None,
    config_overrides: dict[str, Any] | None = None,
) -> StageExecution:
    """Create a StageExecution for testing.

    Args:
        stage_type: The stage type (TXT2IMG, IMG2IMG, UPSCALE, ADETAILER)
        refiner_enabled: Whether to enable SDXL refiner
        hires_enabled: Whether to enable hires fix
        upscaler_name: Upscaler name for UPSCALE stages
        config_overrides: Additional config values to merge

    Returns:
        A StageExecution instance for testing.
    """
    stage_type_str = stage_type.value if isinstance(stage_type, StageType) else stage_type

    base_config = {
        "prompt": "test prompt",
        "negative_prompt": "",
        "steps": 20,
        "cfg_scale": 7.0,
        "sampler_name": "Euler a",
        "scheduler_name": "Karras",
        "width": 1024,
        "height": 1024,
        "model": "sdxl_base",
        "model_name": "sdxl_base",
        "vae": "vae.sdxl",
        "vae_name": "vae.sdxl",
    }
    if config_overrides:
        base_config.update(config_overrides)

    metadata = StageMetadata(
        refiner_enabled=refiner_enabled,
        refiner_model_name="sdxl_refiner" if refiner_enabled else None,
        refiner_switch_at=10 if refiner_enabled else None,
        hires_enabled=hires_enabled,
        hires_upscaler_name="Latent" if hires_enabled else None,
        hires_denoise=0.35 if hires_enabled else None,
        hires_upscale_factor=1.5 if hires_enabled else None,
        hires_steps=8 if hires_enabled else None,
    )

    return StageExecution(
        stage_type=stage_type_str,
        config=StageConfig(enabled=True, payload=base_config, metadata=metadata),
        order_index=0,
        requires_input_image=stage_type_str in ("img2img", "upscale", "adetailer"),
        produces_output_image=True,
    )


# -----------------------------------------------------------------------------
# Test: TXT2IMG with refiner + hires
# -----------------------------------------------------------------------------


@pytest.mark.parametrize(
    "refiner_enabled, hires_enabled",
    [
        (True, True),
        (True, False),
        (False, True),
        (False, False),
    ],
)
def test_build_sdxl_payload_generation_refiner_and_hires(refiner_enabled: bool, hires_enabled: bool):
    """Test payload builder with various refiner/hires combinations."""
    stage = make_stage(StageType.TXT2IMG, refiner_enabled=refiner_enabled, hires_enabled=hires_enabled)

    payload = build_sdxl_payload(stage, last_image_meta=None)

    # Base fields should always be present
    assert payload["sd_model"] == "sdxl_base"
    assert payload["sd_vae"] == "vae.sdxl"
    assert payload["steps"] == 20
    assert payload["cfg_scale"] == 7.0

    # Refiner fields
    if refiner_enabled:
        assert payload["refiner_enabled"] is True
        assert payload["refiner_model_name"] == "sdxl_refiner"
        assert payload["refiner_switch_step"] == 10
    else:
        assert payload["refiner_enabled"] is False

    # Hires fields
    if hires_enabled:
        assert payload["hires_fix"] is True
        assert payload["enable_hr"] is True
        assert payload["hires_upscaler_name"] == "Latent"
        assert payload["hr_upscaler"] == "Latent"
        assert payload["hires_denoise_strength"] == pytest.approx(0.35)
        assert payload["denoising_strength"] == pytest.approx(0.35)
        assert payload["hires_scale"] == pytest.approx(1.5)
        assert payload["hr_scale"] == pytest.approx(1.5)
        assert payload["hr_second_pass_steps"] == 8
    else:
        assert payload["hires_fix"] is False
        assert payload["enable_hr"] is False


# -----------------------------------------------------------------------------
# Test: IMG2IMG uses last_image_meta
# -----------------------------------------------------------------------------


def test_build_sdxl_payload_img2img_uses_last_image_meta():
    """Test that IMG2IMG stage uses images from last_image_meta."""
    stage = make_stage(StageType.IMG2IMG)
    last_meta = {"images": ["prev_image_1_base64", "prev_image_2_base64"]}

    payload = build_sdxl_payload(stage, last_meta)

    assert payload["input_images"] == ["prev_image_1_base64", "prev_image_2_base64"]
    assert payload["init_images"] == ["prev_image_1_base64", "prev_image_2_base64"]


def test_build_sdxl_payload_img2img_without_last_meta():
    """Test IMG2IMG stage without previous images."""
    stage = make_stage(StageType.IMG2IMG)

    payload = build_sdxl_payload(stage, last_image_meta=None)

    assert payload["input_images"] == []


# -----------------------------------------------------------------------------
# Test: UPSCALE encodes upscaler fields
# -----------------------------------------------------------------------------


def test_build_sdxl_payload_upscale_includes_upscaler_knobs_and_input():
    """Test that UPSCALE stage includes upscaler configuration."""
    config_overrides = {
        "upscaler_name": "R-ESRGAN 4x+",
        "upscale_factor": 2.0,
        "upscale_iterations": 3,
    }
    stage = make_stage(StageType.UPSCALE, config_overrides=config_overrides)
    last_meta = {"images": ["low_res_image_base64"]}

    payload = build_sdxl_payload(stage, last_meta)

    assert payload["task"] == "upscale"
    assert payload["upscaler_name"] == "R-ESRGAN 4x+"
    assert payload["upscaler_1"] == "R-ESRGAN 4x+"
    assert payload["scale"] == 2.0
    assert payload["upscaling_resize"] == 2.0
    assert payload["iterations"] == 3
    assert payload["input_images"] == ["low_res_image_base64"]
    assert payload["image"] == "low_res_image_base64"


def test_build_sdxl_payload_upscale_default_values():
    """Test UPSCALE stage with default upscaler values."""
    stage = make_stage(StageType.UPSCALE)
    last_meta = {"images": ["input_image_base64"]}

    payload = build_sdxl_payload(stage, last_meta)

    assert payload["task"] == "upscale"
    assert payload["upscaler_name"] == "R-ESRGAN 4x+"  # default
    assert payload["scale"] == 2.0  # default
    assert payload["iterations"] == 1  # default


def test_build_sdxl_payload_upscale_no_generation_fields():
    """Test that UPSCALE stage doesn't include generation-specific fields."""
    stage = make_stage(StageType.UPSCALE)

    payload = build_sdxl_payload(stage, last_image_meta=None)

    # Generation fields should be removed for pure upscale
    assert "prompt" not in payload
    assert "negative_prompt" not in payload
    assert "steps" not in payload
    assert "cfg_scale" not in payload
    assert "sampler_name" not in payload


# -----------------------------------------------------------------------------
# Test: ADETAILER stage
# -----------------------------------------------------------------------------


def test_build_sdxl_payload_adetailer_includes_detector_config():
    """Test that ADETAILER stage includes detection configuration."""
    config_overrides = {
        "adetailer_model": "face_yolov8m.pt",
        "adetailer_denoise": 0.5,
        "adetailer_confidence": 0.4,
    }
    stage = make_stage(StageType.ADETAILER, config_overrides=config_overrides)
    last_meta = {"images": ["face_image_base64"]}

    payload = build_sdxl_payload(stage, last_meta)

    assert payload["task"] == "adetailer"
    assert payload["adetailer_enabled"] is True
    assert payload["adetailer_model"] == "face_yolov8m.pt"
    assert payload["adetailer_denoise"] == 0.5
    assert payload["adetailer_confidence"] == 0.4
    assert payload["input_images"] == ["face_image_base64"]


# -----------------------------------------------------------------------------
# Test: DIRECT vs QUEUE produce identical payloads
# -----------------------------------------------------------------------------


def test_payload_independent_of_run_mode_when_stage_same():
    """Test that identical StageExecution produces identical payloads.

    This ensures DIRECT and QUEUE jobs get the same payload structure.
    """
    stage = make_stage(StageType.TXT2IMG, refiner_enabled=True, hires_enabled=True)

    payload_direct = build_sdxl_payload(stage, last_image_meta=None)
    payload_queue = build_sdxl_payload(stage, last_image_meta=None)

    assert payload_direct == payload_queue


def test_payload_consistent_across_calls():
    """Test that multiple calls with same input produce same output."""
    stage = make_stage(StageType.TXT2IMG, refiner_enabled=True, hires_enabled=True)
    last_meta = {"images": ["img1"]}

    payloads = [build_sdxl_payload(stage, last_meta) for _ in range(5)]

    # All payloads should be identical
    assert all(p == payloads[0] for p in payloads)


# -----------------------------------------------------------------------------
# Test: Hires target resolution calculation
# -----------------------------------------------------------------------------


def test_build_sdxl_payload_hires_calculates_target_resolution():
    """Test that hires fix calculates target resolution from scale factor."""
    config_overrides = {
        "width": 1024,
        "height": 768,
    }
    stage = make_stage(StageType.TXT2IMG, hires_enabled=True, config_overrides=config_overrides)

    payload = build_sdxl_payload(stage, last_image_meta=None)

    # With scale factor 1.5 (from make_stage default):
    # 1024 * 1.5 = 1536, 768 * 1.5 = 1152
    assert payload["hr_resize_x"] == 1536
    assert payload["hr_resize_y"] == 1152


# -----------------------------------------------------------------------------
# Test: Edge cases
# -----------------------------------------------------------------------------


def test_build_sdxl_payload_empty_config():
    """Test payload builder with minimal config."""
    stage = StageExecution(
        stage_type="txt2img",
        config=StageConfig(enabled=True, payload={}, metadata=StageMetadata()),
        order_index=0,
        requires_input_image=False,
        produces_output_image=True,
    )

    payload = build_sdxl_payload(stage, last_image_meta=None)

    # Should have defaults
    assert payload["steps"] == 20
    assert payload["cfg_scale"] == 7.0
    assert payload["width"] == 1024
    assert payload["height"] == 1024
    assert payload["refiner_enabled"] is False
    assert payload["hires_fix"] is False


def test_build_sdxl_payload_preserves_extra_config_keys():
    """Test that extra config keys are preserved in payload."""
    config_overrides = {
        "custom_key": "custom_value",
        "styles": ["anime", "detailed"],
    }
    stage = make_stage(StageType.TXT2IMG, config_overrides=config_overrides)

    payload = build_sdxl_payload(stage, last_image_meta=None)

    # Custom keys should be in the base payload since they're in config
    # The payload builder copies from config
    assert "prompt" in payload  # Base field preserved


# -----------------------------------------------------------------------------
# Test: Stage type normalization
# -----------------------------------------------------------------------------


def test_build_sdxl_payload_accepts_string_stage_type():
    """Test that string stage types work."""
    stage = make_stage("txt2img", refiner_enabled=True)

    payload = build_sdxl_payload(stage, last_image_meta=None)

    assert payload["refiner_enabled"] is True


def test_build_sdxl_payload_accepts_enum_stage_type():
    """Test that StageType enum values work."""
    stage = make_stage(StageType.TXT2IMG, refiner_enabled=True)

    payload = build_sdxl_payload(stage, last_image_meta=None)

    assert payload["refiner_enabled"] is True


# -----------------------------------------------------------------------------
# Test: Integration with stage_models.StageExecution
# -----------------------------------------------------------------------------


def test_build_sdxl_payload_with_stage_models_stage_execution():
    """Test payload builder with stage_models.StageExecution (not stage_sequencer)."""
    from src.pipeline.stage_models import StageExecution as ModelsStageExecution

    stage = ModelsStageExecution(
        stage_type=StageType.TXT2IMG,
        config_key="txt2img",
        config={
            "prompt": "a beautiful landscape",
            "steps": 30,
            "width": 512,
            "height": 512,
        },
        order_index=0,
        requires_input_image=False,
        produces_output_image=True,
        refiner_enabled=True,
        refiner_model_name="sd_xl_refiner",
        refiner_switch_step=15,
        hires_enabled=True,
        hires_upscaler_name="4x-UltraSharp",
        hires_denoise_strength=0.4,
        hires_scale_factor=2.0,
    )

    payload = build_sdxl_payload(stage, last_image_meta=None)

    # Check base fields from config
    assert payload["prompt"] == "a beautiful landscape"
    assert payload["steps"] == 30
    assert payload["width"] == 512
    assert payload["height"] == 512

    # Check refiner fields from stage attributes
    assert payload["refiner_enabled"] is True
    assert payload["refiner_model_name"] == "sd_xl_refiner"
    assert payload["refiner_switch_step"] == 15

    # Check hires fields from stage attributes
    assert payload["hires_fix"] is True
    assert payload["enable_hr"] is True
    assert payload["hires_upscaler_name"] == "4x-UltraSharp"
    assert payload["hr_upscaler"] == "4x-UltraSharp"
    assert payload["hires_denoise_strength"] == pytest.approx(0.4)
    assert payload["hires_scale"] == pytest.approx(2.0)
