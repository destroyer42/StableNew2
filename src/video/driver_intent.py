"""Follow a driving video (V1-3): what a driver clip and a requested duration resolve to.

Pure functions over the plain workflow record and :class:`~src.video.driving_video_inspection.DrivingVideoFacts`, shared
by the desktop panel and, later, the phone (RG-140):

* :func:`driver_seconds` is how much motion the clip holds;
* :func:`plan_driver_clip` turns "the whole movement" or a number of seconds into a legal length that fits the driver,
  the working frame the driver is scaled down to cover (so a large clip stays under ComfyUI's upload limit) and the
  one line the panel shows, in seconds only (the owner never has to read a frame count);
* :func:`driver_cover_size` is the scaled size itself, the same-aspect, even-sided size whose centre crop still contains
  that working frame (it never enlarges).

The window is trimmed by the existing "Prepare Motion Source" (``motion_source_plan``): it takes exactly the planned
number of frames from the start at the workflow's frame rate, so the movement plays at its real speed.  Nothing here
reads Tk, a file, a clock or a workflow id.
"""

from __future__ import annotations

import math
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any

from src.video.motion_intent import (
    CLAMP_MAXIMUM,
    CLAMP_WINDOW,
    DurationChoice,
    LengthPolicy,
    frames_for_duration,
)

#: The label of the default duration: as much of the driver as the engine can make.
WHOLE_MOVEMENT_LABEL = "Whole movement"
#: What a driven clip sends when the prompt box is empty.  The driving-video engines need an appearance prompt; the
#: panel shows this text before Queue, so nothing is added unseen (D3).  Untested wording.
DEFAULT_DRIVER_PROMPT = "the same subject, clothing and background as the reference image"


def driver_seconds(facts: Any) -> float | None:
    """Seconds of motion a driver clip holds, or ``None`` when it reports neither a duration nor a frame rate."""

    if facts is None:
        return None
    fps = getattr(facts, "reported_fps", None)
    frames = getattr(facts, "reported_frame_count", None)
    if isinstance(frames, int) and frames > 0 and isinstance(fps, (int, float)) and fps > 0:
        return frames / float(fps)
    duration = getattr(facts, "duration_seconds", None)
    if isinstance(duration, (int, float)) and math.isfinite(duration) and duration > 0:
        return float(duration)
    return None


def _even_up(value: float) -> int:
    return max(2, int(math.ceil(value / 2.0 - 1e-9)) * 2)


def driver_cover_size(
    coded_width: int, coded_height: int, rotation_quadrants: int, cover: tuple[int, int]
) -> tuple[int, int] | None:
    """The coded size a driver is scaled down to so it still covers ``cover`` (display width, height); ``None`` when it
    is already no larger than that.

    The result keeps the clip's aspect (a same-aspect copy, never cropped) with even sides.  A clip stored rotated
    keeps its stored orientation (the rotation metadata is kept), so the cover target is turned the same way."""

    width, height = int(coded_width), int(coded_height)
    target_width, target_height = int(cover[0]), int(cover[1])
    if min(width, height, target_width, target_height) <= 0:
        raise ValueError("The driving video's dimensions are invalid.")
    if int(rotation_quadrants or 0) % 2:
        target_width, target_height = target_height, target_width
    scale = max(target_width / width, target_height / height)
    if scale >= 1.0:
        return None
    size = (_even_up(width * scale), _even_up(height * scale))
    if size[0] >= width and size[1] >= height:
        return None
    return size


def _dimensions(value: Any) -> tuple[int, int] | None:
    if not isinstance(value, Mapping):
        return None
    try:
        width, height = int(value["width"]), int(value["height"])
    except (KeyError, TypeError, ValueError):
        return None
    return (width, height) if width > 0 and height > 0 else None


def working_cover(
    source_policy: Mapping[str, Any] | None, source_orientation: str = ""
) -> tuple[int, int] | None:
    """The frame the driver is cropped to by the graph, from the workflow's source-preparation targets.

    With a known source orientation it is that orientation's target; otherwise (several sources, no source yet) it is
    large enough to cover either one.  ``None`` when the workflow declares no targets (nothing is scaled)."""

    policy = source_policy or {}
    portrait = _dimensions(policy.get("portrait_target"))
    landscape = _dimensions(policy.get("landscape_target"))
    if source_orientation == "square":
        source_orientation = str(policy.get("square_orientation") or "portrait")
    if source_orientation == "portrait" and portrait:
        return portrait
    if source_orientation == "landscape" and landscape:
        return landscape
    targets = [target for target in (portrait, landscape) if target]
    if not targets:
        return None
    return (max(t[0] for t in targets), max(t[1] for t in targets))


@dataclass(frozen=True)
class DriverPlan:
    """The length a driver and a requested duration resolve to, and the words the panel shows."""

    choice: DurationChoice
    window_seconds: float | None
    line: str

    @property
    def frames(self) -> int:
        return self.choice.frames


def plan_driver_clip(
    requested_seconds: float | None,
    policy: LengthPolicy,
    window_seconds: float | None,
) -> DriverPlan:
    """The legal length for ``requested_seconds`` (``None`` = the whole movement) that fits a driver of
    ``window_seconds``.  An unreadable window (``None``) keeps the request, or the engine's default."""

    choice = frames_for_duration(requested_seconds, policy, window=window_seconds)
    clip = f"clip {choice.seconds:.1f} s"
    if window_seconds is None:
        line = clip
    else:
        line = f"Driver {window_seconds:.1f} s · {clip}"
    if choice.note:
        line += f" · {choice.note}"
    elif choice.clamped == CLAMP_MAXIMUM:
        line += " (the engine's longest)"
    elif choice.clamped == CLAMP_WINDOW and requested_seconds is not None:
        line += " (the driver ends there)"
    return DriverPlan(choice, window_seconds, line)


#: V1 end frame: what a start-and-end job sends when the prompt box is empty, shown before Queue.  Untested wording.
DEFAULT_BETWEEN_PROMPT = "smooth, natural motion from the first image to the last"


__all__ = [
    "DEFAULT_BETWEEN_PROMPT",
    "DEFAULT_DRIVER_PROMPT",
    "WHOLE_MOVEMENT_LABEL",
    "DriverPlan",
    "driver_cover_size",
    "driver_seconds",
    "plan_driver_clip",
    "working_cover",
]
