from __future__ import annotations

from src.pipeline.result_contract_v26 import build_diagnostics_descriptor, build_replay_descriptor


def test_result_contract_carries_secondary_motion_summary() -> None:
    result = {
        "run_id": "run-123",
        "success": True,
        "variants": [],
        "metadata": {
            "output_dir": "output/test",
            "secondary_motion": {
                "intent": {"enabled": True, "mode": "observe", "intent": "micro_sway"},
                "primary_policy": {
                    "policy_id": "observe_policy_v1",
                    "enabled": True,
                    "backend_mode": "observe_shared_postprocess_candidate",
                    "intensity": 0.25,
                    "cap_pixels": 12,
                },
            },
        },
        "stage_events": [{"stage": "video_workflow"}],
    }

    replay = build_replay_descriptor(result, njr_snapshot={"normalized_job": {"job_id": "job-123"}})
    diagnostics = build_diagnostics_descriptor(result, njr_snapshot={"normalized_job": {"job_id": "job-123"}})

    assert replay["secondary_motion"]["status"] == "observe"
    assert replay["secondary_motion"]["policy_id"] == "observe_policy_v1"
    assert diagnostics["secondary_motion"]["status"] == "observe"
    assert diagnostics["replay_descriptor"]["secondary_motion"]["policy_id"] == "observe_policy_v1"
