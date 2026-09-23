"""Deterministic native-resolution (480x832) synthetic pose-control sequences for PR-VID-180
Case A (articulated gesture) and Case B (locomotion/root translation).

Reuses PR-VID-170's ``synthetic_pose.py`` motion *semantics* -- temporal phase, arm-angle
progression, gait-cycle count, and normalized root-translation fraction of canvas width -- at
StableNew's portrait 480x832 envelope instead of VID-170's square 256x256 canvas. VID-170's
module and historical fixtures (``tools.qualification.vid170.synthetic_pose``,
``reports/vid170/case_a_arm_raise.mp4``, ``reports/vid170/case_b_walk_forward.mp4``) are left
completely unmodified: this is a clean-room reimplementation of the same formulas, parameterized
by canvas width/height, not an edit of or import from that module's render functions.

The resolution-independent quantities -- arm-angle progression as a function of frame index,
gait phase, and hip-translation fraction of canvas width -- are exposed here as pure functions
(``arm_raise_angle``, ``gait_phase``, ``leg_swing_angle``, ``hip_x_fraction``) so tests can prove
frame-by-frame that they are numerically identical to VID-170 Case A/B's formulas, independent of
canvas size. Absolute pixel quantities (limb lengths, joint offsets) are scaled by
``SCALE = WIDTH / vid170.synthetic_pose.WIDTH`` so the rendered figure stays proportioned to the
new, wider-than-256 canvas; scaling the shared (constrained) width dimension keeps the figure
within frame in the taller 480x832 portrait envelope.
"""

from __future__ import annotations

import hashlib
import math
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    import numpy as np

WIDTH = 480
HEIGHT = 832
FRAMES = 13
FPS = 8.0

_OLD_WIDTH = 256  # tools.qualification.vid170.synthetic_pose.WIDTH
SCALE = WIDTH / _OLD_WIDTH  # 1.875

_HEAD = (60, 60, 220)
_TORSO = (220, 200, 60)
_ARM = (60, 200, 60)
_LEG_NEAR = (220, 120, 60)
_LEG_FAR = (200, 60, 200)
_THICKNESS = max(1, round(4 * SCALE))

# Normalized constants -- identical values to tools.qualification.vid170.synthetic_pose, kept
# here as named constants (not imported) so this module has no runtime dependency on VID-170.
HIP_Y_FRACTION = 0.62
HIP_X_START_FRACTION = 0.32
HIP_X_END_FRACTION = 0.68
GAIT_CYCLES = 2.0
GAIT_SWING_DEG = 28.0

__all__ = [
    "WIDTH",
    "HEIGHT",
    "FRAMES",
    "FPS",
    "SCALE",
    "arm_raise_angle",
    "gait_phase",
    "leg_swing_angle",
    "hip_x_fraction",
    "render_arm_raise_native",
    "render_walk_forward_native",
    "sha256_of",
]


def arm_raise_angle(t: int, frames: int = FRAMES) -> float:
    """Case A: right-arm angle in radians (0 = hanging, pi = overhead) at frame ``t``.

    Resolution-independent; identical formula to VID-170 Case A's ``angle``."""

    raise_fraction = math.sin(math.pi * t / (frames - 1))
    return math.pi * raise_fraction


def gait_phase(t: int, frames: int = FRAMES, cycles: float = GAIT_CYCLES) -> float:
    """Case B: gait-cycle phase in radians at frame ``t``. Resolution-independent; identical
    formula to VID-170 Case B's ``phase``."""

    progress = t / (frames - 1)
    return 2 * math.pi * cycles * progress


def leg_swing_angle(phase: float, *, opposite: bool = False) -> float:
    """Case B: one leg's swing angle in radians at a given gait ``phase``. Resolution-independent;
    identical formula to VID-170 Case B's ``leg_r_angle``/``leg_l_angle``."""

    swing = math.radians(GAIT_SWING_DEG)
    return swing * math.sin(phase + (math.pi if opposite else 0.0))


def hip_x_fraction(t: int, frames: int = FRAMES) -> float:
    """Case B: hip-x position as a fraction of canvas width at frame ``t`` (root/pelvis
    translation). Resolution-independent; identical fractions to VID-170 Case B's
    ``start_x``/``end_x`` (0.32 * WIDTH, 0.68 * WIDTH)."""

    progress = t / (frames - 1)
    return HIP_X_START_FRACTION + (HIP_X_END_FRACTION - HIP_X_START_FRACTION) * progress


