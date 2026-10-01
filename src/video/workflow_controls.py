"""Neutral, spec-declared operator controls for workflow-owned generation inputs (PR-VID-192).

A workflow opts into an operator-visible control by declaring BOTH an input binding whose
``source_field`` reads ``stage_config.operator_controls.<name>`` AND an entry in
``backend_defaults["operator_controls"]``::

    {"name": "pose_strength", "kind": "number", "label": "Pose Strength",
     "default": 1.0, "minimum": 0.0, "maximum": 10.0, "step": 0.01, "help": "..."}
    {"name": "pose_prompt", "kind": "text", "label": "Motion Prompt",
     "fallback_field": "prompt", "help": "..."}

The values are validated and frozen at admission into ``stage_config["operator_controls"]`` (the
immutable NJR), so the compiler binds them to the exact graph inputs and replay reproduces them.
Nothing here branches on a workflow or model name, and a control the selected workflow does not
declare is refused rather than silently dropped.  Optional ``ordered_pairs`` constrain two number
controls (first <= second) for inputs the runtime itself rejects when reversed.
"""

from __future__ import annotations

import math
from collections.abc import Mapping
from typing import Any

OPERATOR_CONTROLS_KEY = "operator_controls"
ORDERED_PAIRS_KEY = "operator_control_ordered_pairs"
KIND_NUMBER = "number"
KIND_TEXT = "text"


def _spec_name(spec: Any) -> str:
    return str(getattr(spec, "display_name", None) or getattr(spec, "workflow_id", "workflow"))


def operator_controls(spec: Any) -> list[dict[str, Any]]:
    """Declared controls that are also declared input bindings, in declaration order."""

    raw = (getattr(spec, "backend_defaults", None) or {}).get(OPERATOR_CONTROLS_KEY)
    if not isinstance(raw, (list, tuple)):
        return []
    declared = set(getattr(spec, "declared_input_names", ()) or ())
    controls: list[dict[str, Any]] = []
    for entry in raw:
        if not isinstance(entry, Mapping):
            continue
        name = str(entry.get("name") or "").strip()
        kind = str(entry.get("kind") or "").strip()
        if not name or name not in declared or kind not in (KIND_NUMBER, KIND_TEXT):
            continue
        control: dict[str, Any] = {
            "name": name,
            "kind": kind,
            "label": str(entry.get("label") or name),
            "help": str(entry.get("help") or ""),
        }
        if kind == KIND_NUMBER:
            try:
                control.update(
                    default=float(entry["default"]),
                    minimum=float(entry["minimum"]),
                    maximum=float(entry["maximum"]),
                    step=float(entry.get("step") or 0.0),
                )
            except (KeyError, TypeError, ValueError):
                continue
            if control["minimum"] > control["maximum"] or not (
                control["minimum"] <= control["default"] <= control["maximum"]
            ):
                continue
        else:
            control["fallback_field"] = str(entry.get("fallback_field") or "")
            control["required"] = bool(entry.get("required", False))
        controls.append(control)
    return controls


def ordered_pairs(spec: Any) -> list[tuple[str, str]]:
    raw = (getattr(spec, "backend_defaults", None) or {}).get(ORDERED_PAIRS_KEY)
    pairs: list[tuple[str, str]] = []
    for item in raw if isinstance(raw, (list, tuple)) else ():
        if isinstance(item, (list, tuple)) and len(item) == 2:
            pairs.append((str(item[0]), str(item[1])))
    return pairs


def operator_controls_projection(spec: Any) -> list[dict[str, Any]] | None:
    """What an operator form needs to render the declared controls, or None when there are none."""

    controls = operator_controls(spec)
    return controls or None


def _format_number(value: float) -> str:
    return f"{value:g}"


def resolve_operator_controls(spec: Any, form_data: Mapping[str, Any]) -> dict[str, Any] | None:
    """Validate the operator's controls against the spec and return the frozen effective values.

    Empty numbers take the declared default; an empty text control takes its declared fallback
    field's text (recorded as an explicit value).  Returns None when the spec declares no
    controls.  Illegal values are rejected, never clamped or rounded.
    """

    controls = operator_controls(spec)
    submitted = form_data.get(OPERATOR_CONTROLS_KEY)
    if not controls:
        if isinstance(submitted, Mapping) and any(
            str(value if value is not None else "").strip() for value in submitted.values()
        ):
            raise ValueError(f"'{_spec_name(spec)}' does not accept workflow controls.")
        return None
    supplied = dict(submitted) if isinstance(submitted, Mapping) else {}
    known = {control["name"] for control in controls}
    unknown = sorted(name for name in supplied if name not in known)
    if unknown:
        raise ValueError(f"'{_spec_name(spec)}' does not accept the control(s): {', '.join(unknown)}.")

    resolved: dict[str, Any] = {}
    for control in controls:
        name, label = control["name"], control["label"]
        raw = supplied.get(name)
        text = str(raw if raw is not None else "").strip()
        if control["kind"] == KIND_TEXT:
            if not text and control["fallback_field"]:
                text = str(form_data.get(control["fallback_field"]) or "").strip()
            if not text and control["required"]:
                raise ValueError(f"'{_spec_name(spec)}' needs a {label}.")
            resolved[name] = text
            continue
        if not text:
            resolved[name] = control["default"]
            continue
        try:
            number = float(text)
        except (TypeError, ValueError) as exc:
            raise ValueError(f"{label} must be a number.") from exc
        if not math.isfinite(number) or not control["minimum"] <= number <= control["maximum"]:
            raise ValueError(
                f"{label} must be between {_format_number(control['minimum'])} and "
                f"{_format_number(control['maximum'])} (default {_format_number(control['default'])})."
            )
        resolved[name] = number
    for first, second in ordered_pairs(spec):
        if first in resolved and second in resolved and resolved[first] > resolved[second]:
            labels = {control["name"]: control["label"] for control in controls}
            raise ValueError(
                f"{labels.get(first, first)} ({_format_number(resolved[first])}) must not be greater "
                f"than {labels.get(second, second)} ({_format_number(resolved[second])})."
            )
    return resolved


def control_defaults(spec: Any) -> dict[str, Any]:
    """Declared numeric defaults (text controls have no fixed default)."""

    return {c["name"]: c["default"] for c in operator_controls(spec) if c["kind"] == KIND_NUMBER}


__all__ = [
    "KIND_NUMBER",
    "KIND_TEXT",
    "OPERATOR_CONTROLS_KEY",
    "ORDERED_PAIRS_KEY",
    "control_defaults",
    "operator_controls",
    "operator_controls_projection",
    "ordered_pairs",
    "resolve_operator_controls",
]
