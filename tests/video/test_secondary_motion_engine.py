from __future__ import annotations

from PIL import Image

from src.video.motion.secondary_motion_engine import apply_secondary_motion_to_frames
from src.video.motion.secondary_motion_models import SecondaryMotionIntent, SecondaryMotionPolicy


def _make_frames(count: int = 3) -> list[Image.Image]:
    frames: list[Image.Image] = []
    for index in range(count):
        image = Image.new("RGBA", (12, 12), (255, 0, 0, 255))
        image.putpixel((index % 12, index % 12), (0, 0, 255, 255))
        frames.append(image)
    return frames


def test_secondary_motion_engine_is_deterministic_for_fixed_seed() -> None:
    frames = _make_frames()
    policy = SecondaryMotionPolicy(
        policy_id="shared_motion_apply_v1",
        enabled=True,
        backend_mode="apply_shared_postprocess_candidate",
        intensity=0.45,
        damping=0.9,
        frequency_hz=0.4,
        cap_pixels=4,
    )
    intent = SecondaryMotionIntent(enabled=True, mode="apply", intent="micro_sway", regions=("hair",))

    first_frames, first_result = apply_secondary_motion_to_frames(
        [frame.copy() for frame in frames],
        policy=policy,
        intent=intent,
        seed=1234,
    )
    second_frames, second_result = apply_secondary_motion_to_frames(
        [frame.copy() for frame in frames],
        policy=policy,
        intent=intent,
        seed=1234,
    )

    assert first_result.to_dict() == second_result.to_dict()
    assert [frame.tobytes() for frame in first_frames] == [frame.tobytes() for frame in second_frames]


def test_secondary_motion_engine_observe_mode_skips_frame_mutation() -> None:
    frames = _make_frames()
    policy = SecondaryMotionPolicy(
        policy_id="shared_motion_observe_v1",
        enabled=True,
        backend_mode="observe_shared_postprocess_candidate",
        intensity=0.4,
        damping=0.9,
        frequency_hz=0.2,
        cap_pixels=6,
    )

    output_frames, result = apply_secondary_motion_to_frames(frames, policy=policy)

    assert result.status == "observe"
    assert result.skip_reason == "observe_only"
    assert result.application_path == "policy_observation_only"
    assert [frame.tobytes() for frame in output_frames] == [frame.tobytes() for frame in frames]


def test_secondary_motion_engine_respects_cap_clamps() -> None:
    frames = _make_frames()
    policy = SecondaryMotionPolicy(
        policy_id="shared_motion_clamp_v1",
        enabled=True,
        backend_mode="apply_shared_postprocess_candidate",
        intensity=2.0,
        damping=1.0,
        frequency_hz=1.0,
        cap_pixels=3,
    )

    _output_frames, result = apply_secondary_motion_to_frames(frames, policy=policy, seed=99)

    assert result.status == "applied"
    assert int((result.metrics or {}).get("max_abs_dx", 0)) <= 3
    assert int((result.metrics or {}).get("cap_pixels", 0)) == 3
