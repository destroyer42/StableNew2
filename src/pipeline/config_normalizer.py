from __future__ import annotations

from collections.abc import Mapping
from copy import deepcopy
from typing import Any

from src.pipeline.config_contract_v26 import extract_execution_config


_COMMON_TOP_LEVEL_KEYS = {
    "prompt",
    "negative_prompt",
    "lora_strengths",
    "loras",
    "steps",
    "cfg_scale",
    "sampler_name",
    "sampler",
    "scheduler",
    "scheduler_name",
    "width",
    "height",
    "seed",
    "subseed",
    "subseed_strength",
    "batch_size",
    "n_iter",
    "clip_skip",
    "model",
    "model_name",
    "sd_model",
    "vae",
    "vae_name",
    "sd_vae",
    "enable_hr",
    "hires_enabled",
    "hr_scale",
    "hires_scale_factor",
    "hr_upscaler",
    "hires_upscaler_name",
    "denoising_strength",
    "hires_denoise",
    "hires_denoise_strength",
    "hr_second_pass_steps",
    "hires_steps",
    "refiner_enabled",
    "use_refiner",
    "refiner_model_name",
    "refiner_checkpoint",
    "refiner_switch_at",
    "refiner_switch_step",
    "prompt_optimizer",
}

_UPSCALE_TOP_LEVEL_KEYS = {
    "upscaler",
    "upscaler_name",
    "upscaler_1",
    "upscale_factor",
    "scale",
    "upscaling_resize",
    "upscale_iterations",
    "iterations",
}

_TXT2IMG_HIRES_KEYS = {
    "enable_hr",
    "hires_enabled",
    "hr_scale",
    "hires_scale_factor",
    "hr_upscaler",
    "hires_upscaler_name",
    "denoising_strength",
    "hires_denoise",
    "hires_denoise_strength",
    "hr_second_pass_steps",
    "hires_steps",
    "hr_resize_x",
    "hr_resize_y",
}


def _mapping_dict(value: Any) -> dict[str, Any]:
    if isinstance(value, Mapping):
        return deepcopy(dict(value))
    return {}


def _has_value(value: Any) -> bool:
    return value is not None and not (isinstance(value, str) and value == "")


def _first_value(data: Mapping[str, Any], *keys: str) -> Any:
    for key in keys:
        if key in data and _has_value(data[key]):
            return data[key]
    return None


