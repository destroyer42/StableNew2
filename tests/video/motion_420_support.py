"""Deterministic fixtures for the PR-VID-MOTION-420 tests: synthetic clips with a measurable moving subject.

A clip is a dark background with a bright square that moves a fixed number of pixels per frame, written as
PNGs and encoded by the installed FFmpeg (lossless H.264), so every test can state exactly where the subject is
at each frame.  Nothing here generates anything, starts a runtime or touches the network.
"""

from __future__ import annotations

import subprocess
from pathlib import Path
from typing import Any

import numpy as np
import pytest
from PIL import Image, ImageDraw

from src.pipeline.video import resolve_ffmpeg_executable
from src.video.container_metadata import resolve_ffprobe_executable
from src.video.motion_source_plan import MotionSourceContract

FFMPEG = resolve_ffmpeg_executable()
FFPROBE = resolve_ffprobe_executable()
needs_ffmpeg = pytest.mark.skipif(
    FFMPEG is None or FFPROBE is None, reason="FFmpeg/FFprobe are not installed"
)

DRIVE_ID = "wan_animate2_drive_i2v_v1"
DRIVE_VERSION = "1.2.0"
BACKGROUND = (12, 18, 40)
SUBJECT = (250, 250, 250)

#: The registered Wan-Animate-2 declaration (portrait 480x832, landscape 832x480, square -> portrait).
SOURCE_POLICY: dict[str, Any] = {
    "resize_policy": "cover_resize_center_crop",
    "portrait_target": {"width": 480, "height": 832},
    "landscape_target": {"width": 832, "height": 480},
    "square_orientation": "portrait",
}


def contract(frames: int = 17, *, version: str = DRIVE_VERSION) -> MotionSourceContract:
    return MotionSourceContract(DRIVE_ID, version, frames, 24, "rev", "rule")


def source_image(path: Path, size: tuple[int, int] = (240, 416), color=(90, 60, 130)) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    Image.new("RGB", size, color).save(path)
    return path


def moving_square_clip(
    tmp_path: Path,
    name: str = "driver.mp4",
    *,
    size: tuple[int, int] = (270, 480),
    frames: int = 20,
    rate: str = "24",
    start: tuple[int, int] = (40, 100),
    step: tuple[int, int] = (6, 0),
    edge: int = 24,
    rotate: int = 0,
) -> Path:
    """A clip whose white ``edge``-pixel square starts at ``start`` and moves ``step`` pixels per frame."""

    assert FFMPEG is not None
    folder = tmp_path / f"{Path(name).stem}_frames"
    folder.mkdir(parents=True, exist_ok=True)
    for index in range(frames):
        image = Image.new("RGB", size, BACKGROUND)
        x, y = start[0] + step[0] * index, start[1] + step[1] * index
        ImageDraw.Draw(image).rectangle([x, y, x + edge - 1, y + edge - 1], fill=SUBJECT)
        image.save(folder / f"f_{index:04d}.png")
    path = tmp_path / name
    command = [
        str(FFMPEG), "-v", "error", "-y", "-framerate", rate, "-i", str(folder / "f_%04d.png"),
        "-c:v", "libx264", "-qp", "0", "-pix_fmt", "yuv444p",
    ]  # fmt: skip
    if rotate:
        command += ["-metadata:s:v:0", f"rotate={rotate}"]
    subprocess.run([*command, str(path)], check=True, capture_output=True, timeout=120)
    return path


def decode_rgb_frames(path: Path, count: int | None = None) -> list[np.ndarray]:
    """Every frame of ``path`` as an ``(h, w, 3)`` array (display orientation), decoded here by FFmpeg itself."""

    assert FFMPEG is not None
    folder = path.parent / f"{path.stem}_decoded"
    folder.mkdir(parents=True, exist_ok=True)
    for stale in folder.glob("*.png"):
        stale.unlink()
    subprocess.run(
        [str(FFMPEG), "-v", "error", "-nostdin", "-i", str(path), "-map", "0:v:0", "-an",
         "-fps_mode", "passthrough", "-pix_fmt", "rgb24", str(folder / "d_%05d.png")],
        check=True, capture_output=True, timeout=120,
    )  # fmt: skip
    frames = [
        np.asarray(Image.open(item).convert("RGB")) for item in sorted(folder.glob("d_*.png"))
    ]
    return frames[:count] if count is not None else frames


def subject_centroid(frame: np.ndarray, threshold: int = 200) -> tuple[float, float] | None:
    """Centre of the bright subject (x, y) in pixel-edge coordinates, or None when it is not visible."""

    ys, xs = np.where(frame.min(axis=2) > threshold)
    if xs.size == 0:
        return None
    return (float(xs.mean()) + 0.5, float(ys.mean()) + 0.5)
