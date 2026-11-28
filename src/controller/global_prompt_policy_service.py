"""Controller-side projection of current global prompt intent.

Reads editable intent at compilation time only; execution consumes the frozen
values written into the job configuration.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import replace
from typing import Any

from src.pipeline.global_prompt_policy import apply_global_prompt_policy


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
    if not positive:
        positive = _saved_policy(config_manager, "positive")
    if not negative:
        negative = _saved_policy(config_manager, "negative")
    return {
        "positive_enabled": bool(positive.get("enabled", False)),
        "positive_text": str(positive.get("text") or ""),
        "negative_enabled": bool(negative.get("enabled", True)),
        "negative_text": str(negative.get("text") or ""),
    }


def _saved_policy(config_manager: Any, kind: str) -> dict[str, Any]:
    """The saved-settings policy for ``kind``; empty when the manager keeps none (a partial settings stand-in)."""

    enabled = getattr(config_manager, f"get_global_{kind}_enabled", None)
    text = getattr(config_manager, f"get_global_{kind}_prompt", None)
    if not callable(enabled) or not callable(text):
        return {}
    return {"enabled": bool(enabled()), "text": text()}


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


def current_policy(controller: Any) -> dict[str, Any]:
    """Current editable policy, provided by AppController wiring at compile time."""

    getter = getattr(controller, "get_current_global_prompt_policy", None)
    policy = getter() if callable(getter) else None
    return dict(policy) if isinstance(policy, Mapping) else policy_from_overrides(None)


def overlay_config_in_place(config: dict[str, Any], policy: Mapping[str, Any]) -> None:
    config.update(apply_global_prompt_policy(config, **policy))


def overlay_current_policy(controller: Any, entries: list[Any]) -> list[Any]:
    """Return pack entries whose snapshots carry the current run-level policy."""

    policy = current_policy(controller)
    return [
        replace(e, config_snapshot=apply_global_prompt_policy(e.config_snapshot, **policy))
        for e in entries
    ]


def copy_frozen_keys(controller: Any, target: dict[str, Any]) -> None:
    """Freeze the current policy into generic/manual runtime overrides."""

    overlay_config_in_place(target, current_policy(controller))
