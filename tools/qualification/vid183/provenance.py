"""Shared frozen facts and deterministic pair checks for PR-VID-183.

This package deliberately reuses the accepted PR-VID-181 CPU-only pose path.  It
adds no production runtime surface and no alternate implementation of Wan basic
retargeting.
"""

from __future__ import annotations

from pathlib import Path

from tools.qualification.vid181 import provenance as accepted

CHECKPOINT_REPO = accepted.CHECKPOINT_REPO
CHECKPOINT_REVISION = accepted.CHECKPOINT_REVISION
DET_MODEL = accepted.DET_MODEL
FPS = accepted.FPS
FRAMES = accepted.FRAMES
HEIGHT = accepted.HEIGHT
POSE_MODEL = accepted.POSE_MODEL
PROVIDER = accepted.PROVIDER
UPSTREAM_DIVISOR = accepted.UPSTREAM_DIVISOR
UPSTREAM_REPO = accepted.UPSTREAM_REPO
UPSTREAM_SHA = accepted.UPSTREAM_SHA
WIDTH = accepted.WIDTH
adapt_pose_to_frozen = accepted.adapt_pose_to_frozen
assert_isolated_env = accepted.assert_isolated_env
select_indices = accepted.select_indices
sha256_of = accepted.sha256_of
tree_sha256 = accepted.tree_sha256

REFERENCE_SHA256 = "362c86cc83876e340b8927dd54a0f55af1c5fb82c1e9c98d624e67044afa71bb"
SOURCE_START_SECONDS = 8.0
SOURCE_DURATION_SECONDS = 1.625


def control_motion_energy(path: Path) -> float:
    """Mean absolute inter-frame pixel change; a simple no-op guard, not a quality metric."""

    import cv2
    import numpy as np

    capture = cv2.VideoCapture(str(path))
    frames: list[object] = []
    while True:
        ok, frame = capture.read()
        if not ok:
            break
        frames.append(cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY))
    capture.release()
    if len(frames) != FRAMES:
        raise ValueError(f"{path} does not contain exactly {FRAMES} decodable frames")
    changes = [
        np.abs(b.astype(np.int16) - a.astype(np.int16)).mean()
        for a, b in zip(frames, frames[1:], strict=False)
    ]
    return float(np.mean(changes))


def validate_control_pair(control_a: Path, control_b: Path) -> dict[str, float]:
    """Require a real basic-retarget change without erasing temporal locomotion control."""

    import cv2
    import numpy as np

    if sha256_of(control_a) == sha256_of(control_b):
        raise RuntimeError("BASIC_RETARGET_NO_MEANINGFUL_CONTROL_CHANGE: identical control hashes")
    cap_a, cap_b = cv2.VideoCapture(str(control_a)), cv2.VideoCapture(str(control_b))
    pairs: list[float] = []
    try:
        while True:
            ok_a, frame_a = cap_a.read()
            ok_b, frame_b = cap_b.read()
            if ok_a != ok_b:
                raise RuntimeError("BASIC_RETARGET_CONTROL_INVALID: unequal control frame counts")
            if not ok_a:
                break
            if frame_a.shape != frame_b.shape:
                raise RuntimeError("BASIC_RETARGET_CONTROL_INVALID: unequal control geometry")
            pairs.append(float(np.abs(frame_a.astype(np.int16) - frame_b.astype(np.int16)).mean()))
    finally:
        cap_a.release()
        cap_b.release()
    if len(pairs) != FRAMES:
        raise RuntimeError("BASIC_RETARGET_CONTROL_INVALID: controls must have 13 frames")
    mean_difference = float(np.mean(pairs))
    motion_a, motion_b = control_motion_energy(control_a), control_motion_energy(control_b)
    if mean_difference < 1.0:
        raise RuntimeError("BASIC_RETARGET_NO_MEANINGFUL_CONTROL_CHANGE: pixel delta below guard")
    if motion_a <= 0.0 or motion_b <= 0.0 or motion_b < motion_a * 0.05:
        raise RuntimeError("BASIC_RETARGET_CONTROL_INVALID: B did not retain temporal motion")
    return {
        "mean_frame_pixel_delta": mean_difference,
        "motion_energy_a": motion_a,
        "motion_energy_b": motion_b,
    }
