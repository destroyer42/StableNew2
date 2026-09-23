"""Deterministic adaptation of the existing PR-VID-110 skeleton-only pose control clip to the
frozen PR-VID-160B probe geometry (256x256, 13 frames). No new dependency: reuses the same
OpenCV/numpy already used by ``tools/qualification/vid110/metrics.py``.

The source, ``reports/vid110/inputs/pose_user.mp4`` (480x832, 24 fps, 49 frames), is an
already-accepted, skeleton-on-black control clip (no RGB scene/background) from PR-VID-110's
pose-skeleton-only lane. Only geometry/frame-count are changed here; no re-extraction, no new
model, no new custom node.
"""

from __future__ import annotations

import hashlib
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    import numpy as np

SOURCE_POSE_VIDEO = Path("reports/vid110/inputs/pose_user.mp4")
TARGET_WIDTH = 256
TARGET_HEIGHT = 256
TARGET_FRAMES = 13
TARGET_FPS = 8.0


def sample_indices(total: int, count: int) -> list[int]:
    """Evenly spaced frame indices over ``[0, total-1]`` -- the same convention as
    ``tools.qualification.vid110.metrics.contact_sheet``."""

    import numpy as np

    if total < 1 or count < 1:
        raise ValueError("total and count must be positive")
    return [int(i) for i in np.linspace(0, total - 1, num=min(count, total))]


def center_square_crop(frame: np.ndarray) -> np.ndarray:
    height, width = frame.shape[:2]
    side = min(height, width)
    top = (height - side) // 2
    left = (width - side) // 2
    return frame[top : top + side, left : left + side]


def read_frames(path: Path) -> list[np.ndarray]:
    import cv2

    capture = cv2.VideoCapture(str(path))
    frames: list[np.ndarray] = []
    while True:
        ok, frame = capture.read()
        if not ok:
            break
        frames.append(frame)
    capture.release()
    return frames


def adapt_pose_video(
    source: Path = SOURCE_POSE_VIDEO,
    target: Path = Path("reports/vid160c/pose_control_256x256_13f.mp4"),
) -> Path:
    """Deterministically resample ``source`` to exactly ``TARGET_FRAMES`` square frames."""

    import cv2

    frames = read_frames(source)
    if len(frames) < 2:
        raise ValueError(f"{source} has fewer than 2 decodable frames")
    indices = sample_indices(len(frames), TARGET_FRAMES)
    target.parent.mkdir(parents=True, exist_ok=True)
    fourcc = cv2.VideoWriter_fourcc(*"mp4v")
    writer = cv2.VideoWriter(str(target), fourcc, TARGET_FPS, (TARGET_WIDTH, TARGET_HEIGHT))
    try:
        for index in indices:
            square = center_square_crop(frames[index])
            resized = cv2.resize(
                square, (TARGET_WIDTH, TARGET_HEIGHT), interpolation=cv2.INTER_AREA
            )
            writer.write(resized)
    finally:
        writer.release()
    return target


def sha256_of(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()
