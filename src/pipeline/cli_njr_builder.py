from __future__ import annotations

from copy import deepcopy
from time import time
from uuid import uuid4

from src.pipeline.config_contract_v26 import (
    canonicalize_intent_config,
    extract_adaptive_refinement_intent,
)
from src.pipeline.job_models_v2 import NormalizedJobRecord, StageConfig

_TXT2IMG_INACTIVE_HIRES_KEYS = (
    "hr_scale",
    "hr_upscaler",
    "denoising_strength",
    "hr_second_pass_steps",
    "hr_resize_x",
    "hr_resize_y",
)


def _txt2img_hires_enabled(data: dict[str, object]) -> bool:
    return bool(data.get("enable_hr") or data.get("hires_enabled"))


def _stage_config_from_section(stage_type: str, section: dict[str, object] | None) -> StageConfig:
    data = dict(section or {})
    denoising_strength = (
        float(data.get("denoising_strength", 0.0) or 0.0) or None
        if "denoising_strength" in data
        else None
    )
    if stage_type == "txt2img" and not _txt2img_hires_enabled(data):
        denoising_strength = None
    return StageConfig(
        stage_type=stage_type,
        enabled=True,
        steps=int(data.get("steps", 0) or 0) or None,
        cfg_scale=float(data.get("cfg_scale", 0.0) or 0.0) or None,
        denoising_strength=denoising_strength,
        sampler_name=str(data.get("sampler_name", "") or "") or None,
        scheduler=str(data.get("scheduler", "") or "") or None,
        model=str(data.get("model", "") or data.get("sd_model_checkpoint", "") or "") or None,
        vae=str(data.get("vae", "") or "") or None,
        extra=data,
    )


def _flatten_txt2img_config(config: dict[str, object]) -> dict[str, object]:
    txt2img = dict(config.get("txt2img", {}) or {})
    flattened = dict(txt2img)
    if not _txt2img_hires_enabled(txt2img):
        for key in _TXT2IMG_INACTIVE_HIRES_KEYS:
            flattened.pop(key, None)
    for key in ("pipeline", "aesthetic"):
        value = config.get(key)
        if isinstance(value, dict):
            flattened[key] = deepcopy(value)
    hires_fix = config.get("hires_fix")
    if isinstance(hires_fix, dict):
        flattened["hires_fix"] = deepcopy(hires_fix)
    return flattened


def build_cli_njr(
    *,
    prompt: str,
    config: dict[str, object],
    batch_size: int,
    run_name: str | None = None,
) -> NormalizedJobRecord:
    full_config = deepcopy(config)
    txt2img = dict(full_config.get("txt2img", {}) or {})
    pipeline = dict(full_config.get("pipeline", {}) or {})

    job_id = str(run_name or f"cli-{uuid4().hex[:12]}")
    stage_chain = [_stage_config_from_section("txt2img", txt2img)]

    if pipeline.get("img2img_enabled"):
        stage_chain.append(
            _stage_config_from_section("img2img", dict(full_config.get("img2img", {}) or {}))
        )
    if pipeline.get("adetailer_enabled"):
        stage_chain.append(
            _stage_config_from_section("adetailer", dict(full_config.get("adetailer", {}) or {}))
        )
    if pipeline.get("upscale_enabled"):
        stage_chain.append(
            _stage_config_from_section("upscale", dict(full_config.get("upscale", {}) or {}))
        )

    return NormalizedJobRecord(
        job_id=job_id,
        config=_flatten_txt2img_config(full_config),
        path_output_dir="output",
        filename_template="{seed}",
        seed=int(txt2img.get("seed", -1) or -1),
        variant_index=0,
        variant_total=1,
        batch_index=0,
        batch_total=1,
        created_ts=time(),
        positive_prompt=prompt,
        negative_prompt=str(txt2img.get("negative_prompt", "") or ""),
        steps=int(txt2img.get("steps", 20) or 20),
        cfg_scale=float(txt2img.get("cfg_scale", 7.0) or 7.0),
        width=int(txt2img.get("width", 512) or 512),
        height=int(txt2img.get("height", 512) or 512),
        sampler_name=str(txt2img.get("sampler_name", "Euler a") or "Euler a"),
        scheduler=str(txt2img.get("scheduler", "") or ""),
        clip_skip=int(txt2img.get("clip_skip", 0) or 0),
        base_model=str(
            txt2img.get("model", "") or txt2img.get("sd_model_checkpoint", "") or "unknown"
        ),
        vae=str(txt2img.get("vae", "") or "") or None,
        stage_chain=stage_chain,
        images_per_prompt=max(1, int(batch_size or 1)),
        run_mode="QUEUE",
        queue_source="RUN_NOW",
        intent_config=canonicalize_intent_config(
            {
                "run_mode": "queue",
                "source": "cli",
                "prompt_source": "cli",
                "requested_job_label": run_name,
                "adaptive_refinement": extract_adaptive_refinement_intent(full_config),
            }
        ),
        extra_metadata={
            "execution_source": "cli",
            **({"run_name": run_name} if run_name else {}),
        },
    )
