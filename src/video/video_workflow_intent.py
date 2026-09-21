"""Producer-side, capability-driven video workflow intent (PR-VID-130).

Pure functions that turn a selected ``WorkflowSpec`` plus operator form data into (a) the
admission errors an operator can read *before* queueing and (b) the neutral ``video_execution``
block stored in the immutable stage config.  Everything is derived from the spec's declared input
bindings, governance state and accepted controls; nothing here branches on a workflow or model
name.  No backend is invoked and nothing is executed.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any

from src.video.video_backend_types import (
    CONTROL_CAMERA_INTENT,
    CONTROL_END_ANCHOR,
    CONTROL_MID_ANCHORS,
    CONTROL_NEGATIVE_PROMPT,
    CONTROL_PROMPT_TEXT,
    CONTROL_SOURCE_IMAGE,
    VIDEO_TASK_IMAGE_TO_VIDEO,
)
from src.video.video_execution_resolver import VIDEO_EXECUTION_KEY

EXPERIMENTAL_OPT_IN_FIELD = "experimental_opt_in"


def _text(value: Any) -> str:
    return str(value or "").strip()


def mid_anchor_list(raw: Any) -> list[str]:
    if isinstance(raw, str):
        raw = [item.strip() for item in raw.split(";") if item.strip()]
    return [str(Path(str(item)).expanduser()) for item in raw or [] if _text(item)]


def default_negative_prompt(spec: Any) -> str:
    return _text((getattr(spec, "backend_defaults", None) or {}).get("default_negative_prompt"))


def experimental_opt_in_granted(spec: Any, form_data: Mapping[str, Any]) -> bool:
    """True only for an experimental spec whose job form explicitly ticked the opt-in."""

    return bool(getattr(spec, "is_experimental", False)) and (
        form_data.get(EXPERIMENTAL_OPT_IN_FIELD) is True
    )


def requested_controls(spec: Any, form_data: Mapping[str, Any]) -> tuple[str, ...]:
    """Controls this job actually requests: only what the form supplied for the workflow."""

    controls = {CONTROL_SOURCE_IMAGE}
    if _text(form_data.get("prompt")):
        controls.add(CONTROL_PROMPT_TEXT)
    if _text(form_data.get("negative_prompt")) or default_negative_prompt(spec):
        if "negative_prompt" in spec.declared_input_names:
            controls.add(CONTROL_NEGATIVE_PROMPT)
    if _text(form_data.get("end_anchor_path")):
        controls.add(CONTROL_END_ANCHOR)
    if mid_anchor_list(form_data.get("mid_anchor_paths")):
        controls.add(CONTROL_MID_ANCHORS)
    camera = form_data.get("camera_intent")
    if isinstance(camera, Mapping) and _text(camera.get("preset")).lower() not in {"", "none"}:
        controls.add(CONTROL_CAMERA_INTENT)
    return tuple(sorted(controls))


def capability_errors(spec: Any, form_data: Mapping[str, Any]) -> list[str]:
    """Operator-readable admission problems derived from the spec (empty when admissible)."""

    errors: list[str] = []
    name = spec.display_name
    if spec.is_experimental and not experimental_opt_in_granted(spec, form_data):
        errors.append(
            f"'{name}' is an experimental workflow. Tick 'Enable experimental workflow for this "
            "job' to run it; the choice is recorded per job."
        )
    required = set(spec.required_input_names)
    if "end_anchor" in required and not _text(form_data.get("end_anchor_path")):
        errors.append("Please choose an end anchor image for the video workflow.")
    if "prompt" in required and not _text(form_data.get("prompt")):
        errors.append(f"'{name}' needs a prompt describing the motion.")
    accepted = set(spec.accepted_controls)
    for control in requested_controls(spec, form_data):
        if control not in accepted:
            errors.append(
                f"'{name}' does not accept the requested {control.replace('_', ' ')} input."
            )
    return errors


def build_video_execution_block(spec: Any, form_data: Mapping[str, Any]) -> dict[str, Any]:
    """The neutral intent stored in the immutable stage config for this job."""

    return {
        "backend_id": spec.backend_id,
        "task": VIDEO_TASK_IMAGE_TO_VIDEO,
        "controls": list(requested_controls(spec, form_data)),
        "workflow_id": spec.workflow_id,
        "workflow_version": spec.workflow_version,
        EXPERIMENTAL_OPT_IN_FIELD: experimental_opt_in_granted(spec, form_data),
    }


def form_visibility(spec: Any) -> dict[str, bool]:
    """Which optional form sections are meaningful for ``spec`` (used by the UI to show or
    disable fields so nothing implies it will be honoured when it will not)."""

    accepted = set(getattr(spec, "accepted_controls", ()))
    declared: Sequence[str] = getattr(spec, "declared_input_names", ())
    return {
        "end_anchor": CONTROL_END_ANCHOR in accepted and "end_anchor" in declared,
        "mid_anchors": CONTROL_MID_ANCHORS in accepted and "mid_anchors" in declared,
        "camera_intent": CONTROL_CAMERA_INTENT in accepted and "camera_preset" in declared,
        "depth_conditioning": "depth_map" in declared,
        "motion_profile": "motion_profile" in declared,
        "negative_prompt": CONTROL_NEGATIVE_PROMPT in accepted and "negative_prompt" in declared,
        "experimental": bool(getattr(spec, "is_experimental", False)),
    }


__all__ = [
    "EXPERIMENTAL_OPT_IN_FIELD",
    "VIDEO_EXECUTION_KEY",
    "build_video_execution_block",
    "capability_errors",
    "default_negative_prompt",
    "experimental_opt_in_granted",
    "form_visibility",
    "mid_anchor_list",
    "requested_controls",
]
