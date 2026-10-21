"""PR-VID-POST-304: temporal stabilisation of per-frame face restoration (pure math, no models).

The smoothing is deterministic, so every expectation here is computed from synthetic landmarks and
synthetic face crops: no detector, no network, no GPU.
"""

from __future__ import annotations

import math
import random

import pytest
from PIL import Image

from src.video.restoration.temporal import (
    FaceLandmarkSmoother,
    ResidualSmoother,
    TemporalFaceStabilizer,
    frame_signature,
    is_scene_cut,
)

# Left eye, right eye, nose, left mouth corner, right mouth corner (the detector's order), 100 px wide.
_BASE = ((100.0, 120.0), (160.0, 120.0), (130.0, 150.0), (108.0, 180.0), (152.0, 180.0))


def _shift(landmarks, dx: float, dy: float):
    return tuple((x + dx, y + dy) for x, y in landmarks)


def _jittered(count: int, amplitude: float, seed: int = 11):
    rng = random.Random(seed)
    return [
        tuple(
            (x + rng.uniform(-amplitude, amplitude), y + rng.uniform(-amplitude, amplitude))
            for x, y in _BASE
        )
        for _ in range(count)
    ]


def _similarity(landmarks, template):
    """Least-squares 4-DOF similarity (scale, rotation, translation) landmarks -> template (Umeyama)."""

    n = len(landmarks)
    mx = sum(p[0] for p in landmarks) / n
    my = sum(p[1] for p in landmarks) / n
    tx = sum(p[0] for p in template) / n
    ty = sum(p[1] for p in template) / n
    a = b = norm = 0.0
    for (x, y), (u, v) in zip(landmarks, template, strict=True):
        x, y, u, v = x - mx, y - my, u - tx, v - ty
        a += x * u + y * v
        b += x * v - y * u
        norm += x * x + y * y
    scale = math.hypot(a, b) / norm
    angle = math.atan2(b, a)
    # Translation of the template origin expressed in the landmark frame.
    off_x = tx - scale * (math.cos(angle) * mx - math.sin(angle) * my)
    off_y = ty - scale * (math.sin(angle) * mx + math.cos(angle) * my)
    return scale, angle, off_x, off_y


def _std(values):
    mean = sum(values) / len(values)
    return math.sqrt(sum((v - mean) ** 2 for v in values) / len(values))


# --- landmark smoothing -----------------------------------------------------------------------


def test_first_observation_is_returned_unsmoothed_and_starts_a_track() -> None:
    smoother = FaceLandmarkSmoother()

    [face] = smoother.update([_BASE])

    assert face.landmarks == _BASE
    assert face.continued is False


def test_ema_blends_the_new_observation_with_the_previous_smoothed_value() -> None:
    smoother = FaceLandmarkSmoother(alpha=0.25)
    smoother.update([_BASE])

    [face] = smoother.update([_shift(_BASE, 8.0, -4.0)])

    # smoothed = alpha * new + (1 - alpha) * previous, for every coordinate.
    assert face.continued is True
    for (sx, sy), (bx, by) in zip(face.landmarks, _BASE, strict=True):
        assert sx == pytest.approx(bx + 0.25 * 8.0)
        assert sy == pytest.approx(by - 0.25 * 4.0)


def test_constant_velocity_motion_converges_to_the_analytic_ema_lag() -> None:
    alpha, velocity = 0.4, 3.0
    smoother = FaceLandmarkSmoother(alpha=alpha)
    smoothed_x = None
    for frame in range(60):
        [face] = smoother.update([_shift(_BASE, velocity * frame, 0.0)])
        smoothed_x = face.landmarks[0][0]

    # A first-order filter trails a ramp by velocity * (1 - alpha) / alpha once settled.
    assert smoothed_x == pytest.approx(
        _BASE[0][0] + velocity * 59 - velocity * (1 - alpha) / alpha, abs=1e-6
    )


def test_jitter_is_reduced_in_landmarks_and_in_the_alignment_transform() -> None:
    template = tuple((x * 0.8 + 20.0, y * 0.8 - 40.0) for x, y in _BASE)
    observed = _jittered(80, amplitude=2.0)
    smoother = FaceLandmarkSmoother()
    smoothed = [smoother.update([frame])[0].landmarks for frame in observed]

    raw_params = [_similarity(frame, template) for frame in observed]
    smooth_params = [_similarity(frame, template) for frame in smoothed]

    # Skip the warm-up frame; every component of the alignment (scale, rotation, translation)
    # must wobble clearly less, which is what keeps the pasted face from shimmering.
    for index, name in enumerate(("scale", "angle", "offset_x", "offset_y")):
        raw = _std([p[index] for p in raw_params[5:]])
        smooth = _std([p[index] for p in smooth_params[5:]])
        assert smooth < 0.7 * raw, f"{name}: smoothed std {smooth:.5f} vs raw {raw:.5f}"


