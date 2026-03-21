from __future__ import annotations

from src.video.motion.secondary_motion_models import (
    SECONDARY_MOTION_POLICY_SCHEMA_V1,
    SECONDARY_MOTION_SCHEMA_V1,
    SecondaryMotionIntent,
    SecondaryMotionPolicy,
)


def test_secondary_motion_intent_round_trip() -> None:
    intent = SecondaryMotionIntent(
        enabled=True,
        mode="observe",
        intent="micro_sway",
        regions=("hair", "fabric"),
        allow_prompt_bias=False,
        allow_native_backend=True,
        record_decisions=True,
        seed=1234,
        algorithm_version="v1",
    )

    restored = SecondaryMotionIntent.from_dict(intent.to_dict())

    assert restored == intent
    assert restored.schema == SECONDARY_MOTION_SCHEMA_V1


def test_secondary_motion_policy_round_trip() -> None:
    policy = SecondaryMotionPolicy(
        policy_id="comfy_video_workflow_observe_v1",
        enabled=True,
        backend_mode="observe_native_candidate",
        intensity=0.25,
        damping=0.9,
        frequency_hz=0.2,
        cap_pixels=12,
        subject_scale="small",
        pose_class="steady",
        reasons=("backend=comfy", "subject_scale=small"),
        algorithm_version="v1",
    )

    restored = SecondaryMotionPolicy.from_dict(policy.to_dict())

    assert restored == policy
    assert restored.schema == SECONDARY_MOTION_POLICY_SCHEMA_V1


def test_invalid_secondary_motion_mode_defaults_to_disabled() -> None:
    restored = SecondaryMotionIntent.from_dict({"enabled": True, "mode": "chaos"})

    assert restored.mode == "disabled"
