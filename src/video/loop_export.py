"""Loop and ping-pong frame sequences for export (PR-VID-LOOP-303).

Cheap perceived length for ambient shots: a clip can play forward then backward (ping-pong) and/or repeat until it
fills a requested duration. Pure frame-list arithmetic, no I/O: the exporter encodes whatever list it is given, and
the run manifest records which mode produced it.

The ping-pong cycle is ``frames + frames[-2:0:-1]``: the two end frames are not repeated at the turn, so the cycle
joins back onto its first frame with no held or doubled frame. A repeat count is rounded up to whole cycles, so the
loop point stays seamless instead of cutting a cycle short.
"""

from __future__ import annotations

import math
from collections.abc import Sequence
from typing import Any, Literal

LoopMode = Literal["none", "ping_pong"]
LOOP_MODES: tuple[str, ...] = ("none", "ping_pong")
# A longer request is refused rather than quietly clamped.
MAX_EXTEND_SECONDS = 60.0
# The exporter writes every frame to disk, so the whole sequence is bounded, not only the duration.
MAX_LOOP_FRAMES = 3600


def loop_export_validation_error(*, mode: str, extend_to_seconds: float) -> str | None:
    """The readable reason a loop request is invalid, or ``None``."""

    if mode not in LOOP_MODES:
        return f"Invalid loop mode: {mode!r} (expected one of {', '.join(LOOP_MODES)})"
    if not math.isfinite(extend_to_seconds) or extend_to_seconds < 0:
        return "extend_to_seconds must be 0 (off) or a positive number of seconds"
    if extend_to_seconds > MAX_EXTEND_SECONDS:
        return f"extend_to_seconds must be at most {MAX_EXTEND_SECONDS:.0f} seconds"
    return None


def ping_pong_cycle[T](frames: Sequence[T]) -> list[T]:
    """Forward then backward without repeating the end frames; a clip under 3 frames has no interior."""

    items = list(frames)
    if len(items) < 3:
        return items
    return items + items[-2:0:-1]


def build_loop_frames[T](
    frames: Sequence[T], *, mode: str, extend_to_seconds: float, fps: int
) -> tuple[list[T], dict[str, Any]]:
    """The frame sequence to export and the record of how it was made.

    The returned list references the input frames (it repeats them, it does not copy them). With the defaults
    (``none``, ``0``) the sequence is the input unchanged and the record says so.
    """

    error = loop_export_validation_error(mode=mode, extend_to_seconds=extend_to_seconds)
    if error:
        raise ValueError(error)
    if fps < 1:
        raise ValueError("fps must be a positive integer")
    base = list(frames)
    cycle = ping_pong_cycle(base) if mode == "ping_pong" else base
    cycles = 1
    if extend_to_seconds > 0 and cycle:
        cycles = max(1, math.ceil(extend_to_seconds * fps / len(cycle)))
    total = len(cycle) * cycles
    if total > MAX_LOOP_FRAMES:
        raise ValueError(
            f"The requested loop would export {total} frames; the limit is {MAX_LOOP_FRAMES}. "
            "Ask for a shorter duration."
        )
    exported = cycle * cycles
    record = {
        "mode": mode,
        "extend_to_seconds": float(extend_to_seconds),
        "fps": int(fps),
        "base_frame_count": len(base),
        "cycle_frame_count": len(cycle),
        "cycles": cycles,
        "output_frame_count": len(exported),
        "output_seconds": round(len(exported) / fps, 3),
    }
    return exported, record


__all__ = [
    "LOOP_MODES",
    "MAX_EXTEND_SECONDS",
    "MAX_LOOP_FRAMES",
    "LoopMode",
    "build_loop_frames",
    "loop_export_validation_error",
    "ping_pong_cycle",
]
