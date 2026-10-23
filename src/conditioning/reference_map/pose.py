"""OpenPose maps from DWPose whole-body keypoints: pure decoding helpers and one deterministic renderer (PR-IMG-CNET-230).

Nothing here loads a model. The contained worker runs the pinned DWPose ONNX files (person detector, whole-body pose
estimator) and uses the numpy helpers below to decode their raw tensors; the parent turns the worker's keypoints into the
skeleton image ControlNet OpenPose units expect (black background, coloured limbs and joints, white face dots, rainbow
hand edges) with ``render_pose``. The decoding and drawing follow the reference DWPose / OpenPose conventions; the exact
upstream preprocessing revision is not pinned by the curated catalog, so physical agreement is a qualification item.

Keypoint layout is COCO-WholeBody: 0-16 body, 17-22 feet, 23-90 face (68), 91-111 left hand, 112-132 right hand.
"""

from __future__ import annotations

import colorsys
import math
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Any

import numpy as np

from src.conditioning.reference_map.contracts import (
    CODE_INFERENCE,
    CODE_NO_PEOPLE,
    MethodIdentity,
    ReferenceMapError,
)

METHOD_ID = "dwpose-onnx"
METHOD_VERSION = 1
KEYPOINTS = 133
MAX_PEOPLE = 8
MIN_BODY_POINTS = 4
SCORE_THRESHOLD = 0.3

DETECTOR_INPUT = (640, 640)
DETECTOR_PERSON_SCORE = 0.3
DETECTOR_NMS = 0.45
DETECTOR_SCORE_FLOOR = 0.1
POSE_INPUT = (288, 384)  # width, height
POSE_BOX_PADDING = 1.25
SIMCC_SPLIT_RATIO = 2.0
POSE_MEAN = (123.675, 116.28, 103.53)
POSE_STD = (58.395, 57.12, 57.375)

CONFIG: dict[str, Any] = {
    "detector": {
        "file": "yolox_l.onnx",
        "input": list(DETECTOR_INPUT),
        "person_score": DETECTOR_PERSON_SCORE,
        "nms": DETECTOR_NMS,
        "class_agnostic_nms": True,
    },
    "estimator": {
        "file": "dw-ll_ucoco_384.onnx",
        "input": list(POSE_INPUT),
        "box_padding": POSE_BOX_PADDING,
        "simcc_split_ratio": SIMCC_SPLIT_RATIO,
        "channel_order": "bgr_as_reference",
    },
    "runtime": "onnxruntime_cpu",
    "keypoint_score_threshold": SCORE_THRESHOLD,
    "max_people": MAX_PEOPLE,
    "min_body_points": MIN_BODY_POINTS,
    "layout": "coco_wholebody_133_to_openpose_18_hand_21_face_68",
    "render": "openpose_skeleton_black_background",
}

#: OpenPose-18 body order built from COCO-WholeBody indices; 17 stands for the neck derived from the two shoulders.
_OPENPOSE_FROM_COCO = (0, 17, 6, 8, 10, 5, 7, 9, 12, 14, 16, 11, 13, 15, 2, 1, 4, 3)
_LIMBS = (
    (1, 2), (1, 5), (2, 3), (3, 4), (5, 6), (6, 7), (1, 8), (8, 9), (9, 10), (1, 11),
    (11, 12), (12, 13), (1, 0), (0, 14), (14, 16), (0, 15), (15, 17),
)  # fmt: skip
_COLORS = (
    (255, 0, 0), (255, 85, 0), (255, 170, 0), (255, 255, 0), (170, 255, 0), (85, 255, 0),
    (0, 255, 0), (0, 255, 85), (0, 255, 170), (0, 255, 255), (0, 170, 255), (0, 85, 255),
    (0, 0, 255), (85, 0, 255), (170, 0, 255), (255, 0, 255), (255, 0, 170), (255, 0, 85),
)  # fmt: skip
_HAND_EDGES = (
    (0, 1), (1, 2), (2, 3), (3, 4), (0, 5), (5, 6), (6, 7), (7, 8), (0, 9), (9, 10),
    (10, 11), (11, 12), (0, 13), (13, 14), (14, 15), (15, 16), (0, 17), (17, 18), (18, 19), (19, 20),
)  # fmt: skip
_FACE = slice(23, 91)
_LEFT_HAND = slice(91, 112)
_RIGHT_HAND = slice(112, 133)
_STICK = 4.0
_BODY_RADIUS = 4.0
_HAND_RADIUS = 4.0
_FACE_RADIUS = 3.0
_HAND_WIDTH = 2.0
_LIMB_DIMMING = 0.6


