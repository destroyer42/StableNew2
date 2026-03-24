from __future__ import annotations

from src.video.motion.secondary_motion_metrics import build_secondary_motion_learning_context


def test_secondary_motion_metrics_normalize_applied_context_from_run_metadata() -> None:
    context = build_secondary_motion_learning_context(
        {
            "video_primary_backend_id": "comfy",
            "secondary_motion": {
                "summary": {
                    "enabled": True,
                    "status": "applied",
                    "policy_id": "workflow_motion_v1",
                    "application_path": "video_reencode_worker",
                    "backend_mode": "apply_shared_postprocess_candidate",
                    "intent": {"mode": "apply", "intent": "micro_sway"},
                    "metrics": {
                        "frames_in": 16,
                        "frames_out": 16,
                        "applied_frame_count": 12,
                        "intensity": 0.25,
                        "damping": 0.9,
                        "frequency_hz": 0.2,
                        "cap_pixels": 12,
                        "avg_abs_dx": 1.0,
                        "avg_abs_dy": 0.3,
                        "max_abs_dx": 2,
                        "max_abs_dy": 1,
                    },
                }
            },
        }
    )

    assert context["backend_id"] == "comfy"
    assert context["status"] == "applied"
    assert context["policy_id"] == "workflow_motion_v1"
    assert context["application_path"] == "video_reencode_worker"
    assert context["applied_motion_strength"] == 0.25
    assert context["frame_count_delta"] == 0
    assert context["applied_frame_ratio"] == 0.75
    assert context["quality_risk_score"] > 0.0


def test_secondary_motion_metrics_normalize_unavailable_context_without_dense_payloads() -> None:
    context = build_secondary_motion_learning_context(
        {
            "video_primary_backend_id": "animatediff",
            "secondary_motion": {
                "apply_result": {
                    "frames_in": 24,
                    "frames_out": 24,
                    "regions_applied": ["hair"],
                },
                "summary": {
                    "enabled": True,
                    "status": "unavailable",
                    "policy_id": "animatediff_motion_v1",
                    "application_path": "frame_directory_worker",
                    "backend_mode": "apply_shared_postprocess_candidate",
                    "intent": {"mode": "apply", "intent": "micro_sway"},
                    "skip_reason": "worker_failed",
                    "metrics": {"applied_frame_count": 0, "frames_in": 24, "frames_out": 24},
                },
            },
            "secondary_motion_source_video_path": "ignored.mp4",
        }
    )

    assert context["backend_id"] == "animatediff"
    assert context["status"] == "unavailable"
    assert context["skip_reason"] == "worker_failed"
    assert context["regions_applied"] == 1
    assert context["applied_motion_strength"] == 0.0
    assert context["quality_risk_score"] == 0.0
    assert "secondary_motion_source_video_path" not in context