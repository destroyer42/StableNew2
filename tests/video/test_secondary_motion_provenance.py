from __future__ import annotations

from src.video.motion.secondary_motion_provenance import (
    SECONDARY_MOTION_PROVENANCE_SCHEMA_V1,
    SECONDARY_MOTION_SUMMARY_SCHEMA_V1,
    build_secondary_motion_manifest_block,
    extract_secondary_motion_summary,
)


def test_secondary_motion_manifest_block_contains_summary() -> None:
    block = build_secondary_motion_manifest_block(
        intent={"enabled": True, "mode": "apply", "intent": "micro_sway"},
        policy={
            "policy_id": "apply_policy_v1",
            "enabled": True,
            "backend_mode": "apply_shared_postprocess_candidate",
            "intensity": 0.4,
            "cap_pixels": 8,
        },
        apply_result={
            "status": "applied",
            "application_path": "shared_postprocess_engine",
            "skip_reason": "",
            "metrics": {"avg_abs_dx": 1.2, "max_abs_dx": 3},
        },
    )

    assert block["schema"] == SECONDARY_MOTION_PROVENANCE_SCHEMA_V1
    assert block["summary"]["schema"] == SECONDARY_MOTION_SUMMARY_SCHEMA_V1
    assert block["summary"]["status"] == "applied"
    assert block["summary"]["policy_id"] == "apply_policy_v1"
    assert block["summary"]["metrics"]["avg_abs_dx"] == 1.2


def test_extract_secondary_motion_summary_handles_observation_payload() -> None:
    summary = extract_secondary_motion_summary(
        {
            "secondary_motion": {
                "intent": {"enabled": True, "mode": "observe", "intent": "micro_sway"},
                "primary_policy": {
                    "policy_id": "observe_policy_v1",
                    "enabled": True,
                    "backend_mode": "observe_shared_postprocess_candidate",
                    "intensity": 0.25,
                    "cap_pixels": 12,
                },
            }
        }
    )

    assert summary["schema"] == SECONDARY_MOTION_SUMMARY_SCHEMA_V1
    assert summary["status"] == "observe"
    assert summary["application_path"] == "policy_observation_only"
    assert summary["policy_id"] == "observe_policy_v1"
    assert summary["intent"]["mode"] == "observe"