def _draw_skeleton(canvas: np.ndarray, points: dict[str, tuple[float, float]]) -> None:
    import cv2

    def line(p1: tuple[float, float], p2: tuple[float, float], color: tuple[int, int, int]) -> None:
        cv2.line(
            canvas,
            (int(round(p1[0])), int(round(p1[1]))),
            (int(round(p2[0])), int(round(p2[1]))),
            color,
            _THICKNESS,
            cv2.LINE_AA,
        )

    p = points
    line(p["neck"], p["hip"], _TORSO)
    line(p["neck"], p["shoulder_l"], _TORSO)
    line(p["neck"], p["shoulder_r"], _TORSO)
    line(p["shoulder_l"], p["elbow_l"], _ARM)
    line(p["elbow_l"], p["wrist_l"], _ARM)
    line(p["shoulder_r"], p["elbow_r"], _ARM)
    line(p["elbow_r"], p["wrist_r"], _ARM)
    line(p["hip"], p["hip_l"], _TORSO)
    line(p["hip"], p["hip_r"], _TORSO)
    line(p["hip_l"], p["knee_l"], _LEG_FAR)
    line(p["knee_l"], p["ankle_l"], _LEG_FAR)
    line(p["hip_r"], p["knee_r"], _LEG_NEAR)
    line(p["knee_r"], p["ankle_r"], _LEG_NEAR)
    cv2.circle(
        canvas,
        (int(round(p["head"][0])), int(round(p["head"][1]))),
        max(1, round(14 * SCALE)),
        _HEAD,
        -1,
        cv2.LINE_AA,
    )


def _neutral_frame_points(hip_x: float, hip_y: float) -> dict[str, tuple[float, float]]:
    neck = (hip_x, hip_y - 55 * SCALE)
    head = (hip_x, neck[1] - 22 * SCALE)
    shoulder_l = (hip_x - 18 * SCALE, neck[1])
    shoulder_r = (hip_x + 18 * SCALE, neck[1])
    hip_l = (hip_x - 12 * SCALE, hip_y)
    hip_r = (hip_x + 12 * SCALE, hip_y)
    return {
        "hip": (hip_x, hip_y),
        "neck": neck,
        "head": head,
        "shoulder_l": shoulder_l,
        "shoulder_r": shoulder_r,
        "hip_l": hip_l,
        "hip_r": hip_r,
    }


def render_arm_raise_native(
    target: Path, *, width: int = WIDTH, height: int = HEIGHT, frames: int = FRAMES
) -> Path:
    """Case A at native 480x832: same normalized arm-angle progression as VID-170 Case A, right
    arm raises from relaxed to overhead and back; left arm/legs stay still."""

    import cv2
    import numpy as np

    target.parent.mkdir(parents=True, exist_ok=True)
    fourcc = cv2.VideoWriter_fourcc(*"mp4v")
    writer = cv2.VideoWriter(str(target), fourcc, FPS, (width, height))
    try:
        base = _neutral_frame_points(hip_x=width / 2, hip_y=height * HIP_Y_FRACTION)
        upper_arm, forearm = 32.0 * SCALE, 30.0 * SCALE
        for t in range(frames):
            canvas = np.zeros((height, width, 3), dtype=np.uint8)
            angle = arm_raise_angle(t, frames)
            shoulder_r = base["shoulder_r"]
            elbow_r = (
                shoulder_r[0] + upper_arm * math.sin(angle),
                shoulder_r[1] - upper_arm * math.cos(angle),
            )
            wrist_r = (
                elbow_r[0] + forearm * math.sin(angle * 0.9),
                elbow_r[1] - forearm * math.cos(angle * 0.9),
            )
            shoulder_l = base["shoulder_l"]
            elbow_l = (shoulder_l[0] - 6 * SCALE, shoulder_l[1] + upper_arm)
            wrist_l = (elbow_l[0] - 2 * SCALE, elbow_l[1] + forearm)
            knee_l = (base["hip_l"][0] - 2 * SCALE, base["hip_l"][1] + 50 * SCALE)
            ankle_l = (knee_l[0], knee_l[1] + 50 * SCALE)
            knee_r = (base["hip_r"][0] + 2 * SCALE, base["hip_r"][1] + 50 * SCALE)
            ankle_r = (knee_r[0], knee_r[1] + 50 * SCALE)
            _draw_skeleton(
                canvas,
                {
                    **base,
                    "shoulder_l": shoulder_l,
                    "elbow_l": elbow_l,
                    "wrist_l": wrist_l,
                    "shoulder_r": shoulder_r,
                    "elbow_r": elbow_r,
                    "wrist_r": wrist_r,
                    "knee_l": knee_l,
                    "ankle_l": ankle_l,
                    "knee_r": knee_r,
                    "ankle_r": ankle_r,
                },
            )
            writer.write(canvas)
    finally:
        writer.release()
    return target


