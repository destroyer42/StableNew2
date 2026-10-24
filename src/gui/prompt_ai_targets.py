"""Closed target advice options from the existing model picker and its canonical policy projection."""

from __future__ import annotations

from typing import Any

from src.controller.content_visibility_resolver import ContentVisibilityResolver
from src.gui_v2.model_policy_projection import project_model_selection
from src.image_backends.image_backend_types import configured_image_backend_id


def prompt_ai_targets(base_panel: Any, visibility_mode: str) -> tuple[tuple[str, str], ...]:
    combo = getattr(base_panel, "_model_combo", None)
    normalize = getattr(base_panel, "_normalize_model_name", None)
    if combo is None or not callable(normalize):
        return ()
    resolver = ContentVisibilityResolver(visibility_mode)
    choices = []
    for name in combo["values"]:
        model_name = normalize(name)
        projection = project_model_selection(model_name, configured_image_backend_id())
        if not projection.policy.explicit_capabilities or projection.blocking:
            continue
        label = f"{model_name} ({projection.policy.display_name})"
        if resolver.is_visible({"name": label}) and model_name and len(model_name) <= 200:
            choices.append((model_name, label))
    return tuple(dict(choices).items())[:256]
