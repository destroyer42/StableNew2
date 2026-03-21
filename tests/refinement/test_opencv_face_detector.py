from __future__ import annotations

from pathlib import Path

import pytest


cv2 = pytest.importorskip("cv2")
np = pytest.importorskip("numpy")

from src.refinement.detectors.opencv_face_detector import OpenCvFaceDetector


class _CascadeStub:
    def __init__(self, responses):
        self._responses = list(responses)
        self._index = 0

    def detectMultiScale(self, *_args, **_kwargs):
        if self._index >= len(self._responses):
            return []
        response = self._responses[self._index]
        self._index += 1
        return response


def test_opencv_face_detector_dedupes_overlapping_detections(monkeypatch, tmp_path: Path) -> None:
    image_path = tmp_path / "subject.png"
    image_path.write_bytes(b"png")
    detector = OpenCvFaceDetector()

    monkeypatch.setattr(detector._cv2, "imread", lambda _path: np.zeros((100, 100, 3), dtype=np.uint8))
    monkeypatch.setattr(detector._cv2, "cvtColor", lambda image, _code: np.zeros((100, 100), dtype=np.uint8))
    monkeypatch.setattr(detector._cv2, "flip", lambda image, _flip_code: image)
    detector._frontal = _CascadeStub([[(10, 10, 30, 30)]])
    detector._profile = _CascadeStub([[(12, 12, 30, 30)], []])

    detections = detector.detect_faces(image_path)

    assert len(detections) == 1
    assert detections[0]["source"] == "frontal"


def test_opencv_face_detector_maps_flipped_profile_coordinates(monkeypatch, tmp_path: Path) -> None:
    image_path = tmp_path / "profile.png"
    image_path.write_bytes(b"png")
    detector = OpenCvFaceDetector()

    monkeypatch.setattr(detector._cv2, "imread", lambda _path: np.zeros((80, 100, 3), dtype=np.uint8))
    monkeypatch.setattr(detector._cv2, "cvtColor", lambda image, _code: np.zeros((80, 100), dtype=np.uint8))
    monkeypatch.setattr(detector._cv2, "flip", lambda image, _flip_code: image)
    detector._frontal = _CascadeStub([[]])
    detector._profile = _CascadeStub([[], [(10, 5, 20, 20)]])

    detections = detector.detect_faces(image_path)

    assert len(detections) == 1
    assert detections[0]["source"] == "profile_flipped"
    assert detections[0]["x"] == 70
    assert detections[0]["y"] == 5
    assert detections[0]["w"] == 20
    assert detections[0]["h"] == 20