def _normalize_scheduler(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    if not text:
        return None
    lowered = text.lower()
    if lowered in {"none", "automatic"}:
        return None
    return text


def normalize_stage_payload_config(
    config: Mapping[str, Any] | None,
    *,
    stage_type: str | None = None,
) -> dict[str, Any]:
    """Normalize a stage payload dict into the canonical pipeline shape."""

    normalized = _mapping_dict(config)

    model = _first_value(normalized, "model", "model_name", "sd_model")
    if _has_value(model):
        normalized["model"] = model

    vae = _first_value(normalized, "vae", "vae_name", "sd_vae")
    if _has_value(vae):
        normalized["vae"] = vae

    sampler_name = _first_value(normalized, "sampler_name", "sampler")
    if _has_value(sampler_name):
        normalized["sampler_name"] = sampler_name

    scheduler = _normalize_scheduler(_first_value(normalized, "scheduler", "scheduler_name"))
    if "scheduler" in normalized or "scheduler_name" in normalized or scheduler is not None:
        normalized["scheduler"] = scheduler

    prompt = _first_value(normalized, "prompt")
    if prompt is not None:
        normalized["prompt"] = str(prompt)

    negative_prompt = _first_value(normalized, "negative_prompt")
    if negative_prompt is not None:
        normalized["negative_prompt"] = str(negative_prompt)

    hires_enabled = bool(_first_value(normalized, "hires_enabled", "enable_hr") or False)
    if (
        "hires_enabled" in normalized
        or "enable_hr" in normalized
        or "hr_scale" in normalized
        or "hires_scale_factor" in normalized
        or "hr_upscaler" in normalized
        or "hires_upscaler_name" in normalized
        or "denoising_strength" in normalized
        or "hires_denoise" in normalized
        or "hires_denoise_strength" in normalized
        or "hr_second_pass_steps" in normalized
        or "hires_steps" in normalized
    ):
        normalized["hires_enabled"] = hires_enabled
        normalized["enable_hr"] = hires_enabled

    hires_scale = _first_value(normalized, "hires_scale_factor", "hr_scale")
    if _has_value(hires_scale):
        normalized["hires_scale_factor"] = float(hires_scale)
        normalized["hr_scale"] = float(hires_scale)

    hires_upscaler = _first_value(normalized, "hires_upscaler_name", "hr_upscaler")
    if _has_value(hires_upscaler):
        normalized["hires_upscaler_name"] = hires_upscaler
        normalized["hr_upscaler"] = hires_upscaler

    hires_denoise = _first_value(
        normalized,
        "hires_denoise",
        "hires_denoise_strength",
        "denoising_strength",
    )
    if _has_value(hires_denoise):
        normalized["hires_denoise"] = float(hires_denoise)
        normalized["denoising_strength"] = float(hires_denoise)

    hires_steps = _first_value(normalized, "hires_steps", "hr_second_pass_steps")
    if _has_value(hires_steps):
        normalized["hires_steps"] = int(hires_steps)
        normalized["hr_second_pass_steps"] = int(hires_steps)

    if stage_type == "txt2img" and not hires_enabled:
        for key in (
            "hires_scale_factor",
            "hr_scale",
            "hires_upscaler_name",
            "hr_upscaler",
            "hires_denoise",
            "denoising_strength",
            "hires_steps",
            "hr_second_pass_steps",
            "hr_resize_x",
            "hr_resize_y",
        ):
            normalized.pop(key, None)

    refiner_enabled = bool(_first_value(normalized, "refiner_enabled", "use_refiner") or False)
    if (
        "refiner_enabled" in normalized
        or "use_refiner" in normalized
        or "refiner_model_name" in normalized
        or "refiner_checkpoint" in normalized
        or "refiner_switch_at" in normalized
        or "refiner_switch_step" in normalized
    ):
        normalized["refiner_enabled"] = refiner_enabled

    refiner_model = _first_value(normalized, "refiner_model_name", "refiner_checkpoint")
    if _has_value(refiner_model):
        normalized["refiner_model_name"] = refiner_model

    refiner_switch = _first_value(normalized, "refiner_switch_at", "refiner_switch_step")
    if _has_value(refiner_switch):
        normalized["refiner_switch_at"] = refiner_switch

    if stage_type == "upscale" or any(key in normalized for key in _UPSCALE_TOP_LEVEL_KEYS):
        upscaler = _first_value(normalized, "upscaler", "upscaler_name", "upscaler_1")
        if _has_value(upscaler):
            normalized["upscaler"] = upscaler
            normalized["upscaler_name"] = upscaler

        scale = _first_value(normalized, "upscale_factor", "scale", "upscaling_resize")
        if _has_value(scale):
            normalized["upscale_factor"] = float(scale)

        iterations = _first_value(normalized, "upscale_iterations", "iterations")
        if _has_value(iterations):
            normalized["upscale_iterations"] = int(iterations)

    return normalized


def normalize_pipeline_config(config: Mapping[str, Any] | None) -> dict[str, Any]:
    """Normalize a pipeline config dict into the canonical nested stage shape."""

    execution_config = extract_execution_config(config)
    raw = _mapping_dict(execution_config or config)
    normalized = deepcopy(raw)

    def _merge_stage(section: str, extra_top_level_keys: set[str] | None = None) -> dict[str, Any]:
        merged: dict[str, Any] = {}
        for key in _COMMON_TOP_LEVEL_KEYS:
            if key in raw:
                merged[key] = raw[key]
        if extra_top_level_keys:
            for key in extra_top_level_keys:
                if key in raw:
                    merged[key] = raw[key]
        merged.update(_mapping_dict(raw.get(section)))
        return normalize_stage_payload_config(
            merged,
            stage_type=section,
        )

    normalized["txt2img"] = _merge_stage("txt2img")
    normalized["img2img"] = _merge_stage("img2img")
    normalized["adetailer"] = _merge_stage("adetailer")
    normalized["upscale"] = _merge_stage("upscale", _UPSCALE_TOP_LEVEL_KEYS)
    normalized["animatediff"] = _mapping_dict(raw.get("animatediff"))
    normalized["video_workflow"] = _mapping_dict(raw.get("video_workflow"))

    pipeline = _mapping_dict(raw.get("pipeline"))
    pipeline["txt2img_enabled"] = bool(
        pipeline.get("txt2img_enabled", normalized["txt2img"].get("enabled", True))
    )
    pipeline["img2img_enabled"] = bool(
        pipeline.get("img2img_enabled", normalized["img2img"].get("enabled", False))
    )
    pipeline["adetailer_enabled"] = bool(
        pipeline.get("adetailer_enabled", normalized["adetailer"].get("enabled", False))
    )
    pipeline["upscale_enabled"] = bool(
        pipeline.get("upscale_enabled", normalized["upscale"].get("enabled", False))
    )
    pipeline["animatediff_enabled"] = bool(
        pipeline.get("animatediff_enabled", normalized["animatediff"].get("enabled", False))
    )
    pipeline["video_workflow_enabled"] = bool(
        pipeline.get("video_workflow_enabled", normalized["video_workflow"].get("enabled", False))
    )
    normalized["pipeline"] = pipeline

    hires_fix = _mapping_dict(raw.get("hires_fix"))
    raw_txt2img = _mapping_dict(raw.get("txt2img"))
    txt2img_hires_present = bool(
        _TXT2IMG_HIRES_KEYS.intersection(raw.keys())
        or _TXT2IMG_HIRES_KEYS.intersection(raw_txt2img.keys())
    )
    if normalized["txt2img"].get("hires_enabled") or hires_fix or txt2img_hires_present:
        hires_fix["enabled"] = bool(
            hires_fix.get("enabled", normalized["txt2img"].get("hires_enabled", False))
        )
        scale = _first_value(hires_fix, "upscale_factor", "scale")
        if not _has_value(scale):
            scale = _first_value(
                raw_txt2img,
                "hires_scale_factor",
                "hr_scale",
            )
        if not _has_value(scale):
            scale = _first_value(raw, "hires_scale_factor", "hr_scale")
        if _has_value(scale):
            hires_fix["upscale_factor"] = float(scale)
        upscaler = _first_value(hires_fix, "upscaler_name", "hr_upscaler")
        if not _has_value(upscaler):
            upscaler = _first_value(
                raw_txt2img,
                "hires_upscaler_name",
                "hr_upscaler",
            )
        if not _has_value(upscaler):
            upscaler = _first_value(raw, "hires_upscaler_name", "hr_upscaler")
        if _has_value(upscaler):
            hires_fix["upscaler_name"] = upscaler
        denoise = _first_value(hires_fix, "denoise", "denoise_strength")
        if not _has_value(denoise):
            denoise = _first_value(
                raw_txt2img,
                "hires_denoise",
                "hires_denoise_strength",
                "denoising_strength",
            )
        if not _has_value(denoise):
            denoise = _first_value(
                raw,
                "hires_denoise",
                "hires_denoise_strength",
                "denoising_strength",
            )
        if _has_value(denoise):
            hires_fix["denoise"] = float(denoise)
        steps = _first_value(hires_fix, "steps")
        if not _has_value(steps):
            steps = _first_value(raw_txt2img, "hires_steps", "hr_second_pass_steps")
        if not _has_value(steps):
            steps = _first_value(raw, "hires_steps", "hr_second_pass_steps")
        if _has_value(steps):
            hires_fix["steps"] = int(steps)
    normalized["hires_fix"] = hires_fix

    metadata = _mapping_dict(raw.get("metadata"))
    if "run_id" in raw and "run_id" not in metadata:
        metadata["run_id"] = raw.get("run_id")
    normalized["metadata"] = metadata

    prompt_optimizer = _mapping_dict(raw.get("prompt_optimizer"))
    if prompt_optimizer:
        normalized["prompt_optimizer"] = prompt_optimizer

    return normalized


__all__ = ["normalize_pipeline_config", "normalize_stage_payload_config"]
