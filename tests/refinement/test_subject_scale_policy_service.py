from __future__ import annotations

from pathlib import Path

from src.refinement.subject_scale_policy_service import SubjectScalePolicyService


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
        "no_face_detected",
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
