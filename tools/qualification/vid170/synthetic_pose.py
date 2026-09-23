"""Deterministic synthetic 2D skeleton pose-control sequences for Cases A/B, used only because no
suitable existing real gesture/locomotion driving clip was found locally, and the immediately
available official Wan Animate example ships exactly one clip (not three distinct motion types) --
see the PR-VID-170 report's driving-motion provenance section for the full sourcing rationale.

This is explicitly **not** real motion capture. It is a clearly labeled, reproducible procedural
construction (pure 2D forward kinematics, drawn with the same OpenCV/numpy already used by
``tools.qualification.vid160c.pose_asset``) that renders a colored-line stick figure on a black
background, matching the general visual convention of the real, accepted
``reports/vid110/inputs/pose_user.mp4`` asset (used unchanged for Case C). No generative model,
no pose-extraction library (MediaPipe/DWPose/``comfyui_controlnet_aux``), and no new dependency is
involved -- only straight-line drawing from computed joint coordinates.

Interpretive caveat carried into the report: this mechanically tests whether
``WanAnimateToVideo`` follows an unambiguous, idealized pose signal (clear joint articulation and,
for Case B, clear root/pelvis translation across frames) -- not robustness to real-world
motion-capture noise.
"""

from __future__ import annotations

import math
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    import numpy as np

WIDTH = 256
HEIGHT = 256
FRAMES = 13
FPS = 8.0

# BGR colors loosely matching the real pose_user.mp4 asset's palette (head/red, torso/cyan,
# arms/green, legs/blue-purple) -- exact color fidelity is not required by WanAnimateToVideo,
# which treats pose_video as plain IMAGE frames.
_HEAD = (60, 60, 220)
_TORSO = (220, 200, 60)
_ARM = (60, 200, 60)
_LEG_NEAR = (220, 120, 60)
_LEG_FAR = (200, 60, 200)
_THICKNESS = 4


def _draw_skeleton(
    canvas: np.ndarray,
    *,
    hip: tuple[float, float],
    neck: tuple[float, float],
    head: tuple[float, float],
    shoulder_l: tuple[float, float],
    elbow_l: tuple[float, float],
    wrist_l: tuple[float, float],
    shoulder_r: tuple[float, float],
    elbow_r: tuple[float, float],
    wrist_r: tuple[float, float],
    hip_l: tuple[float, float],
    knee_l: tuple[float, float],
    ankle_l: tuple[float, float],
    hip_r: tuple[float, float],
    knee_r: tuple[float, float],
    ankle_r: tuple[float, float],
) -> None:
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

    line(neck, hip, _TORSO)
    line(neck, shoulder_l, _TORSO)
    line(neck, shoulder_r, _TORSO)
    line(shoulder_l, elbow_l, _ARM)
    line(elbow_l, wrist_l, _ARM)
    line(shoulder_r, elbow_r, _ARM)
    line(elbow_r, wrist_r, _ARM)
    line(hip, hip_l, _TORSO)
    line(hip, hip_r, _TORSO)
    line(hip_l, knee_l, _LEG_FAR)
    line(knee_l, ankle_l, _LEG_FAR)
    line(hip_r, knee_r, _LEG_NEAR)
    line(knee_r, ankle_r, _LEG_NEAR)
    cv2.circle(canvas, (int(round(head[0])), int(round(head[1]))), 14, _HEAD, -1, cv2.LINE_AA)


def _neutral_frame_points(hip_x: float, hip_y: float) -> dict[str, tuple[float, float]]:
    neck = (hip_x, hip_y - 55)
    head = (hip_x, neck[1] - 22)
    shoulder_l = (hip_x - 18, neck[1])
    shoulder_r = (hip_x + 18, neck[1])
    hip_l = (hip_x - 12, hip_y)
    hip_r = (hip_x + 12, hip_y)
    return {
        "hip": (hip_x, hip_y),
        "neck": neck,
        "head": head,
        "shoulder_l": shoulder_l,
        "shoulder_r": shoulder_r,
        "hip_l": hip_l,
        "hip_r": hip_r,
    }


