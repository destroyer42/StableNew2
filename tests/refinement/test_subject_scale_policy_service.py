from __future__ import annotations

from pathlib import Path

import pytest
from PIL import Image

from src.refinement.detectors.base_detector import SubjectDetector
from src.refinement.subject_scale_policy_service import (
    SubjectScalePolicyConfig,
    SubjectScalePolicyService,
)


def test_subject_scale_policy_service_builds_observation_bundle_with_null_detector() -> None:
    service = SubjectScalePolicyService()

    bundle = service.build_bundle(
        mode="observe",
        prompt_intent={"intent_band": "portrait", "requested_pose": "unknown"},
        image_path=None,
        extra_observation={"stage_chain": ["txt2img", "adetailer"]},
    )

    assert bundle["mode"] == "observe"
    assert bundle["policy_id"] == "observe_only_v1"
    assert bundle["detector_id"] == "null"
    assert bundle["applied_overrides"] == {}
    assert bundle["observation"]["prompt_intent"]["intent_band"] == "portrait"
    assert bundle["observation"]["subject_assessment"]["notes"] == [
        "assessment_unavailable",
    ]
    assert bundle["observation"]["stage_chain"] == ["txt2img", "adetailer"]


def test_subject_scale_policy_service_includes_image_path_when_present(tmp_path: Path) -> None:
    service = SubjectScalePolicyService()
    image_path = tmp_path / "frame.png"
    image_path.write_bytes(b"png")

    assessment = service.assess(image_path=image_path)

    assert assessment["image_path"] == str(image_path)
    assert assessment["detector_id"] == "null"
    assert assessment["detection_count"] == 0


class _FixedDetector(SubjectDetector):
    detector_id = "fixed"

    def __init__(self, detections):
        self._detections = tuple(detections)

    def detect_faces(self, image_path: Path | None):
        return self._detections


def test_subject_scale_policy_service_assigns_scale_band_from_detection_size(
    tmp_path: Path,
) -> None:
    image_path = tmp_path / "subject.png"
    Image.new("RGB", (100, 100), color="white").save(image_path)
    service = SubjectScalePolicyService(
        detector=_FixedDetector([{"x": 10, "y": 10, "w": 20, "h": 20}])
    )

    assessment = service.assess(image_path=image_path)

    assert assessment["detector_id"] == "fixed"
    assert assessment["image_width"] == 100
    assert assessment["image_height"] == 100
    assert assessment["face_area_ratio"] == 0.04
    assert assessment["scale_band"] == "large"
    assert assessment["algorithm_version"] == "v1"


@pytest.mark.parametrize(
    ("size", "expected_band"),
    [
        ((5, 5), "micro"),
        ((10, 10), "small"),
        ((15, 15), "medium"),
        ((20, 20), "large"),
    ],
)
def test_subject_scale_policy_service_uses_versioned_threshold_bands(
    tmp_path: Path,
    size: tuple[int, int],
    expected_band: str,
) -> None:
    image_path = tmp_path / f"{expected_band}.png"
    Image.new("RGB", (100, 100), color="white").save(image_path)
    width, height = size
    service = SubjectScalePolicyService(
        detector=_FixedDetector([{"x": 0, "y": 0, "w": width, "h": height}]),
        cfg=SubjectScalePolicyConfig(algorithm_version="v1"),
    )

    assessment = service.assess(image_path=image_path)

    assert assessment["scale_band"] == expected_band
    assert assessment["algorithm_version"] == "v1"


def test_unavailable_detector_is_unknown_not_no_face(tmp_path: Path) -> None:
    service = SubjectScalePolicyService(
        unavailable_reason="YuNet model missing; restore repository asset"
    )
    assessment = service.assess(tmp_path / "image.png")
    assert assessment["scale_band"] == "unknown"
    assert assessment["detection_status"] == "unavailable"
    assert "no_face_detected" not in assessment["notes"]
    assert "restore repository asset" in assessment["notes"][0]


def test_inference_error_preserves_detector_identity(tmp_path: Path) -> None:
    class BrokenDetector:
        detector_id = "opencv_yunet"
        algorithm_version = "yunet_2026may/1"

        def detect_faces(self, path):
            raise RuntimeError("YuNet inference failed")

    assessment = SubjectScalePolicyService(detector=BrokenDetector()).assess(tmp_path / "image.png")
    assert assessment["scale_band"] == "unknown"
    assert assessment["detection_status"] == "error"
    assert assessment["detector_id"] == "opencv_yunet"
    assert assessment["detector_algorithm_version"] == "yunet_2026may/1"
    assert "no_face_detected" not in assessment["notes"]
