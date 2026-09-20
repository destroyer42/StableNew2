"""Controller-side projection of current global prompt intent.

Reads editable intent at compilation time only; execution consumes the frozen
values written into the job configuration.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import replace
from typing import Any

from src.pipeline.global_prompt_policy import apply_global_prompt_policy

FROZEN_KEYS = ("global_positive_prompt", "global_negative_prompt", "global_prompt_policy_source")


def read_current_policy(
    sidebar: Any, config_manager: Any, log: Callable[[str], None]
) -> dict[str, Any]:
    """Project sidebar (or saved-default) policy into apply_global_prompt_policy kwargs."""

    try:
        positive = sidebar.get_global_positive_config() if sidebar else {}
        negative = sidebar.get_global_negative_config() if sidebar else {}
    except Exception as exc:
        log(f"[controller] Failed to read global prompt policy: {exc}")
        positive, negative = {}, {}
    if not positive and config_manager is not None:
        positive = {
            "enabled": bool(config_manager.get_global_positive_enabled()),
            "text": config_manager.get_global_positive_prompt(),
        }
    if not negative and config_manager is not None:
        negative = {
            "enabled": bool(config_manager.get_global_negative_enabled()),
            "text": config_manager.get_global_negative_prompt(),
        }
    return {
        "positive_enabled": bool(positive.get("enabled", False)),
        "positive_text": str(positive.get("text") or ""),
        "negative_enabled": bool(negative.get("enabled", True)),
        "negative_text": str(negative.get("text") or ""),
    }


def policy_from_overrides(overrides: Mapping[str, Any] | None) -> dict[str, Any]:
    """Recover policy kwargs from a GUI overrides mapping."""

    data = overrides if isinstance(overrides, Mapping) else {}
    pipeline = data.get("pipeline")
    pipeline = pipeline if isinstance(pipeline, Mapping) else {}
    return {
        "positive_enabled": bool(pipeline.get("apply_global_positive_txt2img", False)),
        "positive_text": str(data.get("global_positive_prompt") or ""),
        "negative_enabled": bool(pipeline.get("apply_global_negative_txt2img", True)),
        "negative_text": str(data.get("global_negative_prompt") or ""),
    }


def overlay_pack_entries(entries: list[Any], policy: Mapping[str, Any]) -> list[Any]:
    """Return pack entries whose snapshots carry the current run-level policy."""

    return [
        replace(e, config_snapshot=apply_global_prompt_policy(e.config_snapshot, **policy))
        for e in entries
    ]


def overlay_config_in_place(config: dict[str, Any], policy: Mapping[str, Any]) -> None:
    config.update(apply_global_prompt_policy(config, **policy))


def copy_frozen_keys(source: Mapping[str, Any], target: dict[str, Any]) -> None:
    for key in FROZEN_KEYS:
        if key in source:
            target[key] = source[key]


def overlay_current_policy(controller: Any, entries: list[Any]) -> list[Any]:
    """Overlay the controller's current GUI policy onto pack entries."""

    getter = getattr(controller, "gui_get_pipeline_overrides", None) or getattr(
        controller, "get_gui_overrides", None
    )
    try:
        policy = policy_from_overrides(getter() if callable(getter) else None)
    except Exception:
        policy = policy_from_overrides(None)
    return overlay_pack_entries(entries, policy)