def identity() -> MethodIdentity:
    return MethodIdentity(METHOD_ID, METHOD_VERSION, dict(CONFIG))


@dataclass(frozen=True, slots=True)
class PosePerson:
    """One detected person: 133 keypoints in source pixels with their confidences."""

    points: np.ndarray  # (133, 2) float
    scores: np.ndarray  # (133,) float
    detection_score: float = 1.0


# --------------------------------------------------------------------------------------------- detector decoding


def yolox_decode(raw: np.ndarray, input_size: tuple[int, int] = DETECTOR_INPUT) -> np.ndarray:
    """Add the grid offsets and strides to the raw YOLOX head output (rows ``cx, cy, w, h, objectness, classes...``)."""

    out = np.array(raw, dtype=np.float32)
    out = out.reshape(-1, out.shape[-1])
    grids, strides = [], []
    for stride in (8, 16, 32):
        rows, cols = input_size[0] // stride, input_size[1] // stride
        xv, yv = np.meshgrid(np.arange(cols), np.arange(rows))
        grid = np.stack((xv, yv), axis=2).reshape(-1, 2)
        grids.append(grid)
        strides.append(np.full((grid.shape[0], 1), stride))
    grid_all = np.concatenate(grids, axis=0).astype(np.float32)
    stride_all = np.concatenate(strides, axis=0).astype(np.float32)
    if out.shape[0] != grid_all.shape[0] or out.shape[1] < 6:
        raise ReferenceMapError(CODE_INFERENCE, "The person detector returned an unexpected shape.")
    out[:, :2] = (out[:, :2] + grid_all) * stride_all
    out[:, 2:4] = np.exp(np.clip(out[:, 2:4], -20.0, 20.0)) * stride_all
    return out


def nms(boxes: np.ndarray, scores: np.ndarray, threshold: float) -> list[int]:
    """Greedy non-maximum suppression over ``xyxy`` boxes; ties keep the lower index."""

    order = np.argsort(-scores, kind="stable")
    keep: list[int] = []
    areas = np.maximum(boxes[:, 2] - boxes[:, 0], 0) * np.maximum(boxes[:, 3] - boxes[:, 1], 0)
    while order.size:
        best = int(order[0])
        keep.append(best)
        rest = order[1:]
        if not rest.size:
            break
        x0 = np.maximum(boxes[best, 0], boxes[rest, 0])
        y0 = np.maximum(boxes[best, 1], boxes[rest, 1])
        x1 = np.minimum(boxes[best, 2], boxes[rest, 2])
        y1 = np.minimum(boxes[best, 3], boxes[rest, 3])
        inter = np.maximum(x1 - x0, 0) * np.maximum(y1 - y0, 0)
        union = areas[best] + areas[rest] - inter
        overlap = np.divide(inter, union, out=np.zeros_like(inter), where=union > 0)
        order = rest[overlap <= threshold]
    return keep


def person_boxes(decoded: np.ndarray, ratio: float) -> list[tuple[np.ndarray, float]]:
    """``(xyxy box in source pixels, score)`` of each confident person, strongest first."""

    if ratio <= 0 or not math.isfinite(ratio):
        raise ReferenceMapError(CODE_INFERENCE, "Invalid detector scale.")
    class_scores = decoded[:, 4:5] * decoded[:, 5:]
    centre, size = decoded[:, :2], decoded[:, 2:4]
    boxes = np.concatenate((centre - size / 2.0, centre + size / 2.0), axis=1) / ratio
    labels = class_scores.argmax(axis=1)
    best = class_scores[np.arange(class_scores.shape[0]), labels]
    candidate = np.flatnonzero(best > DETECTOR_SCORE_FLOOR)
    if not candidate.size:
        return []
    kept = [int(candidate[i]) for i in nms(boxes[candidate], best[candidate], DETECTOR_NMS)]
    people = [i for i in kept if labels[i] == 0 and best[i] > DETECTOR_PERSON_SCORE]
    return [(boxes[i].astype(np.float32), float(best[i])) for i in people]


# ----------------------------------------------------------------------------------------- estimator decoding


def box_center_scale(box: Sequence[float]) -> tuple[np.ndarray, np.ndarray]:
    """Padded crop centre and ``(width, height)`` with the estimator's aspect ratio applied."""

    x0, y0, x1, y1 = (float(v) for v in box)
    center = np.array([(x0 + x1) / 2.0, (y0 + y1) / 2.0], dtype=np.float32)
    width, height = (x1 - x0) * POSE_BOX_PADDING, (y1 - y0) * POSE_BOX_PADDING
    aspect = POSE_INPUT[0] / POSE_INPUT[1]
    if width > height * aspect:
        height = width / aspect
    else:
        width = height * aspect
    return center, np.array([width, height], dtype=np.float32)


