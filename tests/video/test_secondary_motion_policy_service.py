from __future__ import annotations

from src.video.motion.secondary_motion_policy_service import SecondaryMotionPolicyService


def test_secondary_motion_policy_service_builds_observation_only_policy() -> None:
    service = SecondaryMotionPolicyService()

    observation = service.build_observation(
        intent={
            "schema": "stablenew.secondary-motion.v1",
            "enabled": True,
            "mode": "observe",
            "intent": "micro_sway",
            "regions": ["hair", "fabric"],
            "allow_prompt_bias": False,
            "allow_native_backend": False,
            "record_decisions": True,
            "algorithm_version": "v1",
        },
        stage_name="video_workflow",
        backend_id="comfy",
        prompt="portrait woman with flowing hair, gentle breeze",
        negative_prompt="camera shake",
        motion_profile="cinematic",
        subject_summary={"scale_band": "small", "pose_band": "steady"},
    )

    assert observation["intent"]["enabled"] is True
    assert observation["policy"]["enabled"] is True
    assert observation["policy"]["backend_mode"] == "observe_shared_postprocess_candidate"
    assert observation["policy"]["subject_scale"] == "small"
    assert observation["policy"]["pose_class"] == "steady"
    assert observation["prompt_features"]["camera_locked"] is True


def test_secondary_motion_policy_service_disables_policy_when_intent_is_off() -> None:
    service = SecondaryMotionPolicyService()

    observation = service.build_observation(
        intent={"enabled": False, "mode": "disabled"},
        stage_name="animatediff",
        backend_id="animatediff",
        prompt="portrait",
        negative_prompt="",
    )

    assert observation["policy"]["enabled"] is False
    assert observation["policy"]["backend_mode"] == "disabled"
    assert observation["policy"]["reasons"] == ["secondary_motion_disabled"]
