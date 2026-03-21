from __future__ import annotations

from pathlib import Path
from typing import Any

try:  # pragma: no cover - import availability is environment-dependent
    import cv2
except Exception:  # pragma: no cover
    cv2 = None  # type: ignore[assignment]

from .base_detector import SubjectDetector


def _iou(box_a: tuple[int, int, int, int], box_b: tuple[int, int, int, int]) -> float:
    ax1, ay1, aw, ah = box_a
    bx1, by1, bw, bh = box_b
    ax2, ay2 = ax1 + aw, ay1 + ah
    bx2, by2 = bx1 + bw, by1 + bh

    inter_x1 = max(ax1, bx1)
    inter_y1 = max(ay1, by1)
    inter_x2 = min(ax2, bx2)
    inter_y2 = min(ay2, by2)
    if inter_x2 <= inter_x1 or inter_y2 <= inter_y1:
        return 0.0
    inter = (inter_x2 - inter_x1) * (inter_y2 - inter_y1)
    union = aw * ah + bw * bh - inter
    return float(inter) / float(union) if union > 0 else 0.0


class OpenCvFaceDetector(SubjectDetector):
    detector_id = "opencv"

    def __init__(self) -> None:
        if cv2 is None:  # pragma: no cover - exercised in runner fallback tests
            raise RuntimeError("OpenCV detector requested but cv2 is unavailable")
        frontal_path = str(Path(cv2.data.haarcascades) / "haarcascade_frontalface_default.xml")
        profile_path = str(Path(cv2.data.haarcascades) / "haarcascade_profileface.xml")
        self._cv2 = cv2
        self._frontal = cv2.CascadeClassifier(frontal_path)
        self._profile = cv2.CascadeClassifier(profile_path)

    def _dedupe(self, detections: list[dict[str, Any]], iou_threshold: float = 0.35) -> tuple[dict[str, Any], ...]:
        ordered = sorted(detections, key=lambda item: item["w"] * item["h"], reverse=True)
        kept: list[dict[str, Any]] = []
        for candidate in ordered:
            box = (candidate["x"], candidate["y"], candidate["w"], candidate["h"])
            if any(
                _iou(box, (item["x"], item["y"], item["w"], item["h"])) >= iou_threshold
                for item in kept
            ):
                continue
            kept.append(candidate)
        return tuple(kept)

    def detect_faces(self, image_path: Path | None) -> tuple[dict[str, Any], ...]:
        if image_path is None:
            return ()
        image = self._cv2.imread(str(image_path))
        if image is None:
            return ()
        gray = self._cv2.cvtColor(image, self._cv2.COLOR_BGR2GRAY)
        flipped_gray = self._cv2.flip(gray, 1)

        detections: list[dict[str, Any]] = []

        for (x, y, w, h) in self._frontal.detectMultiScale(gray, scaleFactor=1.1, minNeighbors=5):
            detections.append(
                {
                    "x": int(x),
                    "y": int(y),
                    "w": int(w),
                    "h": int(h),
                    "confidence": 1.0,
                    "source": "frontal",
                }
            )
        for (x, y, w, h) in self._profile.detectMultiScale(gray, scaleFactor=1.1, minNeighbors=4):
            detections.append(
                {
                    "x": int(x),
                    "y": int(y),
                    "w": int(w),
                    "h": int(h),
                    "confidence": 1.0,
                    "source": "profile",
                }
            )
        width = gray.shape[1]
        for (x, y, w, h) in self._profile.detectMultiScale(flipped_gray, scaleFactor=1.1, minNeighbors=4):
            detections.append(
                {
                    "x": int(width - x - w),
                    "y": int(y),
                    "w": int(w),
                    "h": int(h),
                    "confidence": 1.0,
                    "source": "profile_flipped",
                }
            )

        return self._dedupe(detections)