def warp_matrix(center: np.ndarray, scale: np.ndarray) -> np.ndarray:
    """The 2x3 affine mapping the padded box in the source onto the estimator input (no rotation)."""

    sx, sy = POSE_INPUT[0] / float(scale[0]), POSE_INPUT[1] / float(scale[1])
    return np.array(
        [
            [sx, 0.0, -(float(center[0]) - float(scale[0]) / 2.0) * sx],
            [0.0, sy, -(float(center[1]) - float(scale[1]) / 2.0) * sy],
        ],
        dtype=np.float32,
    )


def simcc_keypoints(
    simcc_x: np.ndarray, simcc_y: np.ndarray, center: np.ndarray, scale: np.ndarray
) -> tuple[np.ndarray, np.ndarray]:
    """Decode one person's SimCC vectors into source-pixel keypoints and confidences."""

    if simcc_x.ndim != 2 or simcc_y.ndim != 2 or simcc_x.shape[0] != simcc_y.shape[0]:
        raise ReferenceMapError(CODE_INFERENCE, "The pose estimator returned an unexpected shape.")
    max_x, max_y = simcc_x.max(axis=1), simcc_y.max(axis=1)
    locs = np.stack((simcc_x.argmax(axis=1), simcc_y.argmax(axis=1)), axis=1).astype(np.float32)
    scores = np.minimum(max_x, max_y).astype(np.float32)
    locs[scores <= 0.0] = -1.0
    keypoints = locs / SIMCC_SPLIT_RATIO
    keypoints = keypoints / np.array(POSE_INPUT, dtype=np.float32) * scale + center - scale / 2.0
    return keypoints.astype(np.float32), scores


# ------------------------------------------------------------------------------------------------- transport


def people_to_payload(people: Sequence[PosePerson], width: int, height: int) -> dict[str, Any]:
    return {
        "width": int(width),
        "height": int(height),
        "people": [
            {
                "detection_score": round(float(p.detection_score), 4),
                "points": np.round(p.points, 2).tolist(),
                "scores": np.round(p.scores, 4).tolist(),
            }
            for p in people
        ],
    }


def people_from_payload(payload: Any) -> tuple[PosePerson, ...]:
    """Validate the worker's (untrusted) keypoint document; anything off-contract is an inference failure."""

    if not isinstance(payload, Mapping) or not isinstance(payload.get("people"), list):
        raise ReferenceMapError(CODE_INFERENCE, "The pose worker returned an invalid result.")
    raw_people = payload["people"]
    if len(raw_people) > MAX_PEOPLE * 4:
        raise ReferenceMapError(CODE_INFERENCE, "The pose worker returned too many people.")
    people = []
    for item in raw_people:
        try:
            points = np.asarray(item["points"], dtype=np.float64)
            scores = np.asarray(item["scores"], dtype=np.float64)
            detection = float(item.get("detection_score", 1.0))
        except (KeyError, TypeError, ValueError, AttributeError) as exc:
            raise ReferenceMapError(
                CODE_INFERENCE, "The pose worker returned an invalid person."
            ) from exc
        if points.shape != (KEYPOINTS, 2) or scores.shape != (KEYPOINTS,):
            raise ReferenceMapError(CODE_INFERENCE, "The pose worker returned an invalid person.")
        people.append(PosePerson(points, scores, detection if math.isfinite(detection) else 0.0))
    people.sort(key=lambda person: -person.detection_score)
    return tuple(people)


# -------------------------------------------------------------------------------------------------- rendering


def _visible(points: np.ndarray, scores: np.ndarray, width: int, height: int) -> np.ndarray:
    with np.errstate(invalid="ignore"):
        inside = (
            np.isfinite(points).all(axis=1)
            & np.isfinite(scores)
            & (scores > SCORE_THRESHOLD)
            & (points[:, 0] >= 0)
            & (points[:, 0] < width)
            & (points[:, 1] >= 0)
            & (points[:, 1] < height)
        )
    return inside


def _body18(person: PosePerson, width: int, height: int) -> tuple[np.ndarray, np.ndarray]:
    visible = _visible(person.points, person.scores, width, height)
    points = np.vstack([person.points[:17], (person.points[5] + person.points[6]) / 2.0])
    shown = np.concatenate([visible[:17], [bool(visible[5] and visible[6])]])
    order = list(_OPENPOSE_FROM_COCO)
    return points[order], shown[order]


