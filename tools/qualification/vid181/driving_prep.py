"""Deterministic pre-step for real driving footage: trim a time window, take a FIXED (non-tracking)
crop with exactly the 464:832 (= 29:52) aspect of the accepted pose geometry, and scale it to
464x832. A fixed crop never removes image-space root translation and never stretches: it only
selects the region the subject occupies so the upstream-rendered pose is not a tiny figure in a
letterboxed landscape frame. The crop is a recorded, reproducible input choice (not pose editing).
"""

from __future__ import annotations

import subprocess
from pathlib import Path

OUT_W = 464
OUT_H = 832
ASPECT_UNIT_W = 29  # 464 / 16
ASPECT_UNIT_H = 52  # 832 / 16


def crop_size(k: int) -> tuple[int, int]:
    """Exact-aspect crop window: 29k x 52k."""

    if k < 1:
        raise ValueError("k must be positive")
    return ASPECT_UNIT_W * k, ASPECT_UNIT_H * k


def ffmpeg_filter(x: int, y: int, k: int) -> str:
    width, height = crop_size(k)
    if x < 0 or y < 0:
        raise ValueError("crop origin must be non-negative")
    return f"crop={width}:{height}:{x}:{y},scale={OUT_W}:{OUT_H}:flags=lanczos"


def prepare(
    source: Path, target: Path, *, start_s: float, duration_s: float, x: int, y: int, k: int
) -> dict[str, object]:
    """Trim + fixed crop + scale with ffmpeg (audio dropped, near-lossless H.264)."""

    target.parent.mkdir(parents=True, exist_ok=True)
    vf = ffmpeg_filter(x, y, k)
    command = [
        "ffmpeg", "-v", "error", "-y", "-ss", f"{start_s}", "-t", f"{duration_s}",
        "-i", str(source), "-an", "-vf", vf,
        "-c:v", "libx264", "-crf", "12", "-preset", "slow", "-pix_fmt", "yuv420p", str(target),
    ]
    subprocess.run(command, check=True)
    width, height = crop_size(k)
    return {
        "start_s": start_s,
        "duration_s": duration_s,
        "crop": {"x": x, "y": y, "width": width, "height": height},
        "scale_to": [OUT_W, OUT_H],
        "filter": vf,
        "tracking": False,
    }
