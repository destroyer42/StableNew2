"""Authoring profiles and compile-time ADetailer settings."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from src.prompting.prompt_intent_analyzer import classify_subject_count

FACE_MASK_LIMITS = {"single": 1, "multiple": 0}
FACE_MODES = (*FACE_MASK_LIMITS, "auto")
PROFILES_KEY = "face_mode_profiles"

# The first name is the executor's key. Keep aliases synchronized when applying a profile.
PROFILE_FIELDS = (
    ("adetailer_prompt", "ad_prompt"),
    ("adetailer_negative_prompt", "ad_negative_prompt"),
    ("adetailer_confidence", "ad_confidence", "confidence"),
    ("adetailer_denoise", "ad_denoising_strength", "denoise_strength"),
    ("adetailer_padding", "ad_inpaint_only_masked_padding", "inpaint_padding"),
    ("ad_mask_blur", "mask_blur"),
    ("ad_mask_filter_method", "mask_filter_method"),
    ("ad_mask_min_ratio", "mask_min_ratio"),
    ("ad_mask_max_ratio", "mask_max_ratio"),
    ("ad_dilate_erode", "mask_dilate_erode"),
    ("adetailer_hands_prompt",),
    ("adetailer_hands_negative_prompt",),
    ("adetailer_hands_confidence",),
    ("adetailer_hands_denoise",),
    ("ad_hands_padding", "hands_padding"),
    ("ad_hands_mask_blur",),
    ("ad_hands_mask_filter_method",),
    ("ad_hands_mask_k",),
    ("ad_hands_mask_min_ratio",),
    ("ad_hands_mask_max_ratio",),
    ("ad_hands_dilate_erode",),
    ("ad_hands_mask_merge_invert",),
)
FACE_PROMPT_FIELDS = PROFILE_FIELDS[:2]


def profile_values(config: Mapping[str, Any]) -> dict[str, Any]:
    """Select only profile-owned values, preserving explicit empty prompts and zeroes."""
    values: dict[str, Any] = {}
    for names in PROFILE_FIELDS:
        present = next((name for name in names if name in config), None)
        if present is not None:
            values[names[0]] = config[present]
    return values


def suggested_profile(mode: str) -> dict[str, Any]:
    return {
        "adetailer_prompt": (
            "natural facial detail, preserve each person's distinct features"
            if mode == "multiple"
            else "natural facial detail, preserve facial features"
        ),
        "adetailer_negative_prompt": "distorted facial features, unnatural skin texture",
        "adetailer_confidence": 0.35,
        "adetailer_denoise": 0.30 if mode == "multiple" else 0.32,
        "adetailer_padding": 32,
        "ad_mask_blur": 6,
        "ad_mask_filter_method": "Area",
        "ad_mask_min_ratio": 0.01,
        "ad_mask_max_ratio": 1.0,
        "ad_dilate_erode": 4,
        "adetailer_hands_prompt": "natural hand anatomy, well-formed fingers, natural knuckles",
        "adetailer_hands_negative_prompt": "extra fingers, fused fingers, deformed hands",
        "adetailer_hands_confidence": 0.30,
        "adetailer_hands_denoise": 0.25,
        "ad_hands_padding": 16,
        "ad_hands_mask_blur": 4,
        "ad_hands_mask_filter_method": "Area",
        "ad_hands_mask_k": 0 if mode == "multiple" else 6,
        "ad_hands_mask_min_ratio": 0.003,
        "ad_hands_mask_max_ratio": 1.0,
        "ad_hands_dilate_erode": 6,
        "ad_hands_mask_merge_invert": "None",
    }


def apply_profile(
    config: Mapping[str, Any], mode: str, values: Mapping[str, Any]
) -> dict[str, Any]:
    result = dict(config)
    for names in PROFILE_FIELDS:
        if names[0] in values:
            result.update(dict.fromkeys(names, values[names[0]]))
    mask_limit = FACE_MASK_LIMITS[mode]
    result.update(
        ad_mask_k_largest=mask_limit,
        mask_k_largest=mask_limit,
        ad_mask_merge_invert="None",
        mask_merge_mode="None",
    )
    return result


def compile_adetailer(
    config: dict[str, Any], positive: str
) -> tuple[dict[str, Any], dict[str, Any]]:
    """Resolve an authored mode for one rendered prompt. Old sections are left intact."""
    section = config.get("adetailer")
    if not isinstance(section, Mapping) or section.get("face_mode") not in FACE_MODES:
        return config, {}
    requested = section["face_mode"]
    decision = classify_subject_count(positive) if requested == "auto" else None
    effective = (
        ("multiple" if decision.classification == "multiple" else "single")
        if decision is not None
        else requested
    )
    profiles = section.get(PROFILES_KEY)
    values = profiles.get(effective) if isinstance(profiles, Mapping) else None
    frozen = apply_profile(
        section, effective, profile_values(values) if isinstance(values, Mapping) else {}
    )
    # Executable config keeps only the selected values. Provenance records how they were chosen.
    frozen.pop(PROFILES_KEY, None)
    frozen["face_mode"] = effective
    evidence = {
        "requested_mode": requested,
        "effective_mode": effective,
        "inference_version": decision.version if decision else None,
        "classification": decision.classification if decision else "manual",
        "reason": decision.reason if decision else "operator selection",
        "uncertain": decision is not None and decision.classification == "unknown",
        "face_mask_limit": FACE_MASK_LIMITS[effective],
        "hand_mask_limit": frozen.get("ad_hands_mask_k", 6),
    }
    return {**config, "adetailer": frozen}, evidence