def test_smoothing_is_deterministic() -> None:
    observed = _jittered(25, amplitude=1.5)

    def run():
        smoother = FaceLandmarkSmoother()
        return [smoother.update([frame])[0].landmarks for frame in observed]

    assert run() == run()


def test_a_large_jump_starts_a_new_unsmoothed_track() -> None:
    smoother = FaceLandmarkSmoother(alpha=0.2, max_jump=1.0)
    [first] = smoother.update([_BASE])
    jumped = _shift(_BASE, 400.0, 0.0)  # far more than one eye distance (60 px)

    [second] = smoother.update([jumped])

    assert second.continued is False
    assert second.landmarks == jumped  # no drag towards the old position
    assert second.track_id != first.track_id


def test_a_move_within_the_jump_limit_stays_on_the_same_track() -> None:
    smoother = FaceLandmarkSmoother(max_jump=1.0)
    [first] = smoother.update([_BASE])

    [second] = smoother.update([_shift(_BASE, 30.0, 0.0)])  # half an eye distance

    assert second.track_id == first.track_id and second.continued is True


def test_two_faces_keep_their_own_tracks_when_detection_order_swaps() -> None:
    left, right = _BASE, _shift(_BASE, 300.0, 0.0)
    smoother = FaceLandmarkSmoother(alpha=0.5)
    first = smoother.update([left, right])

    swapped = smoother.update([_shift(right, 2.0, 0.0), _shift(left, 2.0, 0.0)])

    assert swapped[0].track_id == first[1].track_id
    assert swapped[1].track_id == first[0].track_id
    assert swapped[0].landmarks[0][0] == pytest.approx(right[0][0] + 1.0)
    assert swapped[1].landmarks[0][0] == pytest.approx(left[0][0] + 1.0)


def test_a_track_survives_a_short_detector_dropout_but_not_a_long_one() -> None:
    smoother = FaceLandmarkSmoother(alpha=0.5, max_gap=2)
    [first] = smoother.update([_BASE])
    smoother.update([])
    smoother.update([])  # two missed frames: still within the gap

    [resumed] = smoother.update([_shift(_BASE, 2.0, 0.0)])
    assert resumed.track_id == first.track_id and resumed.continued is True

    smoother.update([])
    smoother.update([])
    smoother.update([])  # three missed frames: the track is gone
    [fresh] = smoother.update([_shift(_BASE, 2.0, 0.0)])
    assert fresh.track_id != first.track_id and fresh.continued is False


def test_a_scene_cut_drops_every_track_even_when_the_face_is_in_the_same_place() -> None:
    smoother = FaceLandmarkSmoother(alpha=0.2)
    [first] = smoother.update([_BASE])

    [after_cut] = smoother.update([_shift(_BASE, 1.0, 0.0)], scene_cut=True)

    assert after_cut.continued is False
    assert after_cut.track_id != first.track_id
    assert after_cut.landmarks == _shift(_BASE, 1.0, 0.0)


@pytest.mark.parametrize("alpha", [0.0, -0.1, 1.5])
def test_alpha_must_be_in_the_open_closed_unit_interval(alpha: float) -> None:
    with pytest.raises(ValueError, match="alpha"):
        FaceLandmarkSmoother(alpha=alpha)


# --- scene cuts ---------------------------------------------------------------------------------


def test_scene_cut_detection_separates_a_cut_from_continuous_motion() -> None:
    dark = frame_signature(Image.new("RGB", (64, 48), (20, 20, 20)))
    slightly_brighter = frame_signature(Image.new("RGB", (64, 48), (30, 30, 30)))
    bright = frame_signature(Image.new("RGB", (64, 48), (230, 230, 230)))

    assert is_scene_cut(None, dark) is False  # nothing to compare with
    assert is_scene_cut(dark, slightly_brighter) is False
    assert is_scene_cut(dark, bright) is True


# --- restored-face (residual) smoothing ---------------------------------------------------------


np = pytest.importorskip("numpy")


def _crop(value: int = 100, size: int = 16):
    return np.full((size, size, 3), value, dtype=np.uint8)


