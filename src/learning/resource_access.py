"""Canonical projected WebUI resource access for Learning surfaces."""

from __future__ import annotations

from typing import Any

from src.learning.variable_selection_contract import normalize_resource_entries


def resolve_app_state(learning_controller: Any | None) -> Any | None:
    """Return the canonical AppStateV2 projection exposed to Learning."""
    if learning_controller is None:
        return None
    direct = getattr(learning_controller, "app_state", None)
    if direct is not None and hasattr(direct, "resources"):
        return direct
    app_controller = getattr(learning_controller, "app_controller", None)
    projected = getattr(app_controller, "app_state", None)
    if projected is not None and hasattr(projected, "resources"):
        return projected
    return None


def get_projected_resources(learning_controller: Any | None) -> dict[str, list[Any]]:
    """Read the current resource projection without querying WebUI directly."""
    state = resolve_app_state(learning_controller)
    resources = getattr(state, "resources", None) if state is not None else None
    return dict(resources or {})


def get_resource_choices(
    learning_controller: Any | None,
    resource_key: str,
) -> tuple[list[str], dict[str, str]]:
    """Return display choices and display-to-runtime mapping from one source."""
    entries = get_projected_resources(learning_controller).get(resource_key, [])
    return normalize_resource_entries(list(entries or []))
