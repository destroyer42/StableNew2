"""Advisory timing preview of a harvested window against the *currently selected* workflow (PR-VID-MOTION-400).

A harvested asset is workflow-independent.  This shows, without touching any file, what the existing
PR-VID-MOTION-210 *Prepare Motion Source* would do with the selected window for the selected workflow and length:
which frames are consumed, what is omitted, repeated or held.  It is display-only and changes no asset; the real
preparation re-verifies everything at admission, and a workflow that cannot honestly offer preparation says so.
"""

from __future__ import annotations

from fractions import Fraction
from typing import Any

from src.video.motion_source_plan import (
    FPS_CONVERSION_NONE,
    FPS_CONVERSION_WORKFLOW_RATE,
    MotionSourceSettings,
    build_frame_plan,
    explain_plan,
    motion_source_contract,
)


def workflow_timing_lines(
    spec: Any,
    frame_count_value: Any,
    *,
    window_frames: int,
    rate: Fraction | None,
    convert_to_workflow_rate: bool,
) -> tuple[str, ...]:
    """Operator-facing lines, or one line saying why no preview is offered.  Never raises."""

    if spec is None:
        return (
            "No workflow that takes a driving video is selected, so no workflow timing is shown.",
        )
    try:
        contract = motion_source_contract(spec, frame_count_value)
        settings = MotionSourceSettings(
            start_frame=0,
            end_frame=None,
            fps_conversion=FPS_CONVERSION_WORKFLOW_RATE
            if convert_to_workflow_rate
            else FPS_CONVERSION_NONE,
        )
        plan = build_frame_plan(settings, contract, rate=rate, available_frames=window_frames)
    except ValueError as exc:
        return (f"Workflow timing is not available: {exc}",)
    lines = list(explain_plan(plan, contract))
    lines.append(
        "This is a preview of Prepare Motion Source for the selected workflow and length. The harvested clip "
        "itself is not changed."
    )
    return tuple(lines)


__all__ = ["workflow_timing_lines"]
