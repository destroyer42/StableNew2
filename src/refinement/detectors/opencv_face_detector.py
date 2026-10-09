from __future__ import annotations

import hashlib
import math
from pathlib import Path
from typing import Any

try:  # pragma: no cover - optional capability
    import cv2
except Exception:  # pragma: no cover
    cv2 = None  # type: ignore[assignment]

from .base_detector import SubjectDetector

MODEL_NAME = "face_detection_yunet_2026may.onnx"
MODEL_SHA256 = "ebafce4e3c118d6554634be5c27ab333b4c047a9a8c3faf1d7cf93101c22f0f0"
MODEL_SIZE = 229738
MODEL_PATH = Path(__file__).resolve().parents[1] / "assets" / MODEL_NAME


def _iou(box_a: tuple[int, int, int, int], box_b: tuple[int, int, int, int]) -> float:
    ax, ay, aw, ah = box_a
    bx, by, bw, bh = box_b
    intersection = max(0, min(ax + aw, bx + bw) - max(ax, bx)) * max(
        0, min(ay + ah, by + bh) - max(ay, by)
    )
    union = aw * ah + bw * bh - intersection
    return intersection / union if union > 0 else 0.0


class OpenCvFaceDetector(SubjectDetector):
    """Offline, CPU YuNet projection into original-image subject boxes."""

    detector_id = "opencv_yunet"
    algorithm_version = "yunet_2026may/1"
    model_sha256 = MODEL_SHA256

    def __init__(
        self,
        *,
        model_path: Path = MODEL_PATH,
        score_threshold: float = 0.6,
        max_input_edge: int = 1280,
    ) -> None:
        if not math.isfinite(score_threshold) or not 0 <= score_threshold <= 1:
            raise ValueError("YuNet score threshold must be finite and between zero and one")
        if not isinstance(max_input_edge, int) or max_input_edge <= 0:
            raise ValueError("YuNet maximum input edge must be a positive integer")
        if cv2 is None or not hasattr(cv2, "FaceDetectorYN"):
            raise RuntimeError(
                "YuNet requires pinned opencv-python with FaceDetectorYN; check runtime readiness"
            )
        try:
            # Bound the read before hashing; only the exact qualified bytes may reach native DNN.
            with model_path.open("rb") as stream:
                data = stream.read(MODEL_SIZE + 1)
            if len(data) != MODEL_SIZE or hashlib.sha256(data).hexdigest() != MODEL_SHA256:
                raise ValueError("model identity mismatch")
        except (OSError, ValueError) as exc:
            raise RuntimeError(
                "YuNet model unavailable or corrupt; restore the verified repository model asset"
            ) from exc
        self._cv2 = cv2
        self._score_threshold = score_threshold
        self._max_input_edge = max_input_edge
        try:
            self._model = cv2.FaceDetectorYN.create(
                model=str(model_path),
                config="",
                input_size=(320, 320),
                score_threshold=score_threshold,
                nms_threshold=0.3,
                top_k=5000,
                backend_id=cv2.dnn.DNN_BACKEND_OPENCV,
                target_id=cv2.dnn.DNN_TARGET_CPU,
            )
            if self._model is None:
                raise ValueError("empty detector")
        except Exception as exc:
            raise RuntimeError(
                "YuNet CPU initialization failed; verify pinned OpenCV and repository model"
            ) from exc

    def _dedupe(self, detections: list[dict[str, Any]]) -> tuple[dict[str, Any], ...]:
        ordered = sorted(
            detections,
            key=lambda item: (
                -item["w"] * item["h"],
                -item["confidence"],
                item["x"],
                item["y"],
                item["w"],
                item["h"],
            ),
        )
        kept: list[dict[str, Any]] = []
        for candidate in ordered:
            box = (candidate["x"], candidate["y"], candidate["w"], candidate["h"])
            if not any(
                _iou(box, (item["x"], item["y"], item["w"], item["h"])) >= 0.35 for item in kept
            ):
                kept.append(candidate)
        return tuple(kept)

    def detect_faces(self, image_path: Path | None) -> tuple[dict[str, Any], ...]:
        if image_path is None:
            raise RuntimeError("YuNet requires a readable input image")
        try:
            # Match Pillow's raw raster dimensions used by subject-scale assessment.
            image = self._cv2.imread(
                str(image_path), self._cv2.IMREAD_COLOR | self._cv2.IMREAD_IGNORE_ORIENTATION
            )
            if image is None or len(image.shape) != 3 or image.shape[2] != 3:
                raise ValueError("image cannot be decoded as BGR")
            height, width = image.shape[:2]
            if height <= 0 or width <= 0:
                raise ValueError("empty image")
            scale = min(1.0, self._max_input_edge / max(width, height))
            input_width, input_height = max(1, round(width * scale)), max(1, round(height * scale))
            if (input_width, input_height) != (width, height):
                image = self._cv2.resize(image, (input_width, input_height))
            self._model.setInputSize((input_width, input_height))
            _, faces = self._model.detect(image)
            if faces is None:
                return ()
            if len(faces) > 5000:
                raise ValueError("unexpected detection count")
            detections: list[dict[str, Any]] = []
            for row in faces:
                if len(row) != 15:
                    raise ValueError("malformed YuNet output")
                x, y, w, h, confidence = (float(row[index]) for index in (0, 1, 2, 3, 14))
                # Nonempty output with unusable geometry/score is not evidence of absence.
                if (
                    not all(math.isfinite(value) for value in (x, y, w, h, confidence))
                    or w <= 0
                    or h <= 0
                    or not 0 <= confidence <= 1
                ):
                    raise ValueError("malformed YuNet detection row")
                if confidence < self._score_threshold:
                    continue  # Valid detection below the declared threshold.
                # YuNet coordinates are in its input frame; use actual rounded resize dimensions.
                left = max(0, min(width, math.floor(x * width / input_width)))
                top = max(0, min(height, math.floor(y * height / input_height)))
                right = max(0, min(width, math.ceil((x + w) * width / input_width)))
                bottom = max(0, min(height, math.ceil((y + h) * height / input_height)))
                if right <= left or bottom <= top:
                    raise ValueError("YuNet detection outside the input image")
                detections.append(
                    {
                        "x": left,
                        "y": top,
                        "w": right - left,
                        "h": bottom - top,
                        "confidence": confidence,
                        "source": "yunet",
                    }
                )
            return self._dedupe(detections)
        except Exception as exc:
            raise RuntimeError(
                "YuNet inference failed; verify input image, pinned OpenCV and repository model"
            ) from exc
