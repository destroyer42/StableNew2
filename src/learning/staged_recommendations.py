"""Non-mutating recommendation patches for staged-curation derived jobs."""

from __future__ import annotations

from copy import deepcopy
from typing import Any

_PARAMETER_KEYS = {
    "cfg": "cfg_scale",
    "cfg_scale": "cfg_scale",
    "steps": "steps",
    "sampler": "sampler_name",
    "sampler_name": "sampler_name",
    "scheduler": "scheduler",
    "model": "model",
    "vae": "vae",
    "denoising_strength": "denoising_strength",
    "upscale_factor": "upscaling_resize",
}
_ALLOWED_PATCH_KEYS = frozenset(_PARAMETER_KEYS.values())


def _config_stage(target_stage: str) -> str:
    return "img2img" if target_stage == "refine" else (
        "adetailer" if target_stage == "face_triage" else target_stage
    )


def build_derived_recommendation_patch(
    recommendations: Any, *, target_stage: str, current_config: dict[str, Any]
) -> dict[str, Any]:
    """Return a bounded stage-local patch and readable diff; mutate nothing."""
    stage = _config_stage(target_stage)
    current = dict(current_config.get(stage) or {})
    changes: list[dict[str, Any]] = []
    patch: dict[str, Any] = {}
    for rec in list(getattr(recommendations, "recommendations", []) or []):
        raw_name = str(getattr(rec, "parameter_name", "") or "").strip().lower()
        key = _PARAMETER_KEYS.get(raw_name)
        if not key:
            continue
        value = getattr(rec, "recommended_value", None)
        if value is None or current.get(key) == value:
            continue
        patch[key] = value
        changes.append(
            {
                "setting": key,
                "current": current.get(key),
                "suggested": value,
                "confidence": float(getattr(rec, "confidence_score", 0.0) or 0.0),
            }
        )
    return {"target_stage": stage, "stage_patch": patch, "changes": changes}


def apply_derived_recommendation_patch(
    config: dict[str, Any],
    recommendation_patch: dict[str, Any] | None,
    *,
    target_stage: str | None = None,
) -> dict[str, Any]:
    """Apply a confirmed patch to an isolated derived-job config copy."""
    result = deepcopy(config)
    payload = dict(recommendation_patch or {})
    stage = str(payload.get("target_stage") or "")
    expected_stage = _config_stage(target_stage) if target_stage else stage
    stage_patch = {
        str(key): value
        for key, value in dict(payload.get("stage_patch") or {}).items()
        if str(key) in _ALLOWED_PATCH_KEYS
    }
    if stage and stage == expected_stage and stage_patch:
        result.setdefault(stage, {}).update(stage_patch)
    return result
