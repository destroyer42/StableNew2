"""PR-VID-184 tracking/scoring: pure-stdlib synthetic-box tests (no video, no detector, no
GPU/network). Locks in the greedy nearest-centroid tracker's behavior on the three
detector-dependent Phase C metrics before it is trusted against real detector output."""

from __future__ import annotations

from tools.qualification.vid184.tracking import track

FRAME_WIDTH = 400


def _box(cx: float, cy: float, w: float = 40, h: float = 100, score: float = 0.9) -> list[float]:
    return [cx - w / 2, cy - h / 2, cx + w / 2, cy + h / 2, score]


def test_single_continuous_subject_passes_all_three_metrics() -> None:
    # A subject walking steadily left to right: one box per frame, no ghost.
    frames = [[_box(50 + 5 * i, 200)] for i in range(20)]
    payload = {"frames": frames, "frame_width": FRAME_WIDTH}
    result = track(payload)
    assert result.primary_subject_continuity == 1.0
    assert result.ghost_actor_persistence == 0
    assert result.root_translation_fraction > 0.15


def test_planted_subject_with_persistent_ghost_fails() -> None:
    # The PR-VID-181 Case B failure shape: a stationary primary figure plus a separate
    # figure that performs the actual stepping motion across many consecutive frames.
    frames = [
        [_box(50, 200), _box(50 + 10 * i, 600)]  # primary stays put; ghost moves and persists
        for i in range(20)
    ]
    payload = {"frames": frames, "frame_width": FRAME_WIDTH}
    result = track(payload)
    assert result.root_translation_fraction < 0.15  # primary itself never translates
    assert result.ghost_actor_persistence >= 10  # ghost present for many consecutive frames


def test_no_detection_frames_reduce_continuity_without_crashing() -> None:
    frames = (
        [[_box(50, 200)] for _ in range(5)]
        + [[] for _ in range(5)]
        + [[_box(90, 200)] for _ in range(5)]
    )
    payload = {"frames": frames, "frame_width": FRAME_WIDTH}
    result = track(payload)
    assert result.frame_count == 15
    assert result.primary_subject_continuity == 10 / 15


def test_large_jump_is_treated_as_track_loss_not_teleport() -> None:
    # A detection far outside max_jump_fraction is NOT stitched into the primary track (that
    # would let a distant false positive/ghost fake continuity or root translation): the frame
    # is instead treated as a track loss and does not count as "primary present". This is a
    # deliberately conservative choice -- the alternative (silently reacquiring on the nearest
    # box in the very next frame) would let a same-frame ghost hijack the primary track.
    frames = [[_box(50, 200)]] + [[_box(50 + FRAME_WIDTH, 200)]]  # jump > frame width away
    payload = {"frames": frames, "frame_width": FRAME_WIDTH}
    result = track(payload, max_jump_fraction=0.35)
    assert result.primary_present_frames == 1
    assert result.primary_subject_continuity == 0.5


def test_empty_video_returns_zeroed_result_without_crashing() -> None:
    payload = {"frames": [], "frame_width": FRAME_WIDTH}
    result = track(payload)
    assert result.frame_count == 0
    assert result.primary_subject_continuity == 0.0
    assert result.ghost_actor_persistence == 0
    assert result.root_translation_fraction == 0.0


def test_short_ghost_blip_stays_under_the_two_frame_noise_threshold() -> None:
    # A single-frame false-positive ghost should not itself cross the frozen
    # GHOST_ACTOR_MAX_PERSISTENT_FRAMES=2 pass/fail gate (that assertion lives in the scoring
    # contract test; this test only locks in the tracker's own consecutive-run counting).
    frames = [[_box(50, 200)], [_box(55, 200), _box(300, 600)], [_box(60, 200)]]
    payload = {"frames": frames, "frame_width": FRAME_WIDTH}
    result = track(payload)
    assert result.ghost_actor_persistence == 1
