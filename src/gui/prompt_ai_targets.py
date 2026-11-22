"""Closed target advice options from the existing model picker and its canonical policy projection."""

from __future__ import annotations

import re
from typing import Any

from src.controller.content_visibility_resolver import ContentVisibilityResolver
from src.gui_v2.model_policy_projection import ModelControlProjection

_MAX_TARGETS = 256


def prompt_ai_target_projections(
    base_panel: Any, visibility_mode: str
) -> dict[str, tuple[str, ModelControlProjection]]:
    """Capture visible eligible checkpoint ids, labels and their policy projections in picker order."""
    combo = getattr(base_panel, "_model_combo", None)
    normalize = getattr(base_panel, "_normalize_model_name", None)
    project = getattr(base_panel, "project_checkpoint_candidates", None)
    if combo is None or not callable(normalize) or not callable(project):
        return {}
    resolver = ContentVisibilityResolver(visibility_mode)
    model_names = tuple(dict.fromkeys(normalize(name) for name in combo["values"]))
    choices: dict[str, tuple[str, ModelControlProjection]] = {}
    for projection in project(name for name in model_names if name and len(name) <= 200):
        policy = projection.policy
        if not policy.explicit_capabilities or projection.blocking or not policy.stages:
            continue
        name = projection.model_name
        label = f"{name} ({policy.display_name})"
        # Checkpoint names can concatenate the NSFW marker with the model name or version.
        visibility_label = re.sub(r"nsfw", " nsfw ", label, flags=re.IGNORECASE)
        if not resolver.is_visible({"name": visibility_label}):
            continue
        choices[name] = (label, projection)
        if len(choices) == _MAX_TARGETS:
            break
    return choices


def prompt_ai_targets(base_panel: Any, visibility_mode: str) -> tuple[tuple[str, str], ...]:
    return tuple(
        (name, label)
        for name, (label, _projection) in prompt_ai_target_projections(
            base_panel, visibility_mode
        ).items()
    )
