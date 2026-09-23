"""Deterministic 480x832 (native resolution, no crop, no resize) adaptation of the same real
PR-VID-110 pose source PR-VID-170 Case C used, reusing PR-VID-160C's exact
``sample_indices``/``read_frames`` functions unchanged so the selected temporal indices are
identical by construction -- this package's only intended variable versus PR-VID-170 Case C is
spatial resolution, not motion timing.

The source (``reports/vid110/inputs/pose_user.mp4``) is already 480x832, so this adaptation is
purely a temporal resample (select the same 13 frames PR-VID-170 Case C selected) at native
geometry; no cv2.resize/crop step is needed or performed.
"""

from __future__ import annotations

from pathlib import Path

from tools.qualification.vid160c.pose_asset import (
    SOURCE_POSE_VIDEO,
    TARGET_FRAMES,
    read_frames,
    sample_indices,
    sha256_of,
)

TARGET_FPS = 8.0

__all__ = ["SOURCE_POSE_VIDEO", "TARGET_FRAMES", "TARGET_FPS", "adapt_pose_video_native", "sha256_of"]


def adapt_pose_video_native(
    source: Path = SOURCE_POSE_VIDEO,
    target: Path = Path("reports/vid175/case_c_480x832_13f.mp4"),
) -> tuple[Path, list[int], tuple[int, int]]:
    """Select the same PR-VID-160C/170-Case-C temporal indices, write them at the source's native
    resolution (no crop, no resize). Returns (target path, selected indices, (width, height))."""

    import cv2

    frames = read_frames(source)
    if len(frames) < 2:
        raise ValueError(f"{source} has fewer than 2 decodable frames")
    indices = sample_indices(len(frames), TARGET_FRAMES)
    height, width = frames[0].shape[:2]
    target.parent.mkdir(parents=True, exist_ok=True)
    fourcc = cv2.VideoWriter_fourcc(*"mp4v")
    writer = cv2.VideoWriter(str(target), fourcc, TARGET_FPS, (width, height))
    try:
        for index in indices:
            writer.write(frames[index])
    finally:
        writer.release()
    return target, indices, (width, height)
