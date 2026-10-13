"""Photo draft settings projection; NJRs are still compiled by ReprocessJobBuilder."""

from __future__ import annotations

import math
from copy import deepcopy
from functools import lru_cache
from pathlib import Path
from typing import Any

from PIL import Image

from .models import PhotoOptimizeBaseline
from .paths import io_path

STAGES = ("img2img", "adetailer", "upscale")

# Nested canonical value, nested legacy spellings, flat legacy spellings, fallback.
FIELDS = {
    "img2img": {
        "sampler_name": ((), ("img2img_sampler_name", "sampler_name"), "Euler a"),
        "scheduler": ((), ("img2img_scheduler", "scheduler"), "normal"),
        "steps": ((), ("img2img_steps", "steps"), 20),
        "cfg_scale": ((), ("img2img_cfg_scale", "cfg_scale"), 7.0),
        "denoising_strength": ((), ("img2img_denoising_strength",), 0.3),
        "width": ((), ("width",), 0),
        "height": ((), ("height",), 0),
    },
    "adetailer": {
        "adetailer_model": (("ad_model",), ("adetailer_model",), ""),
        "adetailer_confidence": (("ad_confidence",), ("adetailer_confidence",), 0.35),
        "adetailer_steps": (("ad_steps", "steps"), ("adetailer_steps",), 28),
        "adetailer_cfg": (("ad_cfg_scale", "cfg_scale"), ("adetailer_cfg_scale",), 7.0),
        "adetailer_denoise": (
            ("ad_denoising_strength", "denoising_strength"),
            ("adetailer_denoising_strength",),
            0.4,
        ),
        "adetailer_sampler": (("ad_sampler", "sampler_name"), ("adetailer_sampler_name",), ""),
        "scheduler": (("ad_scheduler",), ("adetailer_scheduler",), "Use sampler default"),
    },
    "upscale": {
        "upscaler": ((), ("upscaler",), ""),
        "upscaling_resize": (("upscale_factor", "upscale_by"), ("upscale_factor",), 2.0),
        "steps": ((), ("upscale_steps",), 20),
        "denoising_strength": ((), ("upscale_denoising_strength",), 0.35),
        "sampler_name": ((), ("upscale_sampler_name",), "Euler a"),
        "scheduler": ((), ("upscale_scheduler",), "normal"),
        "tile_size": ((), (), 0),
        "face_restore": ((), (), False),
        "face_restore_method": ((), (), "CodeFormer"),
    },
}


def normalize_settings(config: dict[str, Any], *, defaults: bool = True) -> dict[str, Any]:
    """Nested explicit values win, including zero, False and empty strings.

    Synchronize consumed aliases so the form, compiler and executor agree.
    Preserve every unrelated field, including stage-specific model overrides.
    """
    result = deepcopy(config)
    for stage, fields in FIELDS.items():
        nested = result.setdefault(stage, {})
        if not isinstance(nested, dict):
            raise ValueError(f"{stage} settings must be an object")
        for key, (aliases, flat_keys, fallback) in fields.items():
            candidates = [(nested, k) for k in (key, *aliases)] + [(result, k) for k in flat_keys]
            present = next(((d, k) for d, k in candidates if k in d and d[k] is not None), None)
            if present is None and not defaults:
                continue
            value = present[0][present[1]] if present else fallback
            nested[key] = value
            for alias in aliases:
                nested[alias] = value
            # Generic root globals are img2img projections only.
            for alias in flat_keys:
                result[alias] = value
    return result


@lru_cache(maxsize=256)
def _decode_geometry(path: str, signature: tuple[int, int]) -> tuple[int, int]:
    with Image.open(path) as picture:
        picture.load()
        return picture.size


def decoded_geometry(path: str | Path) -> tuple[int, int]:
    try:
        source = io_path(path).resolve()
        stat = source.stat()
        return _decode_geometry(str(source), (stat.st_size, stat.st_mtime_ns))
    except (OSError, ValueError) as exc:
        raise ValueError(f"Cannot decode working photo: {path}") from exc


def resolve_geometry(baseline: PhotoOptimizeBaseline, path: str | Path) -> dict[str, Any]:
    size = decoded_geometry(path)  # Validate even a custom-size input before any admission.
    config = normalize_settings(baseline.config)
    if baseline.geometry_policy == "auto":
        width, height = size
    elif baseline.geometry_policy == "custom":
        width, height = config["img2img"]["width"], config["img2img"]["height"]
        try:
            valid = all(not isinstance(v, bool) and math.isfinite(float(v))
                        and float(v).is_integer() and float(v) > 0 for v in (width, height))
        except (TypeError, ValueError):
            valid = False
        if not valid:
            raise ValueError("Custom width and height must be positive integers")
    else:
        raise ValueError("Geometry policy must be Auto or Custom")
    for section in (config, config.setdefault("txt2img", {}), config["img2img"]):
        section.update(width=int(float(width)), height=int(float(height)))
    return config


def validate_settings(config: dict[str, Any]) -> None:
    for stage, keys in FIELDS.items():
        for key, (_, _, fallback) in keys.items():
            value = config[stage][key]
            if isinstance(fallback, bool) or not isinstance(fallback, (int, float)):
                continue
            try:
                number = float(value)
            except (TypeError, ValueError) as exc:
                raise ValueError(f"{stage} {key} must be a number") from exc
            if not math.isfinite(number) or number < 0:
                raise ValueError(f"{stage} {key} must be finite and nonnegative")
            if isinstance(fallback, int) and number != int(number):
                raise ValueError(f"{stage} {key} must be an integer")
            if key in {"steps", "adetailer_steps", "upscaling_resize"} and number <= 0:
                raise ValueError(f"{stage} {key} must be positive")
            if (
                key in {"denoising_strength", "adetailer_denoise", "adetailer_confidence"}
                and number > 1
            ):
                raise ValueError(f"{stage} {key} must be between 0 and 1")


def copy_pipeline_settings(
    baseline: PhotoOptimizeBaseline, defaults: dict[str, Any]
) -> PhotoOptimizeBaseline:
    """Copy execution settings only; preserve per-photo prompts and geometry policy."""
    copied = PhotoOptimizeBaseline.from_dict(baseline.to_dict())
    config = defaults.get("config")
    if not isinstance(config, dict) or not config:
        raise ValueError("Live Pipeline settings are unavailable; open the Pipeline tab and retry")
    from src.pipeline.reprocess_builder import ReprocessJobBuilder

    copied.config = ReprocessJobBuilder._merge_nested_dicts(baseline.config, config)
    if copied.geometry_policy == "custom":
        old = normalize_settings(baseline.config)["img2img"]
        copied.config.setdefault("img2img", {}).update(width=old["width"], height=old["height"])
    copied.config = resolve_geometry(copied, copied.working_image_path)
    copied.model = str(defaults.get("model", ""))
    copied.vae = str(defaults.get("vae", ""))
    copied.stage_defaults = dict(defaults.get("stage_defaults", copied.stage_defaults))
    validate_settings(copied.config)
    return copied
