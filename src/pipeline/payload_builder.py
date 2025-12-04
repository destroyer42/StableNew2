# Subsystem: Pipeline
# Role: Canonical payload builder for SDXL stages.

"""Canonical payload builder for SDXL pipeline stages.

This module provides a single entrypoint for building WebUI payloads from
StageExecution objects. All SDXL stage calls (direct and queued) should
use build_sdxl_payload() to ensure consistent behavior.

Key responsibilities:
- Merge base stage config with refiner/hires/upscaler metadata
- Handle input image chaining via last_image_meta
- Produce payloads directly consumable by ApiClient.generate_images
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any, Protocol

from src.pipeline.stage_models import StageType


class StageExecutionLike(Protocol):
    """Protocol for stage execution objects.

    This is a structural type hint - any object with these attributes works:
    - stage_type: str | StageType
    - config: Mapping or object with payload attribute

    Optional attributes:
    - refiner_enabled, refiner_model_name, refiner_switch_step
    - hires_enabled, hires_upscaler_name, hires_denoise_strength, hires_scale_factor
    """

    stage_type: str | StageType
    config: Any


def build_sdxl_payload(
    stage: StageExecutionLike,
    last_image_meta: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """Build a complete WebUI payload from a StageExecution.

    This is the canonical function for building SDXL payloads. All stage
    execution paths (direct and queued) should use this function.

    Args:
        stage: A StageExecution (or compatible object with stage_type, config, etc.)
        last_image_meta: Optional metadata from previous stage, including 'images' for chaining.

    Returns:
        A dict payload ready to pass to ApiClient.generate_images.
    """
    # Extract stage type and config
    stage_type = _normalize_stage_type(stage.stage_type)
    config = _extract_config(stage)

    # Build base payload
    payload = _build_base_payload(config)

    # Apply stage-specific augmentations
    if stage_type in (StageType.TXT2IMG, StageType.IMG2IMG):
        _apply_refiner_fields(payload, stage)
        _apply_hires_fields(payload, stage, config)

    if stage_type == StageType.IMG2IMG:
        _apply_input_images(payload, last_image_meta)

    if stage_type == StageType.UPSCALE:
        _apply_upscale_fields(payload, config, last_image_meta)

    if stage_type == StageType.ADETAILER:
        _apply_adetailer_fields(payload, config, last_image_meta)

    return payload


def _normalize_stage_type(stage_type: str | StageType) -> StageType:
    """Convert string stage type to StageType enum."""
    if isinstance(stage_type, StageType):
        return stage_type
    return StageType(stage_type)


def _extract_config(stage: StageExecutionLike) -> dict[str, Any]:
    """Extract the config dict from a stage, handling various formats."""
    # Handle stage_sequencer.StageExecution which has config.payload
    if hasattr(stage, "config") and hasattr(stage.config, "payload"):
        return dict(stage.config.payload or {})
    # Handle stage_models.StageExecution which has config as a Mapping
    if hasattr(stage, "config") and isinstance(stage.config, Mapping):
        return dict(stage.config)
    return {}


def _build_base_payload(config: dict[str, Any]) -> dict[str, Any]:
    """Build the base payload structure with common fields."""
    return {
        "prompt": config.get("prompt", ""),
        "negative_prompt": config.get("negative_prompt", ""),
        "steps": config.get("steps", 20),
        "cfg_scale": config.get("cfg_scale", 7.0),
        "sampler_name": config.get("sampler_name", "Euler a"),
        "scheduler": config.get("scheduler") or config.get("scheduler_name"),
        "width": config.get("width", 1024),
        "height": config.get("height", 1024),
        "seed": config.get("seed", -1),
        "subseed": config.get("subseed", -1),
        "subseed_strength": config.get("subseed_strength", 0.0),
        # model / VAE
        "sd_model": config.get("model") or config.get("model_name"),
        "sd_vae": config.get("vae") or config.get("vae_name"),
        # input images placeholder
        "input_images": [],
        # batch configuration
        "batch_size": config.get("batch_size", 1),
        "n_iter": config.get("n_iter", 1),
        # clip skip
        "clip_skip": config.get("clip_skip", 2),
    }


def _apply_refiner_fields(payload: dict[str, Any], stage: StageExecutionLike) -> None:
    """Apply SDXL refiner fields to the payload.

    Fields applied:
    - refiner_enabled: bool (explicit, not inferred)
    - refiner_model_name: str | None
    - refiner_switch_step: int | None
    """
    # Check for refiner fields on stage directly
    refiner_enabled = getattr(stage, "refiner_enabled", False)

    # Also check in config metadata if present
    if not refiner_enabled and hasattr(stage, "config"):
        metadata = getattr(stage.config, "metadata", None)
        if metadata:
            if hasattr(metadata, "refiner_enabled"):
                refiner_enabled = getattr(metadata, "refiner_enabled", False)
            elif isinstance(metadata, dict):
                refiner_enabled = metadata.get("refiner_enabled", False)

    payload["refiner_enabled"] = bool(refiner_enabled)

    if refiner_enabled:
        # Get refiner model name
        refiner_model = getattr(stage, "refiner_model_name", None)
        if not refiner_model and hasattr(stage, "config"):
            metadata = getattr(stage.config, "metadata", None)
            if metadata:
                if hasattr(metadata, "refiner_model_name"):
                    refiner_model = getattr(metadata, "refiner_model_name", None)
                elif isinstance(metadata, dict):
                    refiner_model = metadata.get("refiner_model_name")

        if refiner_model:
            payload["refiner_model_name"] = refiner_model

        # Get refiner switch step
        refiner_switch = getattr(stage, "refiner_switch_step", None)
        if refiner_switch is None and hasattr(stage, "config"):
            metadata = getattr(stage.config, "metadata", None)
            if metadata:
                if hasattr(metadata, "refiner_switch_at"):
                    refiner_switch = getattr(metadata, "refiner_switch_at", None)
                elif isinstance(metadata, dict):
                    refiner_switch = metadata.get("refiner_switch_at") or metadata.get("refiner_switch_step")

        if refiner_switch is not None:
            payload["refiner_switch_step"] = refiner_switch


def _apply_hires_fields(
    payload: dict[str, Any],
    stage: StageExecutionLike,
    config: dict[str, Any],
) -> None:
    """Apply hires fix fields to the payload.

    Fields applied:
    - hires_fix / enable_hr: bool (explicit)
    - hires_upscaler_name / hr_upscaler: str | None
    - hires_denoise_strength / denoising_strength: float | None
    - hires_scale / hr_scale: float | None
    - hr_second_pass_steps: int | None
    - hr_resize_x, hr_resize_y: int (optional, computed from scale)
    """
    # Check for hires enabled on stage directly
    hires_enabled = getattr(stage, "hires_enabled", False)

    # Also check in config metadata if present
    if not hires_enabled and hasattr(stage, "config"):
        metadata = getattr(stage.config, "metadata", None)
        if metadata:
            if hasattr(metadata, "hires_enabled"):
                hires_enabled = getattr(metadata, "hires_enabled", False)
            elif isinstance(metadata, dict):
                hires_enabled = metadata.get("hires_enabled", False)

    # Also check config directly for enable_hr
    if not hires_enabled:
        hires_enabled = config.get("enable_hr", False) or config.get("hires_enabled", False)

    payload["hires_fix"] = bool(hires_enabled)
    payload["enable_hr"] = bool(hires_enabled)

    if hires_enabled:
        # Get upscaler name
        upscaler_name = getattr(stage, "hires_upscaler_name", None)
        if not upscaler_name and hasattr(stage, "config"):
            metadata = getattr(stage.config, "metadata", None)
            if metadata:
                if hasattr(metadata, "hires_upscaler_name"):
                    upscaler_name = getattr(metadata, "hires_upscaler_name", None)
                elif isinstance(metadata, dict):
                    upscaler_name = metadata.get("hires_upscaler_name")
        if not upscaler_name:
            upscaler_name = config.get("hr_upscaler") or config.get("hires_upscaler_name", "Latent")

        if upscaler_name:
            payload["hires_upscaler_name"] = upscaler_name
            payload["hr_upscaler"] = upscaler_name

        # Get denoise strength
        denoise = getattr(stage, "hires_denoise_strength", None)
        if denoise is None and hasattr(stage, "config"):
            metadata = getattr(stage.config, "metadata", None)
            if metadata:
                if hasattr(metadata, "hires_denoise"):
                    denoise = getattr(metadata, "hires_denoise", None)
                elif isinstance(metadata, dict):
                    denoise = metadata.get("hires_denoise") or metadata.get("hires_denoise_strength")
        if denoise is None:
            denoise = config.get("denoising_strength") or config.get("hires_denoise")

        if denoise is not None:
            payload["hires_denoise_strength"] = float(denoise)
            payload["denoising_strength"] = float(denoise)

        # Get scale factor
        scale_factor = getattr(stage, "hires_scale_factor", None)
        if scale_factor is None and hasattr(stage, "config"):
            metadata = getattr(stage.config, "metadata", None)
            if metadata:
                if hasattr(metadata, "hires_upscale_factor"):
                    scale_factor = getattr(metadata, "hires_upscale_factor", None)
                elif isinstance(metadata, dict):
                    scale_factor = metadata.get("hires_upscale_factor") or metadata.get("hires_scale_factor")
        if scale_factor is None:
            scale_factor = config.get("hr_scale") or config.get("hires_scale_factor")

        if scale_factor is not None:
            payload["hires_scale"] = float(scale_factor)
            payload["hr_scale"] = float(scale_factor)

            # Compute target resolution if not explicitly set
            base_width = payload.get("width", 1024)
            base_height = payload.get("height", 1024)
            payload["hr_resize_x"] = int(base_width * float(scale_factor))
            payload["hr_resize_y"] = int(base_height * float(scale_factor))

        # Get hires steps
        hires_steps = None
        if hasattr(stage, "config"):
            metadata = getattr(stage.config, "metadata", None)
            if metadata:
                if hasattr(metadata, "hires_steps"):
                    hires_steps = getattr(metadata, "hires_steps", None)
                elif isinstance(metadata, dict):
                    hires_steps = metadata.get("hires_steps")
        if hires_steps is None:
            hires_steps = config.get("hr_second_pass_steps") or config.get("hires_steps")

        if hires_steps is not None:
            payload["hr_second_pass_steps"] = int(hires_steps)
    else:
        # Explicitly set hires fields to disabled defaults
        payload["hr_scale"] = 1.0
        payload["hr_upscaler"] = "None"
        payload["denoising_strength"] = 0.0
        payload["hr_second_pass_steps"] = 0


def _apply_input_images(
    payload: dict[str, Any],
    last_image_meta: Mapping[str, Any] | None,
) -> None:
    """Apply input images from previous stage for img2img-like stages."""
    if last_image_meta is None:
        return

    images = last_image_meta.get("images") or []
    if images:
        payload["input_images"] = list(images)
        # Also set init_images for compatibility
        payload["init_images"] = list(images)


def _apply_upscale_fields(
    payload: dict[str, Any],
    config: dict[str, Any],
    last_image_meta: Mapping[str, Any] | None,
) -> None:
    """Apply upscaler-specific fields for UPSCALE stages.

    Fields applied:
    - task: "upscale"
    - upscaler_name: str
    - scale: float
    - iterations: int
    - input_images: from previous stage

    Note: Refiner/hires fields are NOT applied to pure upscale stages.
    """
    payload["task"] = "upscale"
    payload["upscaler_name"] = config.get("upscaler_name") or config.get("upscaler", "R-ESRGAN 4x+")
    payload["scale"] = config.get("upscale_factor") or config.get("scale", 2.0)
    payload["iterations"] = config.get("upscale_iterations") or config.get("iterations", 1)

    # Also include upscaling_resize for API compatibility
    payload["upscaling_resize"] = payload["scale"]
    payload["upscaler_1"] = payload["upscaler_name"]

    # Use prior images as input
    if last_image_meta:
        images = last_image_meta.get("images") or []
        if images:
            payload["input_images"] = list(images)
            # For extra-single-image API, use 'image' key
            if len(images) > 0:
                payload["image"] = images[0]

    # Clear generation-specific fields that don't apply to upscale
    for key in ["prompt", "negative_prompt", "steps", "cfg_scale", "sampler_name"]:
        payload.pop(key, None)


def _apply_adetailer_fields(
    payload: dict[str, Any],
    config: dict[str, Any],
    last_image_meta: Mapping[str, Any] | None,
) -> None:
    """Apply ADetailer-specific fields.

    ADetailer uses the input image and applies face/body detection and inpainting.
    """
    payload["task"] = "adetailer"

    # ADetailer configuration
    payload["adetailer_enabled"] = True
    payload["adetailer_model"] = config.get("adetailer_model") or config.get("ad_model", "face_yolov8n.pt")
    payload["adetailer_denoise"] = config.get("adetailer_denoise") or config.get("ad_denoising_strength", 0.4)
    payload["adetailer_confidence"] = config.get("adetailer_confidence") or config.get("ad_confidence", 0.3)

    # Use prior images as input
    if last_image_meta:
        images = last_image_meta.get("images") or []
        if images:
            payload["input_images"] = list(images)
            payload["init_images"] = list(images)


__all__ = [
    "build_sdxl_payload",
    "StageExecutionLike",
]