def _restored_with_noise(cropped, rng, amplitude: int = 12):
    noise = rng.integers(-amplitude, amplitude + 1, size=cropped.shape)
    return np.clip(cropped.astype(np.int16) + noise, 0, 255).astype(np.uint8)


def test_the_first_restored_face_of_a_track_is_returned_unchanged() -> None:
    smoother = ResidualSmoother(alpha=0.5)
    rng = np.random.default_rng(1)
    cropped = _crop()
    restored = _restored_with_noise(cropped, rng)

    assert np.array_equal(smoother.blend(7, cropped, restored), restored)


def test_a_static_face_has_its_frame_to_frame_restoration_noise_reduced() -> None:
    rng = np.random.default_rng(5)
    cropped = _crop()
    raw = [_restored_with_noise(cropped, rng) for _ in range(40)]
    smoother = ResidualSmoother(alpha=0.5)

    blended = [smoother.blend(1, cropped, frame) for frame in raw]

    def flicker(frames):
        return float(
            np.mean(
                [
                    np.abs(a.astype(float) - b.astype(float)).mean()
                    for a, b in zip(frames[5:], frames[6:], strict=False)
                ]
            )
        )

    assert flicker(blended) < 0.75 * flicker(raw)


def test_fast_changes_in_the_face_are_not_ghosted_with_the_previous_residual() -> None:
    rng = np.random.default_rng(9)
    smoother = ResidualSmoother(alpha=0.5, motion_scale=24.0)
    first_crop = _crop(60)
    smoother.blend(2, first_crop, _restored_with_noise(first_crop, rng))
    changed = _crop(200)  # the aligned face content changed completely
    restored = _restored_with_noise(changed, rng)

    assert np.array_equal(smoother.blend(2, changed, restored), restored)


def test_tracks_do_not_share_history_and_forgotten_tracks_start_over() -> None:
    rng = np.random.default_rng(3)
    cropped = _crop()
    smoother = ResidualSmoother(alpha=0.5)
    smoother.blend(1, cropped, _restored_with_noise(cropped, rng))
    other = _restored_with_noise(cropped, rng)

    assert np.array_equal(smoother.blend(2, cropped, other), other)  # a new track: no history

    smoother.forget(1)
    again = _restored_with_noise(cropped, rng)
    assert np.array_equal(smoother.blend(1, cropped, again), again)


def test_alpha_one_disables_the_residual_smoothing() -> None:
    rng = np.random.default_rng(2)
    cropped = _crop()
    smoother = ResidualSmoother(alpha=1.0)
    smoother.blend(1, cropped, _restored_with_noise(cropped, rng))
    restored = _restored_with_noise(cropped, rng)

    assert np.array_equal(smoother.blend(1, cropped, restored), restored)


def test_blended_output_stays_a_valid_8_bit_image() -> None:
    cropped = _crop(250)
    smoother = ResidualSmoother(alpha=0.5)
    smoother.blend(1, cropped, np.full_like(cropped, 255))

    result = smoother.blend(1, cropped, np.full_like(cropped, 255))

    assert result.dtype == np.uint8 and int(result.max()) <= 255 and int(result.min()) >= 0


# --- the combined per-frame stabiliser ---------------------------------------------------------


def test_stabilizer_prunes_residual_history_of_tracks_that_ended() -> None:
    stabilizer = TemporalFaceStabilizer(max_gap=0)
    rng = np.random.default_rng(4)
    cropped = _crop()
    image = Image.new("RGB", (32, 32), "gray")

    stabilizer.begin_frame(image)
    [face] = stabilizer.track([_BASE])
    stabilizer.blend(face.track_id, cropped, _restored_with_noise(cropped, rng))
    stabilizer.begin_frame(image)
    stabilizer.track([])  # the face is gone and max_gap=0 ends the track

    assert stabilizer.residual_track_ids() == frozenset()


def test_stabilizer_report_describes_what_it_did() -> None:
    stabilizer = TemporalFaceStabilizer(landmark_alpha=0.4, residual_alpha=0.5)
    image = Image.new("RGB", (32, 32), "gray")
    for detections in ([_BASE], [_BASE], [], [_BASE]):
        stabilizer.begin_frame(image)
        stabilizer.track(detections)

    report = stabilizer.report()

    assert report == {
        "enabled": True,
        "landmark_alpha": 0.4,
        "residual_alpha": 0.5,
        "frames": 4,
        "frames_with_faces": 3,
        "face_observations": 3,
        "tracks_started": 1,
        "scene_cuts": 0,
    }
