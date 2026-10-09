"""Offline CPU qualification using an explicitly supplied photograph; no generation."""

from __future__ import annotations

import argparse
import hashlib
import importlib.metadata
import json
import sys
import tempfile
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[3]))

from src.refinement.detectors.opencv_face_detector import (  # noqa: E402
    MODEL_SHA256,
    OpenCvFaceDetector,
)
from src.refinement.quality_metrics import compute_image_sharpness_variance  # noqa: E402
from src.refinement.subject_scale_policy_service import SubjectScalePolicyService  # noqa: E402


def main() -> None:
    import cv2
    import numpy as np

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("photo", type=Path)
    parser.add_argument("--report", type=Path, required=True)
    args = parser.parse_args()
    owners = {
        item.metadata["Name"]: item.version
        for item in importlib.metadata.distributions()
        if item.metadata["Name"].lower().startswith("opencv-")
    }
    assert owners == {"opencv-python": "5.0.0.93"}, owners
    assert np.__version__ == "2.5.3"
    image = cv2.imread(str(args.photo))
    assert image is not None
    detector = OpenCvFaceDetector()
    results = []
    with tempfile.TemporaryDirectory(prefix="refine150-cpu-") as directory:
        root = Path(directory)
        height, width = image.shape[:2]
        variants = {
            "original": image,
            "mirrored": cv2.flip(image, 1),
            "large": cv2.resize(image, (width * 3, height * 3)),
        }
        for angle in (-25, 25):
            matrix = cv2.getRotationMatrix2D((width / 2, height / 2), angle, 1)
            variants[f"angled_{angle}"] = cv2.warpAffine(image, matrix, (width, height))
        for name, frame in variants.items():
            path = root / f"{name}.png"
            assert cv2.imwrite(str(path), frame)
            start = time.perf_counter()
            detections = detector.detect_faces(path)
            elapsed = time.perf_counter() - start
            assert detections, (name, "no plausible face detected")
            assert detector.detect_faces(path) == detections
            h, w = frame.shape[:2]
            for row in detections:
                assert 0 <= row["x"] < row["x"] + row["w"] <= w
                assert 0 <= row["y"] < row["y"] + row["h"] <= h
                assert 0.6 <= row["confidence"] <= 1
            # This qualification photo is the NASA astronaut: known broad facial region.
            row = detections[0]
            assert 0.02 < row["w"] * row["h"] / (w * h) < 0.2
            assessment = SubjectScalePolicyService(detector=detector).assess(path)
            assert assessment["detection_status"] == "available"
            assert assessment["detector_id"] == "opencv_yunet"
            sharpness = compute_image_sharpness_variance(path)
            assert sharpness is not None and sharpness > 0
            results.append(
                {"name": name, "seconds": elapsed, "detections": detections, "sharpness": sharpness}
            )
        # Encoding/decoding a deterministic fixture is not physical generation.
        video_path = root / "fixture.avi"
        writer = cv2.VideoWriter(str(video_path), cv2.VideoWriter.fourcc(*"MJPG"), 6, (64, 48))
        assert writer.isOpened(), "video encoder unavailable"
        try:
            for index in range(12):
                writer.write(np.full((48, 64, 3), index * 15, dtype=np.uint8))
        finally:
            writer.release()
        reader = cv2.VideoCapture(str(video_path))
        frames = []
        try:
            while True:
                ok, frame = reader.read()
                if not ok:
                    break
                assert frame.shape == (48, 64, 3)
                frames.append(float(frame.mean()))
        finally:
            reader.release()
        assert len(frames) == 12 and all(
            a < b for a, b in zip(frames[:-1], frames[1:], strict=True)
        )
        blank = root / "blank.png"
        assert cv2.imwrite(str(blank), np.zeros((80, 100, 3), dtype=np.uint8))
        assert detector.detect_faces(blank) == ()
    args.report.write_text(
        json.dumps(
            {
                "python": sys.version,
                "packages": owners,
                "numpy": np.__version__,
                "model_sha256": MODEL_SHA256,
                "photo_sha256": hashlib.sha256(args.photo.read_bytes()).hexdigest(),
                "variants": results,
                "decoded_frames": len(frames),
                "video_geometry": [64, 48],
                "blank_faces": 0,
            },
            indent=2,
        ),
        encoding="utf-8",
    )


if __name__ == "__main__":
    main()
