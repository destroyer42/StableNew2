"""PR-VID-MOTION-410 Workstream G: global image-motion diagnostics on deterministic synthetic clips.

The clips are numpy luma arrays (a bright bar moving at a chosen speed over a dark field, or a smooth pattern shifting
as a whole), so every expected onset, offset, lag and rate is known exactly. Nothing decodes a real video.
"""

from __future__ import annotations

from types import SimpleNamespace

import numpy as np
import pytest

from src.video.video_eval_motion_metrics import (
    DIAGNOSTIC_KIND,
    STATUS_INSUFFICIENT,
    STATUS_OK,
    STATUS_UNAVAILABLE,
    DiagnosticClip,
    PreviewCache,
    compare_clips,
    describe_clip,
    diagnose_paths,
    motion_energy,
    unavailable,
)

SIZE = 32


def bar_clip(velocity, *, fps=24.0, label="clip", width=8.0, **fields) -> DiagnosticClip:
    """A bar whose horizontal speed (pixels per frame) over time is ``velocity``; energy is proportional to speed."""

    position, frames = 2.0, []
    columns = np.arange(SIZE, dtype=np.float64)
    for index in range(len(velocity) + 1):
        coverage = np.clip(
            np.minimum(columns + 1, position + width) - np.maximum(columns, position), 0, 1
        )
        frame = np.zeros((SIZE, SIZE), dtype=np.float32)
        frame[8:24, :] = coverage.astype(np.float32)
        frames.append(frame)
        if index < len(velocity):
            position += float(velocity[index])
    return DiagnosticClip(label, np.stack(frames), fps, **fields)


def bump(frames, start, stop, speed=0.3):
    values = np.zeros(frames)
    values[start:stop] = speed
    return values


def gaussian(frames, center, spread=6.0, peak=0.4):
    index = np.arange(frames)
    return peak * np.exp(-0.5 * ((index - center) / spread) ** 2)


def shifted_pattern_clip(velocity, *, fps=24.0, label="camera", **fields) -> DiagnosticClip:
    """The whole frame (a smooth pattern) translating: a camera-like move with no subject at all."""

    position, frames = 0.0, []
    columns = np.arange(SIZE, dtype=np.float64)
    for index in range(len(velocity) + 1):
        row = 0.5 + 0.5 * np.sin(0.4 * (columns - position))
        frames.append(np.tile(row, (SIZE, 1)).astype(np.float32))
        if index < len(velocity):
            position += float(velocity[index])
    return DiagnosticClip(label, np.stack(frames), fps, **fields)


def brightness_ramp_clip(frames=48, *, fps=24.0) -> DiagnosticClip:
    base = np.full((SIZE, SIZE), 0.2, dtype=np.float32)
    return DiagnosticClip("ramp", np.stack([base + 0.01 * i for i in range(frames)]), fps)


def static_clip(frames=48, *, fps=24.0, label="static") -> DiagnosticClip:
    return DiagnosticClip(label, np.full((frames, SIZE, SIZE), 0.3, dtype=np.float32), fps)


# ------------------------------------------------------------------ single clip facts


def test_motion_energy_is_zero_for_a_static_clip_and_positive_for_a_moving_one() -> None:
    assert float(motion_energy(static_clip().luma).max()) == 0.0
    assert float(motion_energy(bar_clip(bump(48, 10, 30)).luma).max()) > 0.5


def test_a_static_clip_is_reported_static_with_a_frozen_interval_not_as_zero_fidelity() -> None:
    facts = describe_clip(static_clip())
    assert facts["static"] is True and facts["active_seconds"] == 0.0
    assert facts["onset_seconds"] is None and facts["offset_seconds"] is None
    assert facts["repeated_frame_ratio"] == 1.0
    assert facts["frozen_intervals"] and facts["frozen_intervals"][0]["start_seconds"] == 0.0


def test_known_onset_and_offset_are_recovered_from_the_trace() -> None:
    facts = describe_clip(bar_clip(bump(48, 12, 36)))
    assert facts["onset_seconds"] == pytest.approx(0.5, abs=1e-3)
    assert facts["offset_seconds"] == pytest.approx(1.5, abs=1e-3)
    assert facts["active_seconds"] == pytest.approx(1.0, abs=1e-3)
    assert facts["static"] is False


