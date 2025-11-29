# Subsystem: Learning
# Role: Defines core dataclasses and contracts shared across the learning subsystem.

# Phase 3+ Learning subsystem:
# Not required for Phase 1 stability; used by future learning workflows only.

"""Stable stub contract for future learning consumers."""

from __future__ import annotations

from typing import Any


def get_available_modifiers() -> list[str]:
    """Return placeholder list of available modifiers."""

    return ["prompt_sr", "wildcards", "matrix"]


def get_modifier_ranges() -> dict[str, Any]:
    """Return placeholder ranges for modifiers."""

    return {
        "steps": {"min": 1, "max": 50},
        "cfg_scale": {"min": 1.0, "max": 30.0},
    }


def get_current_best_defaults() -> dict[str, Any]:
    """Return placeholder defaults for future tuning."""

    return {"txt2img": {"steps": 20, "cfg_scale": 7.0}}


def propose_new_defaults(dataset: Any) -> dict[str, Any]:
    """Return placeholder proposed defaults based on dataset."""

    return {"proposed": True, "source_rows": len(dataset.get("runs", [])) if isinstance(dataset, dict) else 0}