def render_walk_forward_native(
    target: Path, *, width: int = WIDTH, height: int = HEIGHT, frames: int = FRAMES
) -> Path:
    """Case B at native 480x832: same normalized gait phase, alternating-leg swing and
    root-translation fraction of width as VID-170 Case B (~2 gait cycles, hip translates from
    0.32*width to 0.68*width, opposing arm swing)."""

    import cv2
    import numpy as np

    target.parent.mkdir(parents=True, exist_ok=True)
    fourcc = cv2.VideoWriter_fourcc(*"mp4v")
    writer = cv2.VideoWriter(str(target), fourcc, FPS, (width, height))
    try:
        hip_y = height * HIP_Y_FRACTION
        thigh = shin = 42.0 * SCALE
        upper_arm, forearm = 30.0 * SCALE, 28.0 * SCALE
        for t in range(frames):
            canvas = np.zeros((height, width, 3), dtype=np.uint8)
            hip_x = hip_x_fraction(t, frames) * width
            base = _neutral_frame_points(hip_x=hip_x, hip_y=hip_y)
            phase = gait_phase(t, frames)
            leg_r_angle = leg_swing_angle(phase, opposite=False)
            leg_l_angle = leg_swing_angle(phase, opposite=True)
            knee_bend_r = max(0.0, math.sin(phase)) * math.radians(20)
            knee_bend_l = max(0.0, math.sin(phase + math.pi)) * math.radians(20)

            def leg_points(
                hip_pt: tuple[float, float], angle: float, knee_bend: float
            ) -> tuple[tuple[float, float], tuple[float, float]]:
                knee = (hip_pt[0] + thigh * math.sin(angle), hip_pt[1] + thigh * math.cos(angle))
                ankle_angle = angle + knee_bend
                ankle = (
                    knee[0] + shin * math.sin(ankle_angle),
                    knee[1] + shin * math.cos(ankle_angle),
                )
                return knee, ankle

            knee_r, ankle_r = leg_points(base["hip_r"], leg_r_angle, knee_bend_r)
            knee_l, ankle_l = leg_points(base["hip_l"], leg_l_angle, knee_bend_l)

            arm_r_angle = -leg_l_angle * 0.7
            arm_l_angle = -leg_r_angle * 0.7
            elbow_r = (
                base["shoulder_r"][0] + upper_arm * math.sin(arm_r_angle),
                base["shoulder_r"][1] + upper_arm * math.cos(arm_r_angle),
            )
            wrist_r = (
                elbow_r[0] + forearm * math.sin(arm_r_angle),
                elbow_r[1] + forearm * math.cos(arm_r_angle),
            )
            elbow_l = (
                base["shoulder_l"][0] + upper_arm * math.sin(arm_l_angle),
                base["shoulder_l"][1] + upper_arm * math.cos(arm_l_angle),
            )
            wrist_l = (
                elbow_l[0] + forearm * math.sin(arm_l_angle),
                elbow_l[1] + forearm * math.cos(arm_l_angle),
            )
            _draw_skeleton(
                canvas,
                {
                    **base,
                    "elbow_l": elbow_l,
                    "wrist_l": wrist_l,
                    "elbow_r": elbow_r,
                    "wrist_r": wrist_r,
                    "knee_l": knee_l,
                    "ankle_l": ankle_l,
                    "knee_r": knee_r,
                    "ankle_r": ankle_r,
                },
            )
            writer.write(canvas)
    finally:
        writer.release()
    return target


def sha256_of(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()