def test_repeated_frames_are_counted_and_a_held_tail_is_reported() -> None:
    velocity = np.concatenate([bump(30, 0, 30), np.zeros(18)])  # moves, then holds its last frame
    facts = describe_clip(bar_clip(velocity))
    assert facts["held_tail_frames"] == 18
    assert facts["held_tail_seconds"] == pytest.approx(0.75, abs=1e-3)
    doubled = DiagnosticClip("doubled", np.repeat(bar_clip(gaussian(24, 12)).luma, 2, axis=0), 24.0)
    assert describe_clip(doubled)["repeated_frame_ratio"] == pytest.approx(0.5, abs=0.03)


def test_a_clip_without_a_frame_rate_has_no_timing_values() -> None:
    facts = describe_clip(bar_clip(bump(48, 10, 30), fps=None))
    assert facts["status"] == STATUS_INSUFFICIENT and facts["onset_seconds"] is None
    assert facts["duration_seconds"] is None


# ------------------------------------------------------------------ pair comparison


def test_a_matching_trace_correlates_with_no_displacement() -> None:
    profile = gaussian(72, 36)
    out = compare_clips(bar_clip(profile, label="driver"), bar_clip(profile, label="result"))
    comparison = out["comparison"]
    assert out["status"] == STATUS_OK and out["kind"] == DIAGNOSTIC_KIND
    assert comparison["trace_correlation"] > 0.95
    assert comparison["lag_seconds"] == pytest.approx(0.0, abs=1 / 24)
    assert comparison["relative_motion_magnitude"] == pytest.approx(1.0, abs=0.05)


def test_a_known_temporal_offset_is_measured_as_a_lag() -> None:
    driver = bar_clip(gaussian(96, 30))
    late = bar_clip(gaussian(96, 36))  # the same movement, 6 frames (0.25 s) later
    out = compare_clips(driver, late)
    assert out["comparison"]["lag_seconds"] == pytest.approx(0.25, abs=1 / 24)
    assert out["comparison"]["onset_displacement_seconds"] == pytest.approx(0.25, abs=0.1)
    early = compare_clips(late, driver)
    assert early["comparison"]["lag_seconds"] == pytest.approx(-0.25, abs=1 / 24)


def test_different_frame_rates_are_compared_on_seconds_not_frame_indices() -> None:
    # The same 2 s movement sampled at 24 fps and at 12 fps (the frame indices differ by a factor of two).
    fast = bar_clip(gaussian(48, 24, spread=6, peak=0.4), fps=24.0)
    slow = bar_clip(gaussian(24, 12, spread=3, peak=0.8), fps=12.0)
    comparison = compare_clips(fast, slow)["comparison"]
    assert comparison["fps_differs"] is True
    assert comparison["trace_correlation"] > 0.9
    assert comparison["lag_seconds"] == pytest.approx(0.0, abs=0.1)
    assert comparison["common_time_basis"].startswith("seconds")


def test_a_shorter_result_is_disclosed_and_compared_over_the_overlap_only() -> None:
    driver = bar_clip(gaussian(96, 48), label="driver")
    short = bar_clip(gaussian(48, 24), label="result")
    comparison = compare_clips(driver, short)["comparison"]
    assert comparison["duration_difference_seconds"] == pytest.approx(2.0, abs=0.05)
    assert comparison["compared_seconds"] == pytest.approx(2.0, abs=0.1)


def test_an_altered_cadence_moves_the_offset() -> None:
    driver = bar_clip(bump(72, 12, 60))  # 0.5 s to 2.5 s
    hurried = bar_clip(bump(72, 12, 36))  # finishes in half the time
    comparison = compare_clips(driver, hurried)["comparison"]
    assert comparison["offset_displacement_seconds"] == pytest.approx(-1.0, abs=0.1)


def test_the_driver_held_tail_is_excluded_from_the_compared_window() -> None:
    driver = bar_clip(
        np.concatenate([gaussian(48, 24), np.zeros(24)])
    )  # a 1 s prepared last-frame hold
    result = bar_clip(gaussian(72, 24))
    comparison = compare_clips(driver, result)["comparison"]
    # The appended 1 s hold is reported (a decaying tail below the repeat threshold may add to it) and not compared.
    assert comparison["driver_held_tail_seconds"] >= 1.0
    assert comparison["compared_seconds"] <= 2.0


def test_a_frozen_result_while_the_driver_moves_is_insufficient_evidence_not_a_zero() -> None:
    out = compare_clips(bar_clip(gaussian(48, 24)), static_clip())
    comparison = out["comparison"]
    assert out["status"] == STATUS_INSUFFICIENT
    assert comparison["result_frozen_while_driver_active_seconds"] > 0.5
    assert comparison["trace_correlation"] is None  # unavailable, never 0
    assert any("no variation" in reason for reason in out["reasons"])


