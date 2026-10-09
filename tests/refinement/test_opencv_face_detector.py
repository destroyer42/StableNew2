from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import pytest

from src.refinement.detectors import opencv_face_detector as module


def _row(x, y, w, h, score=0.9):
    return [x, y, w, h, *([0] * 10), score]


@pytest.fixture
def fake_cv(monkeypatch):
    model = SimpleNamespace(
        setInputSize=lambda size: sizes.append(size), detect=lambda image: (1, rows)
    )
    rows, sizes, creations = [], [], []

    def create(*args, **kwargs):
        creations.append((args, kwargs))
        return model

    cv = SimpleNamespace(
        FaceDetectorYN=SimpleNamespace(create=create),
        dnn=SimpleNamespace(DNN_BACKEND_OPENCV=3, DNN_TARGET_CPU=0),
        imread=lambda path, flags: SimpleNamespace(shape=(80, 100, 3)),
        IMREAD_COLOR=1,
        IMREAD_IGNORE_ORIENTATION=128,
        resize=lambda image, size: SimpleNamespace(shape=(size[1], size[0], 3)),
    )
    monkeypatch.setattr(module, "cv2", cv)
    return cv, model, rows, sizes, creations


def test_opencv_face_detector_dedupes_overlapping_yunet_detections(fake_cv):
    _, _, rows, _, _ = fake_cv
    rows.extend([_row(10, 10, 30, 30), _row(12, 12, 30, 30, 0.8)])
    detector = module.OpenCvFaceDetector()
    detections = detector.detect_faces(Path("subject.png"))
    assert len(detections) == 1
    assert detections[0]["source"] == "yunet"
    assert detections[0]["confidence"] == 0.9


def test_opencv_face_detector_maps_resized_image_coordinates(fake_cv):
    cv, _, rows, sizes, _ = fake_cv
    cv.imread = lambda path, flags: SimpleNamespace(shape=(160, 200, 3))
    rows.append(_row(10, 5, 20, 20))
    detector = module.OpenCvFaceDetector(max_input_edge=100)
    detection = detector.detect_faces(Path("angled.png"))[0]
    assert sizes == [(100, 80)]
    assert tuple(detection[key] for key in ("x", "y", "w", "h")) == (20, 10, 40, 40)


def test_threshold_clipping_empty_and_deterministic_order(fake_cv):
    _, model, rows, sizes, creations = fake_cv
    rows.extend(
        [
            _row(80, 60, 40, 40),
            _row(-5, -5, 15, 15),
            _row(40, 20, 10, 10),
            _row(20, 20, 10, 10),
            _row(0, 0, 90, 70, 0.59),
            _row(101, 5, 20, 20),
            _row(10, 10, -5, 10),
            _row(0, 0, 5, 5, float("nan")),
        ]
    )
    detector = module.OpenCvFaceDetector()
    detections = detector.detect_faces(Path("faces.png"))
    assert [item["x"] for item in detections] == [80, 0, 20, 40]
    assert (detections[0]["w"], detections[0]["h"]) == (20, 20)
    assert sizes == [(100, 80)]
    assert creations[0][1]["target_id"] == 0
    assert detector.detector_id == "opencv_yunet"
    assert detector.algorithm_version == "yunet_2026may/1"
    assert detector.detect_faces(Path("faces.png")) == detections
    model.detect = lambda image: (1, None)
    assert detector.detect_faces(Path("empty.png")) == ()


@pytest.mark.parametrize("failure", ["missing", "corrupt", "oversized"])
def test_model_asset_fails_closed_before_native_load(fake_cv, tmp_path, failure):
    path = tmp_path / "model.onnx"
    if failure == "corrupt":
        path.write_bytes(b"x" * 229738)
    elif failure == "oversized":
        path.write_bytes(b"x" * 229739)
    with pytest.raises(RuntimeError, match="YuNet model.*restore.*repository"):
        module.OpenCvFaceDetector(model_path=path)
    assert not fake_cv[4]


@pytest.mark.parametrize("failure", ["decode", "inference", "malformed", "missing_input"])
def test_detection_failure_is_not_an_empty_face_result(fake_cv, failure):
    cv, model, rows, _, _ = fake_cv
    detector = module.OpenCvFaceDetector()
    if failure == "decode":
        cv.imread = lambda path, flags: None
    elif failure == "inference":

        def fail(image):
            raise ValueError("native failure")

        model.detect = fail
    elif failure == "malformed":
        rows.append([1, 2])
    with pytest.raises(RuntimeError, match="YuNet"):
        detector.detect_faces(None if failure == "missing_input" else Path("input.png"))


def test_unavailable_api_and_initialization_are_actionable(fake_cv, monkeypatch):
    cv = fake_cv[0]
    cv.FaceDetectorYN.create = lambda *a, **k: (_ for _ in ()).throw(ValueError("bad model"))
    with pytest.raises(RuntimeError, match="YuNet.*initialization"):
        module.OpenCvFaceDetector()
    monkeypatch.setattr(module, "cv2", None)
    with pytest.raises(RuntimeError, match="opencv-python.*FaceDetectorYN"):
        module.OpenCvFaceDetector()


@pytest.mark.parametrize("threshold", [-0.1, 1.1, float("nan")])
def test_invalid_confidence_configuration_rejected(fake_cv, threshold):
    with pytest.raises(ValueError):
        module.OpenCvFaceDetector(score_threshold=threshold)


def test_packaged_asset_identity():
    import hashlib

    data = module.MODEL_PATH.read_bytes()
    assert len(data) == module.MODEL_SIZE
    assert hashlib.sha256(data).hexdigest() == module.MODEL_SHA256
    assert "MIT License" in (module.MODEL_PATH.parent / "LICENSE.YuNet").read_text()


def test_real_cpu_blank_image_has_no_detections(tmp_path):
    cv = pytest.importorskip("cv2")
    np = pytest.importorskip("numpy")
    path = tmp_path / "blank.png"
    assert cv.imwrite(str(path), np.zeros((80, 100, 3), dtype=np.uint8))
    assert module.OpenCvFaceDetector().detect_faces(path) == ()


def test_input_keeps_raw_raster_orientation(fake_cv):
    cv, _, rows, sizes, _ = fake_cv
    reads = []

    def read(path, flags):
        reads.append(flags)
        return SimpleNamespace(shape=(80, 100, 3))

    cv.imread = read
    rows.append(_row(70, 5, 20, 20))
    detection = module.OpenCvFaceDetector().detect_faces(Path("exif.jpg"))[0]
    assert reads == [129]
    assert sizes == [(100, 80)]
    assert detection["x"] == 70
