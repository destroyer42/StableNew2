from __future__ import annotations

from pathlib import Path

import pytest

from src.refinement.quality_metrics import (
    build_refinement_learning_context,
    compute_image_sharpness_variance,
)


def test_build_refinement_learning_context_extracts_compact_scalar_summary() -> None:
    context = build_refinement_learning_context(
        {
            "intent": {
                "mode": "full",
                "profile_id": "auto_v1",
                "detector_preference": "null",
                "algorithm_version": "v1",
            },
            "prompt_intent": {
                "intent_band": "portrait",
                "requested_pose": "profile",
                "wants_face_detail": True,
            },
            "decision_bundle": {
                "algorithm_version": "v1",
                "policy_id": "full_upscale_detail_v1",
                "detector_id": "null",
                "observation": {
                    "subject_assessment": {
                        "scale_band": "small",
                        "pose_band": "profile",
                        "detection_count": 1,
                        "detection_status": "available",
                        "face_area_ratio": 0.12,
                    }
                },
                "applied_overrides": {"upscale_steps": 18, "upscale_denoising_strength": 0.18},
                "prompt_patch": {
                    "add_positive": ["clear irises"],
                    "remove_positive": ["soft face"],
                },
            },
            "image_decisions": [{"decision_bundle": {"policy_id": "full_upscale_detail_v1"}}],
        }
    )

    assert context["mode"] == "full"
    assert context["policy_id"] == "full_upscale_detail_v1"
    assert context["policy_ids"] == ["full_upscale_detail_v1"]
    assert context["scale_band"] == "small"
    assert context["pose_band"] == "profile"
    assert context["face_detected"] is True
    assert context["face_count"] == 1
    assert context["face_area_ratio"] == 0.12
    assert context["prompt_patch_ops"] == "add_positive,remove_positive"
    assert context["applied_override_keys"] == "upscale_denoising_strength,upscale_steps"


def test_compute_image_sharpness_variance_returns_none_when_missing_path() -> None:
    assert compute_image_sharpness_variance(Path("missing-file.png")) is None


def test_unknown_detection_does_not_claim_a_face_and_preserves_yunet_version() -> None:
    context = build_refinement_learning_context(
        {
            "decision_bundle": {
                "observation": {
                    "subject_assessment": {
                        "scale_band": "unknown",
                        "detection_status": "error",
                        "detection_count": 0,
                        "detector_id": "opencv_yunet",
                        "detector_algorithm_version": "yunet_2026may/1",
                    },
                }
            }
        }
    )
    assert context["face_detected"] is None
    assert context["detection_status"] == "error"
    assert context["detector_algorithm_version"] == "yunet_2026may/1"


@pytest.mark.parametrize(
    ("status", "count", "band", "expected"),
    [
        ("available", 1, "small", True),
        ("available", 2, "large", True),
        ("available", 0, "no_face", False),
        ("unavailable", 0, "unknown", None),
        ("error", 0, "unknown", None),
        ("timeout", 0, "unknown", None),
        ("error", 1, "small", None),
        ("timeout", 1, "large", None),
        ("available", 1, "unknown", None),
        ("available", 0, "unknown", None),
        ("available", 0, "small", None),
        ("available", 1, "no_face", None),
        ("available", None, "no_face", None),
        ("available", -1, "no_face", None),
        ("unrecognized", 1, "small", None),
        (None, 1, "small", None),
    ],
)
def test_face_detected_requires_qualified_status_and_consistent_evidence(
    status: str | None, count: int | None, band: str, expected: bool | None
) -> None:
    context = build_refinement_learning_context(
        {
            "decision_bundle": {
                "observation": {
                    "subject_assessment": {
                        "detection_status": status,
                        "detection_count": count,
                        "scale_band": band,
                    }
                }
            }
        }
    )
    assert context["face_detected"] is expected


def test_missing_assessment_is_unknown() -> None:
    context = build_refinement_learning_context({"intent": {"mode": "observe"}})
    assert context["face_detected"] is None
