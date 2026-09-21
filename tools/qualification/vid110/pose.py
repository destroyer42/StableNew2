"""Pose-only control video for the VACE comparison (qualification tooling, no Comfy node).

MediaPipe (Apache-2.0, pinned in a disposable environment) finds one body per frame; only a
skeleton drawn on black is kept, so the driving clip's silhouette, background and appearance
never reach the model.  Run inside the pose environment:

    <pose-python> -m tools.qualification.vid110.pose drive.mp4 pose.mp4
"""

from __future__ import annotations

import sys
from pathlib import Path

# MediaPipe pose landmark indices.
NOSE, L_SH, R_SH, L_EL, R_EL, L_WR, R_WR = 0, 11, 12, 13, 14, 15, 16
L_HIP, R_HIP, L_KN, R_KN, L_AN, R_AN, L_FT, R_FT = 23, 24, 25, 26, 27, 28, 31, 32

# (start, end, BGR colour): OpenPose-style limb colouring; -1 marks the neck midpoint.
NECK = -1
LIMBS: tuple[tuple[int, int, tuple[int, int, int]], ...] = (
    (NOSE, NECK, (0, 0, 255)),
    (NECK, R_SH, (0, 85, 255)),
    (NECK, L_SH, (0, 170, 255)),
    (R_SH, R_EL, (0, 255, 255)),
    (R_EL, R_WR, (0, 255, 170)),
    (L_SH, L_EL, (0, 255, 85)),
    (L_EL, L_WR, (0, 255, 0)),
    (NECK, R_HIP, (85, 255, 0)),
    (R_HIP, R_KN, (170, 255, 0)),
    (R_KN, R_AN, (255, 255, 0)),
    (R_AN, R_FT, (255, 200, 0)),
    (NECK, L_HIP, (255, 170, 0)),
    (L_HIP, L_KN, (255, 85, 0)),
    (L_KN, L_AN, (255, 0, 0)),
    (L_AN, L_FT, (255, 0, 85)),
    (L_HIP, R_HIP, (200, 0, 200)),
)


def limb_points(landmarks: dict[int, tuple[float, float, float]], min_visibility: float = 0.2):
    """Turn ``{index: (x, y, visibility)}`` (normalised) into drawable segments.

    Returns ``[(p0, p1, colour), ...]`` with points as normalised ``(x, y)``; limbs whose
    joints are not visible enough are dropped.
    """

    points = dict(landmarks)
    if L_SH in points and R_SH in points:
        left, right = points[L_SH], points[R_SH]
        points[NECK] = (
            (left[0] + right[0]) / 2,
            (left[1] + right[1]) / 2,
            min(left[2], right[2]),
        )
    segments = []
    for start, end, colour in LIMBS:
        if start in points and end in points:
            a, b = points[start], points[end]
            if min(a[2], b[2]) >= min_visibility:
                segments.append(((a[0], a[1]), (b[0], b[1]), colour))
    return segments


def render_skeleton(segments, width: int, height: int):
    import cv2
    import numpy as np

    canvas = np.zeros((height, width, 3), dtype=np.uint8)
    for (x0, y0), (x1, y1), colour in segments:
        p0, p1 = (int(x0 * width), int(y0 * height)), (int(x1 * width), int(y1 * height))
        cv2.line(canvas, p0, p1, colour, 6, cv2.LINE_AA)
        cv2.circle(canvas, p1, 5, colour, -1, cv2.LINE_AA)
    return canvas


def extract(source: Path, target: Path) -> dict[str, int]:
    import cv2
    import mediapipe as mp

    capture = cv2.VideoCapture(str(source))
    fps = capture.get(cv2.CAP_PROP_FPS) or 24.0
    width = int(capture.get(cv2.CAP_PROP_FRAME_WIDTH))
    height = int(capture.get(cv2.CAP_PROP_FRAME_HEIGHT))
    writer = cv2.VideoWriter(str(target), cv2.VideoWriter_fourcc(*"mp4v"), fps, (width, height))
    detected = total = 0
    last = []
    with mp.solutions.pose.Pose(static_image_mode=False, model_complexity=2) as pose:
        while True:
            ok, frame = capture.read()
            if not ok:
                break
            total += 1
            result = pose.process(cv2.cvtColor(frame, cv2.COLOR_BGR2RGB))
            if result.pose_landmarks:
                detected += 1
                marks = {
                    i: (m.x, m.y, m.visibility)
                    for i, m in enumerate(result.pose_landmarks.landmark)
                }
                last = limb_points(marks)
            writer.write(render_skeleton(last, width, height))
    writer.release()
    capture.release()
    return {"frames": total, "detected": detected}


if __name__ == "__main__":
    print(extract(Path(sys.argv[1]), Path(sys.argv[2])))
