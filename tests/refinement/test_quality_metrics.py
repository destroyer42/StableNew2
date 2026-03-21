from __future__ import annotations

from pathlib import Path

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
                        "face_area_ratio": 0.12,
                    }
                },
                "applied_overrides": {"upscale_steps": 18, "upscale_denoising_strength": 0.18},
                "prompt_patch": {"add_positive": ["clear irises"], "remove_positive": ["soft face"]},
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