def _ellipse(
    center: tuple[float, float], half_length: float, half_width: float, angle: float
) -> list[tuple[float, float]]:
    steps = np.linspace(0.0, 2.0 * math.pi, 72, endpoint=False)
    cos_a, sin_a = math.cos(angle), math.sin(angle)
    x = half_length * np.cos(steps)
    y = half_width * np.sin(steps)
    return [
        (float(center[0] + px * cos_a - py * sin_a), float(center[1] + px * sin_a + py * cos_a))
        for px, py in zip(x, y, strict=True)
    ]


def _dot(draw: Any, point: Any, radius: float, color: tuple[int, int, int]) -> None:
    x, y = float(point[0]), float(point[1])
    draw.ellipse([x - radius, y - radius, x + radius, y + radius], fill=color)


def render_pose(
    people: Sequence[PosePerson], width: int, height: int
) -> tuple[np.ndarray, tuple[str, ...]]:
    """The OpenPose skeleton image for the people with enough confident body keypoints, plus disclosed warnings.

    Raises ``ReferenceMapError(no_people)`` when nobody qualifies: an empty skeleton is never returned as a success.
    """

    from PIL import Image, ImageDraw

    usable = []
    for person in people:
        body, shown = _body18(person, width, height)
        if int(shown.sum()) >= MIN_BODY_POINTS:
            usable.append((person, body, shown))
    if not usable:
        raise ReferenceMapError(
            CODE_NO_PEOPLE,
            "No person was detected, so no map was created. Use an image where a person is clearly visible.",
        )
    warnings: list[str] = []
    if len(usable) > MAX_PEOPLE:
        usable = usable[:MAX_PEOPLE]
        warnings.append("pose_people_truncated")
    unit = max(1.0, max(width, height) / 1024.0)
    limbs = Image.new("RGB", (width, height), (0, 0, 0))
    draw = ImageDraw.Draw(limbs)
    for _person, body, shown in usable:
        for index, (a, b) in enumerate(_LIMBS):
            if not (shown[a] and shown[b]):
                continue
            (x0, y0), (x1, y1) = body[a], body[b]
            length = math.hypot(x1 - x0, y1 - y0)
            polygon = _ellipse(
                ((x0 + x1) / 2.0, (y0 + y1) / 2.0),
                length / 2.0,
                _STICK * unit,
                math.atan2(y1 - y0, x1 - x0),
            )
            draw.polygon(polygon, fill=_COLORS[index])
    canvas = Image.fromarray((np.asarray(limbs, dtype=np.float32) * _LIMB_DIMMING).astype(np.uint8))
    draw = ImageDraw.Draw(canvas)
    any_hand = any_face = partial = False
    for person, body, shown in usable:
        for index in range(18):
            if shown[index]:
                _dot(draw, body[index], _BODY_RADIUS * unit, _COLORS[index])
        partial = partial or int(shown.sum()) < 10
        visible = _visible(person.points, person.scores, width, height)
        for part in (_LEFT_HAND, _RIGHT_HAND):
            points, ok = person.points[part], visible[part]
            any_hand = any_hand or bool(ok.any())
            for edge_index, (a, b) in enumerate(_HAND_EDGES):
                if ok[a] and ok[b]:
                    red, green, blue = colorsys.hsv_to_rgb(edge_index / len(_HAND_EDGES), 1.0, 1.0)
                    draw.line(
                        [tuple(points[a]), tuple(points[b])],
                        fill=(round(red * 255), round(green * 255), round(blue * 255)),
                        width=max(1, round(_HAND_WIDTH * unit)),
                    )
            for k in np.flatnonzero(ok):
                _dot(draw, points[k], _HAND_RADIUS * unit, (0, 0, 255))
        face_ok = visible[_FACE]
        any_face = any_face or bool(face_ok.any())
        for k in np.flatnonzero(face_ok):
            _dot(draw, person.points[_FACE][k], _FACE_RADIUS * unit, (255, 255, 255))
    if not any_hand:
        warnings.append("pose_no_hands")
    if not any_face:
        warnings.append("pose_no_face")
    if partial:
        warnings.append("pose_partial_body")
    return np.ascontiguousarray(np.asarray(canvas, dtype=np.uint8)), tuple(warnings)


__all__ = [
    "CONFIG",
    "KEYPOINTS",
    "MAX_PEOPLE",
    "METHOD_ID",
    "METHOD_VERSION",
    "POSE_INPUT",
    "PosePerson",
    "box_center_scale",
    "identity",
    "nms",
    "people_from_payload",
    "people_to_payload",
    "person_boxes",
    "render_pose",
    "simcc_keypoints",
    "warp_matrix",
    "yolox_decode",
]