def test_a_static_driver_gives_no_comparison() -> None:
    out = compare_clips(static_clip(label="driver"), bar_clip(gaussian(48, 24)))
    assert out["status"] == STATUS_INSUFFICIENT and out["comparison"] is None
    assert any("no global image motion" in reason for reason in out["reasons"])


def test_constant_speed_motion_has_a_zero_variance_trace() -> None:
    constant = bar_clip(np.full(48, 0.3))
    out = compare_clips(bar_clip(gaussian(48, 24)), constant)
    assert (
        out["comparison"]["trace_correlation"] is None and out["comparison"]["lag_seconds"] is None
    )


def test_a_brightness_change_does_not_look_like_the_drivers_motion() -> None:
    out = compare_clips(bar_clip(gaussian(48, 24)), brightness_ramp_clip())
    # A steady brightness ramp is constant energy: no trace variation, so no similarity is claimed.
    assert out["comparison"]["trace_correlation"] is None
    assert out["status"] == STATUS_INSUFFICIENT


def test_a_camera_like_move_is_indistinguishable_from_subject_motion_and_the_result_says_so() -> (
    None
):
    profile = gaussian(72, 36)
    out = compare_clips(bar_clip(profile, label="driver"), shifted_pattern_clip(profile))
    # High similarity is expected here; that is exactly why it is not evidence about the intended subject.
    assert out["comparison"]["trace_correlation"] > 0.9
    assert out["subject_attachment_evidence"] is False
    assert out["validated_pose_fidelity"] is False
    assert any("Camera moves" in text for text in out["limitations"])
    assert "score" not in out and "fidelity_score" not in out["comparison"]


def test_a_truncated_preview_is_disclosed() -> None:
    driver = bar_clip(gaussian(72, 36), truncated=True, reported_frames=300)
    out = compare_clips(driver, bar_clip(gaussian(72, 36)))
    assert out["status"] == STATUS_OK
    assert any("only the first frames" in reason for reason in out["reasons"])


def test_a_clip_without_a_frame_rate_cannot_be_placed_on_a_common_time_basis() -> None:
    out = compare_clips(bar_clip(gaussian(48, 24), fps=None), bar_clip(gaussian(48, 24)))
    assert out["status"] == STATUS_INSUFFICIENT and out["comparison"] is None
    assert any("frame rate" in reason for reason in out["reasons"])


def test_too_few_overlapping_samples_give_insufficient_evidence() -> None:
    tiny = bar_clip(np.array([1.0, 2.0, 1.0]))
    out = compare_clips(tiny, tiny)
    assert out["status"] == STATUS_INSUFFICIENT and out["comparison"]["trace_correlation"] is None


# ------------------------------------------------------------------ media access


def _result(clip: DiagnosticClip):
    return SimpleNamespace(
        ok=True,
        message="",
        clip=SimpleNamespace(
            frame_count=clip.frames,
            fps=clip.fps,
            reported_frame_count=None,
            truncated=False,
            raw=b"",
            frame_bytes=0,
            height=0,
            width=0,
        ),
        _luma=clip,
    )


def test_missing_or_undecodable_media_is_unavailable_with_the_reason() -> None:
    def decode(path, cancel=None):
        return SimpleNamespace(ok=False, message=f"{path} is not a supported video", clip=None)

    out = diagnose_paths("driver.xyz", "result.mp4", cache=PreviewCache(decode))
    assert out["status"] == STATUS_UNAVAILABLE and out["comparison"] is None
    assert any("not a supported video" in reason for reason in out["reasons"])
    none = diagnose_paths(None, None)
    assert none["status"] == STATUS_UNAVAILABLE
    assert any("no driving reference file" in reason for reason in none["reasons"])


def test_a_shared_driving_reference_is_decoded_once(monkeypatch) -> None:
    calls: list[str] = []

    def decode(path, cancel=None):
        calls.append(path)
        return SimpleNamespace(ok=False, message="stop", clip=None)

    cache = PreviewCache(decode)
    for result in ("a.mp4", "b.mp4", "c.mp4"):
        diagnose_paths("driver.mp4", result, cache=cache)
    assert calls.count("driver.mp4") == 1 and len(calls) == 4


def test_an_explicitly_unavailable_diagnostic_has_no_numbers() -> None:
    out = unavailable("the driving video changed after admission")
    assert out["status"] == STATUS_UNAVAILABLE and out["comparison"] is None
    assert out["subject_attachment_evidence"] is False
