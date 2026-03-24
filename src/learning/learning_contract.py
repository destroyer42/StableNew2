# Subsystem: Learning
# Role: Defines core dataclasses and contracts shared across the learning subsystem.

# Phase 3+ Learning subsystem:
# Not required for Phase 1 stability; used by future learning workflows only.

"""Stable stub contract for future learning consumers."""

from __future__ import annotations

from copy import deepcopy
from typing import Any

from src.config.prompting_defaults import DEFAULT_PROMPT_OPTIMIZER_SETTINGS


PROMPT_OPTIMIZER_PRESET_BASELINE_ID = "baseline_safe_v1"
PROMPT_OPTIMIZER_PRESET_SCORE_ID = "score_classifier_v1"
PROMPT_OPTIMIZER_PRESET_ANCHOR_ID = "subject_anchor_v1"

_PROMPT_OPTIMIZER_LEARNING_PRESETS: dict[str, dict[str, Any]] = {
    PROMPT_OPTIMIZER_PRESET_BASELINE_ID: {
        "label": "Baseline Safe",
        "description": "Current conservative optimizer defaults for replay-safe comparisons.",
        "settings": dict(DEFAULT_PROMPT_OPTIMIZER_SETTINGS),
    },
    PROMPT_OPTIMIZER_PRESET_SCORE_ID: {
        "label": "Score Classifier",
        "description": "Enable score-based classification while keeping the rest of the optimizer conservative.",
        "settings": {
            **dict(DEFAULT_PROMPT_OPTIMIZER_SETTINGS),
            "enable_score_based_classification": True,
        },
    },
    PROMPT_OPTIMIZER_PRESET_ANCHOR_ID: {
        "label": "Subject Anchor",
        "description": "Allow subject-anchor boosting for bounded portrait-oriented comparisons.",
        "settings": {
            **dict(DEFAULT_PROMPT_OPTIMIZER_SETTINGS),
            "allow_subject_anchor_boost": True,
        },
    },
}


def get_prompt_optimizer_learning_presets() -> dict[str, dict[str, Any]]:
    """Return deterministic named presets for bounded optimizer comparisons."""

    return deepcopy(_PROMPT_OPTIMIZER_LEARNING_PRESETS)


def get_available_modifiers() -> list[str]:
    """Return placeholder list of available modifiers."""

    return ["prompt_sr", "wildcards", "matrix", "prompt_optimizer_preset"]


def get_modifier_ranges() -> dict[str, Any]:
    """Return placeholder ranges for modifiers."""

    return {
        "steps": {"min": 1, "max": 50},
        "cfg_scale": {"min": 1.0, "max": 30.0},
        "prompt_optimizer_preset": {
            "values": list(get_prompt_optimizer_learning_presets().keys()),
        },
    }


def get_current_best_defaults() -> dict[str, Any]:
    """Return placeholder defaults for future tuning."""

    return {
        "txt2img": {"steps": 20, "cfg_scale": 7.0},
        "prompt_optimizer": {"preset_id": PROMPT_OPTIMIZER_PRESET_BASELINE_ID},
    }


def propose_new_defaults(dataset: Any) -> dict[str, Any]:
    """Return placeholder proposed defaults based on dataset."""

    runs = dataset.get("runs", []) if isinstance(dataset, dict) else []
    preset_counts: dict[str, int] = {}
    for row in runs:
        if not isinstance(row, dict):
            continue
        learning_meta = row.get("prompt_optimizer_learning")
        if not isinstance(learning_meta, dict):
            learning_meta = ((row.get("metadata") or {}).get("prompt_optimizer_learning"))
        if not isinstance(learning_meta, dict):
            continue
        preset_id = str(learning_meta.get("preset_id") or "").strip()
        if preset_id:
            preset_counts[preset_id] = preset_counts.get(preset_id, 0) + 1

    proposed_preset_id = PROMPT_OPTIMIZER_PRESET_BASELINE_ID
    if preset_counts:
        proposed_preset_id = sorted(
            preset_counts.items(),
            key=lambda item: (-item[1], item[0]),
        )[0][0]

    return {
        "proposed": True,
        "source_rows": len(runs),
        "prompt_optimizer": {
            "preset_id": proposed_preset_id,
            "available_presets": list(get_prompt_optimizer_learning_presets().keys()),
        },
    }