def render_arm_raise(target: Path) -> Path:
    """Case A: standing figure, still legs/left arm; right arm raises from the side to overhead
    and back down across the 13 frames (a triangular angle profile peaking at the midpoint)."""

    import cv2
    import numpy as np

    target.parent.mkdir(parents=True, exist_ok=True)
    fourcc = cv2.VideoWriter_fourcc(*"mp4v")
    writer = cv2.VideoWriter(str(target), fourcc, FPS, (WIDTH, HEIGHT))
    try:
        base = _neutral_frame_points(hip_x=WIDTH / 2, hip_y=HEIGHT * 0.62)
        upper_arm, forearm = 32.0, 30.0
        for t in range(FRAMES):
            canvas = np.zeros((HEIGHT, WIDTH, 3), dtype=np.uint8)
            # 0 rad = arm hanging straight down; pi rad = arm straight overhead.
            raise_fraction = math.sin(math.pi * t / (FRAMES - 1))
            angle = math.pi * raise_fraction
            shoulder_r = base["shoulder_r"]
            elbow_r = (
                shoulder_r[0] + upper_arm * math.sin(angle),
                shoulder_r[1] - upper_arm * math.cos(angle),
            )
            wrist_r = (
                elbow_r[0] + forearm * math.sin(angle * 0.9),
                elbow_r[1] - forearm * math.cos(angle * 0.9),
            )
            # Left arm stays relaxed at the side throughout.
            shoulder_l = base["shoulder_l"]
            elbow_l = (shoulder_l[0] - 6, shoulder_l[1] + upper_arm)
            wrist_l = (elbow_l[0] - 2, elbow_l[1] + forearm)
            knee_l = (base["hip_l"][0] - 2, base["hip_l"][1] + 50)
            ankle_l = (knee_l[0], knee_l[1] + 50)
            knee_r = (base["hip_r"][0] + 2, base["hip_r"][1] + 50)
            ankle_r = (knee_r[0], knee_r[1] + 50)
            _draw_skeleton(
                canvas,
                hip=base["hip"],
                neck=base["neck"],
                head=base["head"],
                shoulder_l=shoulder_l,
                elbow_l=elbow_l,
                wrist_l=wrist_l,
                shoulder_r=shoulder_r,
                elbow_r=elbow_r,
                wrist_r=wrist_r,
                hip_l=base["hip_l"],
                knee_l=knee_l,
                ankle_l=ankle_l,
                hip_r=base["hip_r"],
                knee_r=knee_r,
                ankle_r=ankle_r,
            )
            writer.write(canvas)
    finally:
        writer.release()
    return target


def render_walk_forward(target: Path) -> Path:
    """Case B: side-view walk cycle -- the hip/root translates left-to-right across the frame
    (~2 steps of forward displacement) while the legs swing in alternating phase and the arms
    swing in opposition, so the pose signal unambiguously encodes both stepping articulation and
    whole-body translation, not just in-place leg motion."""

    import cv2
    import numpy as np

    target.parent.mkdir(parents=True, exist_ok=True)
    fourcc = cv2.VideoWriter_fourcc(*"mp4v")
    writer = cv2.VideoWriter(str(target), fourcc, FPS, (WIDTH, HEIGHT))
    try:
        hip_y = HEIGHT * 0.62
        start_x, end_x = WIDTH * 0.32, WIDTH * 0.68  # ~2 steps of lateral translation
        thigh, shin, upper_arm, forearm = 42.0, 42.0, 30.0, 28.0
        cycles = 2.0  # two full leg-swing cycles across the sequence == ~two steps
        for t in range(FRAMES):
            canvas = np.zeros((HEIGHT, WIDTH, 3), dtype=np.uint8)
            progress = t / (FRAMES - 1)
            hip_x = start_x + (end_x - start_x) * progress
            base = _neutral_frame_points(hip_x=hip_x, hip_y=hip_y)
            phase = 2 * math.pi * cycles * progress
            swing = math.radians(28)
            leg_r_angle = swing * math.sin(phase)
            leg_l_angle = swing * math.sin(phase + math.pi)
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

            arm_r_angle = -leg_l_angle * 0.7  # opposite-arm swing
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
                hip=base["hip"],
                neck=base["neck"],
                head=base["head"],
                shoulder_l=base["shoulder_l"],
                elbow_l=elbow_l,
                wrist_l=wrist_l,
                shoulder_r=base["shoulder_r"],
                elbow_r=elbow_r,
                wrist_r=wrist_r,
                hip_l=base["hip_l"],
                knee_l=knee_l,
                ankle_l=ankle_l,
                hip_r=base["hip_r"],
                knee_r=knee_r,
                ankle_r=ankle_r,
            )
            writer.write(canvas)
    finally:
        writer.release()
    return target
