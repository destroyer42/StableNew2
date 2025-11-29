"""Pure validator for txt2img pipeline config fields."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict

MIN_STEPS = 1
MAX_STEPS = 150
MIN_CFG_SCALE = 0.0
MAX_CFG_SCALE = 30.0
MIN_DIMENSION = 256
MAX_DIMENSION = 1536
DIMENSION_STEP = 8


@dataclass
class ValidationResult:
    is_valid: bool
    errors: Dict[str, str] = field(default_factory=dict)


def _coerce_int(value: Any) -> int | None:
    try:
        if value is None:
            return None
        if isinstance(value, str) and not value.strip():
            return None
        return int(float(value))
    except (ValueError, TypeError):
        return None


def _coerce_float(value: Any) -> float | None:
    try:
        if value is None:
            return None
        if isinstance(value, str) and not value.strip():
            return None
        return float(value)
    except (ValueError, TypeError):
        return None


def _coerce_str(value: Any) -> str:
    if value is None:
        return ""
    return str(value).strip()


def validate_txt2img(config: dict | None) -> ValidationResult:
    cfg = config or {}
    errors: Dict[str, str] = {}

    steps = _coerce_int(cfg.get("steps"))
    if steps is None or not (MIN_STEPS <= steps <= MAX_STEPS):
        errors["steps"] = f"Steps must be between {MIN_STEPS} and {MAX_STEPS}."

    cfg_scale = _coerce_float(cfg.get("cfg_scale"))
    if cfg_scale is None or not (MIN_CFG_SCALE <= cfg_scale <= MAX_CFG_SCALE):
        errors["cfg_scale"] = f"CFG scale must be between {MIN_CFG_SCALE:g} and {MAX_CFG_SCALE:g}."

    for field in ("width", "height"):
        value = _coerce_int(cfg.get(field))
        if value is None:
            errors[field] = f"{field.title()} is required."
            continue
        if not (MIN_DIMENSION <= value <= MAX_DIMENSION):
            errors[field] = f"{field.title()} must be between {MIN_DIMENSION} and {MAX_DIMENSION}."
            continue
        if value % DIMENSION_STEP != 0:
            errors[field] = f"{field.title()} must be a multiple of {DIMENSION_STEP}."

    def _require(field: str, allow_none_literal: bool = False) -> None:
        value = _coerce_str(cfg.get(field))
        if not value:
            errors[field] = f"{field.replace('_', ' ').title()} is required."
            return
        if allow_none_literal and value.lower() == "none":
            return
        if not value:
            errors[field] = f"{field.replace('_', ' ').title()} is required."

    _require("model")
    _require("sampler_name")
    _require("scheduler")
    _require("vae", allow_none_literal=True)

    return ValidationResult(is_valid=not errors, errors=errors)
