"""Typed txt2img overrides and safe catalog projection for Site-created drafts."""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from typing import Any

from src.generation_profiles.startup import available_model_names
from src.pipeline.config_merger_v2 import (
    ConfigMergerV2,
    StageOverrideFlags,
    StageOverridesBundle,
    Txt2ImgOverrides,
)

Choice = str | int | float
CATALOGS = {"model": "models", "vae": "vaes", "sampler": "samplers", "scheduler": "schedulers"}
NUMBERS: dict[str, tuple[float, float, float]] = {
    "steps": (1, 200, 1),
    "cfg_scale": (0, 30, 0.1),
    "width": (256, 2048, 8),
    "height": (256, 2048, 8),
    "seed": (-1, 4294967295, 1),
    "subseed": (-1, 4294967295, 1),
    "subseed_strength": (0, 1, 0.01),
    "loop_count": (1, 16, 1),
}


def option_names(resources: Mapping[str, Any], key: str) -> list[str]:
    names: Iterable[str]
    if key == "model":
        names = available_model_names(resources) or ()
    else:
        entries = resources.get(CATALOGS[key], ())
        names = (
            (str(getattr(item, "name", item)) for item in entries)
            if isinstance(entries, (list, tuple))
            else ()
        )
    return sorted({name for name in names if name and len(name) <= 256}, key=str.casefold)[:500]


def validate_settings(raw: object, resources: Mapping[str, Any]) -> dict[str, Choice]:
    if not isinstance(raw, dict) or raw.keys() - (CATALOGS.keys() | NUMBERS.keys()):
        raise ValueError("invalid_txt2img_settings")
    validated: dict[str, Choice] = {}
    for key, value in raw.items():
        if key in CATALOGS:
            if not isinstance(value, str) or value not in option_names(resources, key):
                raise ValueError("invalid_txt2img_settings")
        else:
            minimum, maximum, step = NUMBERS[key]
            if type(value) not in {int, float} or not minimum <= value <= maximum:
                raise ValueError("invalid_txt2img_settings")
            if step >= 1 and (type(value) is not int or (value - minimum) % step):
                raise ValueError("invalid_txt2img_settings")
        validated[key] = value
    return validated


def describe_settings(
    config: Mapping[str, Any], resources: Mapping[str, Any]
) -> dict[str, dict[str, object]]:
    section = config.get("txt2img") or {}
    pipeline = config.get("pipeline") or {}
    result: dict[str, dict[str, object]] = {}
    if not isinstance(section, dict) or not isinstance(pipeline, dict):
        return result
    for key in (*CATALOGS, *NUMBERS):
        setting = "sampler_name" if key == "sampler" else key
        value = pipeline.get(key) if key == "loop_count" else section.get(setting, config.get(key))
        default = value if type(value) in {str, int, float} else None
        if key in CATALOGS:
            result[key] = {"default": default, "choices": option_names(resources, key)}
        else:
            minimum, maximum, step = NUMBERS[key]
            result[key] = {"default": default, "min": minimum, "max": maximum, "step": step}
    return result


def apply_site_settings(config: dict[str, Any], overrides: Mapping[str, Choice]) -> dict[str, Any]:
    values: dict[str, Any] = dict(overrides)
    repeats = values.pop("loop_count", None)
    updated = ConfigMergerV2.merge_pipeline(
        config,
        StageOverridesBundle(txt2img=Txt2ImgOverrides(**values)),
        StageOverrideFlags(txt2img_override_enabled=True),
    )
    if repeats is not None:
        updated.setdefault("pipeline", {})["loop_count"] = repeats
    return updated
