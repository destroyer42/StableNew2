"""PR-VID-MOTION-420: the alignment contract, its mathematics and the anchor fit (pure; no FFmpeg).

Positions are asserted against hand-computed values and against pixels of synthetic frames, never against the
module's own output alone.
"""

from __future__ import annotations

import copy
import json
import math

import numpy as np
import pytest
from PIL import Image, ImageDraw

from src.video import motion_alignment as ma
from src.video.motion_alignment import (
    IDENTITY,
    AlignmentError,
    AlignmentIntent,
    AnchorPair,
    FrameSize,
    Rect,
    alignment_from_record,
    baseline_scale,
    fit_anchors,
    inspect_envelope,
    intent_from_frame_region,
    resolve_alignment,
    transform_frame,
)

PORTRAIT = FrameSize(480, 832)
LANDSCAPE = FrameSize(832, 480)
SQUARE_DRIVER = FrameSize(500, 500)


def _frame(size: FrameSize, box: tuple[int, int, int, int]) -> Image.Image:
    image = Image.new("RGB", (size.width, size.height), (10, 10, 10))
    ImageDraw.Draw(image).rectangle([box[0], box[1], box[2] - 1, box[3] - 1], fill=(250, 250, 250))
    return image


def _centroid(image: Image.Image) -> tuple[float, float]:
    array = np.asarray(image)
    ys, xs = np.where(array.min(axis=2) > 200)
    return float(xs.mean()) + 0.5, float(ys.mean()) + 0.5


# ------------------------------------------------------------------------------ resolution


def test_identity_is_the_workflows_own_cover_placement():
    driver = FrameSize(1080, 1920)
    resolved = resolve_alignment(IDENTITY, driver=driver, target=PORTRAIT)
    cover = baseline_scale(driver, PORTRAIT)
    assert cover == pytest.approx(
        480 / 1080
    )  # the wider ratio wins: the width exactly fills the frame
    assert resolved.placement.width == pytest.approx(480.0)
    assert resolved.placement.left == pytest.approx(0.0)
    assert resolved.destination == (0, 0, 480, 832)
    assert resolved.fill_fraction == 0.0
    # The visible source box is exactly the centred cover crop (Pillow ImageOps.fit's rectangle).
    from src.video.workflow_source_preparation import cover_crop_box

    expected = cover_crop_box((1080, 1920), (480, 832))
    assert resolved.source_box == pytest.approx(expected, abs=1e-6)


@pytest.mark.parametrize(
    ("driver", "target"),
    [
        (FrameSize(1080, 1920), PORTRAIT),
        (FrameSize(1920, 1080), PORTRAIT),
        (FrameSize(1920, 1080), LANDSCAPE),
        (FrameSize(640, 480), LANDSCAPE),
        (SQUARE_DRIVER, PORTRAIT),
        (SQUARE_DRIVER, LANDSCAPE),
    ],
)
def test_baseline_always_covers_the_target_and_is_centred(driver, target):
    resolved = resolve_alignment(IDENTITY, driver=driver, target=target)
    centre = resolved.to_target((driver.width / 2, driver.height / 2))
    assert centre == pytest.approx((target.width / 2, target.height / 2))
    assert resolved.fill_fraction == pytest.approx(0.0, abs=1e-9)
    assert resolved.placement.left <= 1e-6 and resolved.placement.top <= 1e-6


def test_translation_moves_the_placement_by_exactly_that_many_target_pixels():
    base = resolve_alignment(IDENTITY, driver=SQUARE_DRIVER, target=LANDSCAPE)
    moved = resolve_alignment(
        AlignmentIntent(translate_x=-40.5, translate_y=12.25),
        driver=SQUARE_DRIVER,
        target=LANDSCAPE,
    )
    assert moved.placement.left - base.placement.left == pytest.approx(-40.5)
    assert moved.placement.top - base.placement.top == pytest.approx(12.25)
    assert moved.placement.width == pytest.approx(base.placement.width)


def test_uniform_scale_is_about_the_target_centre():
    driver = FrameSize(300, 600)
    base = resolve_alignment(IDENTITY, driver=driver, target=PORTRAIT)
    half = resolve_alignment(AlignmentIntent(scale=0.5), driver=driver, target=PORTRAIT)
    assert half.placement.width == pytest.approx(base.placement.width / 2)
    assert half.placement.height == pytest.approx(base.placement.height / 2)
    assert half.placement.center == pytest.approx(base.placement.center)
    # The same factor in both axes: a uniform scale, never an independent width/height change.
    assert half.placement.width / half.placement.height == pytest.approx(
        base.placement.width / base.placement.height
    )
    # aligned = scale * original + translation, about the centre
    point = (75.0, 150.0)
    before, after = base.to_target(point), half.to_target(point)
    centre = (PORTRAIT.width / 2, PORTRAIT.height / 2)
    assert after[0] - centre[0] == pytest.approx(0.5 * (before[0] - centre[0]))
    assert after[1] - centre[1] == pytest.approx(0.5 * (before[1] - centre[1]))


def test_transform_order_is_baseline_then_mirror_then_scale_then_translation():
    driver = FrameSize(200, 400)
    intent = AlignmentIntent(scale=1.5, translate_x=20, translate_y=-30, mirror=True)
    resolved = resolve_alignment(intent, driver=driver, target=PORTRAIT)
    cover = baseline_scale(driver, PORTRAIT)
    point = (50.0, 100.0)
    # step 1 baseline, step 2 mirror about the target centre, step 3 scale about it, step 4 translate
    bx = (PORTRAIT.width - driver.width * cover) / 2 + point[0] * cover
    by = (PORTRAIT.height - driver.height * cover) / 2 + point[1] * cover
    cx, cy = PORTRAIT.width / 2, PORTRAIT.height / 2
    mx = PORTRAIT.width - bx
    expected = (cx + 1.5 * (mx - cx) + 20, cy + 1.5 * (by - cy) - 30)
    assert resolved.to_target(point) == pytest.approx(expected)
    assert resolved.to_driver(expected) == pytest.approx(point)


def test_mirroring_reverses_horizontal_motion_and_nothing_else():
    driver = FrameSize(200, 400)
    plain = resolve_alignment(IDENTITY, driver=driver, target=PORTRAIT)
    mirrored = resolve_alignment(AlignmentIntent(mirror=True), driver=driver, target=PORTRAIT)
    assert mirrored.placement == plain.placement  # the rectangle is symmetric: it does not move
    left, right = (20.0, 200.0), (120.0, 200.0)
    dx_plain = plain.to_target(right)[0] - plain.to_target(left)[0]
    dx_mirror = mirrored.to_target(right)[0] - mirrored.to_target(left)[0]
    assert dx_mirror == pytest.approx(-dx_plain)
    assert mirrored.to_target(left)[1] == pytest.approx(plain.to_target(left)[1])


def test_resolved_values_are_rounded_to_the_stated_precision_and_both_are_recorded():
    resolved = resolve_alignment(
        AlignmentIntent(scale=1.123456789, translate_x=3.14159, translate_y=-2.71828),
        driver=SQUARE_DRIVER,
        target=PORTRAIT,
    )
    assert resolved.intent.scale == 1.1235
    assert (resolved.intent.translate_x, resolved.intent.translate_y) == (3.14, -2.72)
    assert (
        resolved.requested["scale"] == 1.123456789
    )  # what was asked is kept beside what was resolved
    assert resolved.to_record()["requested"]["translate_x"] == 3.14159


@pytest.mark.parametrize(
    ("kwargs", "code"),
    [
        ({"scale": 0.1}, "scale_out_of_range"),
        ({"scale": 4.5}, "scale_out_of_range"),
        ({"scale": float("nan")}, "invalid_value"),
        ({"scale": float("inf")}, "invalid_value"),
        ({"translate_x": float("-inf")}, "invalid_value"),
        ({"translate_y": float("nan")}, "invalid_value"),
        ({"scale": True}, "invalid_value"),
        ({"scale": "1.0"}, "invalid_value"),
        ({"translate_x": 481.0}, "translation_out_of_range"),
        ({"translate_y": -833.0}, "translation_out_of_range"),
        ({"mirror": 1}, "invalid_value"),
        ({"origin": "guess"}, "invalid_value"),
    ],
)
def test_unsupported_values_are_refused_never_clamped(kwargs, code):
    with pytest.raises(AlignmentError) as raised:
        resolve_alignment(AlignmentIntent(**kwargs), driver=SQUARE_DRIVER, target=PORTRAIT)
    assert raised.value.code == code


def test_a_placement_that_leaves_the_frame_is_refused_not_resolved_to_nothing():
    driver = FrameSize(100, 100)
    # scale 0.25 of a 480-wide cover is 120 px; moving it a whole frame away leaves no overlap.
    with pytest.raises(AlignmentError) as raised:
        resolve_alignment(
            AlignmentIntent(scale=0.25, translate_x=480.0, translate_y=0.0),
            driver=driver,
            target=PORTRAIT,
        )
    assert raised.value.code == "no_overlap"


@pytest.mark.parametrize("bad", [FrameSize(1, 100), FrameSize(100, 0), FrameSize(20000, 100)])
def test_unsupported_geometry_is_refused(bad):
    with pytest.raises(AlignmentError) as raised:
        resolve_alignment(IDENTITY, driver=bad, target=PORTRAIT)
    assert raised.value.code == "unsupported_geometry"


def test_boundary_report_names_clipped_edges_and_fill():
    driver = FrameSize(200, 400)
    resolved = resolve_alignment(
        AlignmentIntent(scale=0.5, translate_x=150.0), driver=driver, target=PORTRAIT
    )
    assert resolved.clipped["right"] is True and resolved.clipped["left"] is False
    assert 0.0 < resolved.fill_fraction < 1.0
    assert resolved.driver_visible_fraction < 1.0
    record = resolved.to_record()
    assert record["fill"] == {"policy": "constant_gray_128", "rgb": [128, 128, 128]}
    assert record["resampling"] == "lanczos"


# ------------------------------------------------------------------------------ pixels


def test_transform_frame_places_a_known_subject_where_the_mathematics_says():
    driver = FrameSize(300, 600)
    frame = _frame(driver, (100, 200, 140, 260))  # centre (120, 230)
    intent = AlignmentIntent(scale=0.7, translate_x=-25.0, translate_y=40.0)
    resolved = resolve_alignment(intent, driver=driver, target=PORTRAIT)
    out = transform_frame(frame, resolved)
    assert out.size == (480, 832) and out.mode == "RGB"
    got = _centroid(out)
    want = resolved.to_target((120.0, 230.0))
    assert got[0] == pytest.approx(want[0], abs=0.75) and got[1] == pytest.approx(want[1], abs=0.75)


def test_uncovered_target_pixels_take_the_declared_constant_fill():
    driver = FrameSize(300, 600)
    resolved = resolve_alignment(AlignmentIntent(scale=0.5), driver=driver, target=PORTRAIT)
    out = np.asarray(transform_frame(_frame(driver, (0, 0, 300, 600)), resolved))
    x0, y0, x1, y1 = resolved.destination
    assert (out[:y0] == 128).all() and (out[y1:] == 128).all()
    assert (out[:, :x0] == 128).all() and (out[:, x1:] == 128).all()
    assert out[(y0 + y1) // 2, (x0 + x1) // 2].min() > 200  # the driver's own pixels inside


def test_mirror_flips_the_pixels_to_the_other_side_of_the_frame():
    driver = FrameSize(300, 600)
    frame = _frame(driver, (30, 280, 70, 320))
    plain = transform_frame(frame, resolve_alignment(IDENTITY, driver=driver, target=PORTRAIT))
    flipped = transform_frame(
        frame, resolve_alignment(AlignmentIntent(mirror=True), driver=driver, target=PORTRAIT)
    )
    px, py = _centroid(plain)
    fx, fy = _centroid(flipped)
    assert fx == pytest.approx(PORTRAIT.width - px, abs=1.0)
    assert fy == pytest.approx(py, abs=1.0)


def test_a_frame_of_the_wrong_size_is_refused_not_silently_resized():
    resolved = resolve_alignment(IDENTITY, driver=FrameSize(300, 600), target=PORTRAIT)
    with pytest.raises(AlignmentError):
        transform_frame(Image.new("RGB", (301, 600)), resolved)


def test_the_same_constant_transform_applies_to_every_frame_of_a_moving_subject():
    driver = FrameSize(300, 600)
    resolved = resolve_alignment(
        AlignmentIntent(scale=0.8, translate_x=14.0, translate_y=-9.0),
        driver=driver,
        target=PORTRAIT,
    )
    positions = [(60 + 10 * t, 200 + 4 * t) for t in range(0, 20, 3)]
    outs = [
        _centroid(transform_frame(_frame(driver, (x - 12, y - 12, x + 12, y + 12)), resolved))
        for x, y in positions
    ]
    scale = resolved.effective_scale
    for earlier, later, (x0, y0), (x1, y1) in zip(
        outs, outs[1:], positions, positions[1:], strict=False
    ):
        # displacement scales by exactly the effective scale and never gains a per-frame correction
        assert later[0] - earlier[0] == pytest.approx((x1 - x0) * scale, abs=1.0)
        assert later[1] - earlier[1] == pytest.approx((y1 - y0) * scale, abs=1.0)


# ------------------------------------------------------------------------------ record


def test_a_record_round_trips_and_a_hand_edit_is_detected():
    driver = FrameSize(1080, 1920)
    resolved = resolve_alignment(
        AlignmentIntent(scale=1.1, translate_x=8.0, translate_y=-12.0, mirror=True),
        driver=driver,
        target=PORTRAIT,
    )
    record = json.loads(json.dumps(resolved.to_record()))
    assert alignment_from_record(record).transform_sha256 == resolved.transform_sha256
    for key, value in (("scale", 1.2), ("translate_x", 9.0), ("mirror", False)):
        edited = copy.deepcopy(record)
        edited[key] = value
        with pytest.raises(AlignmentError):
            alignment_from_record(edited)
    edited = copy.deepcopy(record)
    edited["source_box"] = [record["source_box"][0] + 1.0, *record["source_box"][1:]]
    with pytest.raises(AlignmentError) as raised:
        alignment_from_record(edited)
    assert raised.value.code == "record_mismatch"
    edited = copy.deepcopy(record)
    edited["transform_version"] = "stablenew.alignment-transform.v0"
    with pytest.raises(AlignmentError) as raised:
        alignment_from_record(edited)
    assert raised.value.code == "unsupported_version"


def test_the_transform_digest_depends_on_the_geometry_not_on_how_the_numbers_were_chosen():
    driver = FrameSize(300, 600)
    manual = resolve_alignment(
        AlignmentIntent(scale=0.9, translate_x=5.0), driver=driver, target=PORTRAIT
    )
    fitted = resolve_alignment(
        AlignmentIntent(scale=0.9, translate_x=5.0, origin="anchor_fit"),
        driver=driver,
        target=PORTRAIT,
    )
    other = resolve_alignment(
        AlignmentIntent(scale=0.9, translate_x=6.0), driver=driver, target=PORTRAIT
    )
    assert manual.transform_sha256 == fitted.transform_sha256 != other.transform_sha256


# ------------------------------------------------------------------------------ anchors


def _anchors_for(intent: AlignmentIntent, driver: FrameSize, target: FrameSize, points, kinds=None):
    truth = resolve_alignment(intent, driver=driver, target=target)
    kinds = kinds or ["head", "hip_center", "feet", "other"]
    return [AnchorPair(kinds[i % len(kinds)], truth.to_target(p), p) for i, p in enumerate(points)]


def test_a_known_correspondence_set_recovers_the_known_transform():
    driver = FrameSize(1080, 1920)
    truth = AlignmentIntent(scale=1.2, translate_x=-18.0, translate_y=24.0)
    anchors = _anchors_for(truth, driver, PORTRAIT, [(540, 400), (540, 1000), (500, 1500)])
    fit = fit_anchors(anchors, driver=driver, target=PORTRAIT)
    assert fit.status == ma.FIT_OK and fit.proposed
    assert fit.intent.scale == pytest.approx(1.2, abs=1e-3)
    assert fit.intent.translate_x == pytest.approx(-18.0, abs=0.02)
    assert fit.intent.translate_y == pytest.approx(24.0, abs=0.02)
    assert fit.rms_error < 0.05 and fit.max_error < 0.05
    assert fit.intent.origin == ma.ORIGIN_ANCHOR_FIT and len(fit.intent.anchors) == 3
    assert fit.intent.fit["method"] == "least_squares_uniform_scale_translation"


def test_the_fit_is_deterministic_and_order_independent():
    driver = FrameSize(1080, 1920)
    anchors = _anchors_for(
        AlignmentIntent(scale=0.85, translate_x=30.0),
        driver,
        PORTRAIT,
        [(300, 300), (800, 1500), (540, 900)],
    )
    first = fit_anchors(anchors, driver=driver, target=PORTRAIT)
    again = fit_anchors(anchors, driver=driver, target=PORTRAIT)
    shuffled = fit_anchors(list(reversed(anchors)), driver=driver, target=PORTRAIT)
    assert (first.intent.scale, first.intent.translate_x, first.intent.translate_y) == (
        again.intent.scale,
        again.intent.translate_x,
        again.intent.translate_y,
    )
    assert shuffled.intent.scale == pytest.approx(first.intent.scale, abs=1e-4)
    assert shuffled.intent.translate_x == pytest.approx(first.intent.translate_x, abs=0.01)


def test_the_fit_respects_an_explicit_mirror():
    driver = FrameSize(1080, 1920)
    truth = AlignmentIntent(scale=1.1, translate_x=10.0, mirror=True)
    anchors = _anchors_for(truth, driver, PORTRAIT, [(300, 400), (700, 1500)])
    fit = fit_anchors(anchors, driver=driver, target=PORTRAIT, mirror=True)
    assert fit.intent.mirror is True and fit.intent.scale == pytest.approx(1.1, abs=1e-3)
    assert fit.rms_error < 0.05


def test_one_pair_fixes_only_the_position_and_says_so():
    driver = FrameSize(1080, 1920)
    anchors = [AnchorPair("head", (300.0, 200.0), (540.0, 400.0))]
    fit = fit_anchors(anchors, driver=driver, target=PORTRAIT)
    assert fit.proposed and fit.intent.scale == 1.0
    assert any(issue.code == "translation_only" for issue in fit.issues)
    mapped = resolve_alignment(fit.intent, driver=driver, target=PORTRAIT).to_target((540.0, 400.0))
    assert mapped == pytest.approx((300.0, 200.0), abs=0.02)


def test_no_anchors_and_degenerate_anchors_are_refused_with_a_reason():
    driver = FrameSize(1080, 1920)
    empty = fit_anchors([], driver=driver, target=PORTRAIT)
    assert empty.status == ma.FIT_REFUSED and not empty.proposed
    assert empty.issues[0].code == "insufficient_anchors" and empty.issues[0].blocking
    coincident = fit_anchors(
        [
            AnchorPair("head", (240.0, 200.0), (540.0, 400.0)),
            AnchorPair("feet", (241.0, 201.0), (541.0, 401.0)),
        ],
        driver=driver,
        target=PORTRAIT,
    )
    assert coincident.status == ma.FIT_REFUSED
    assert coincident.issues[0].code == "degenerate_anchors"


@pytest.mark.parametrize(
    "anchor",
    [
        AnchorPair("tail", (240.0, 200.0), (540.0, 400.0)),
        AnchorPair("head", (float("nan"), 200.0), (540.0, 400.0)),
        AnchorPair("head", (240.0, 200.0), (540.0, float("inf"))),
        AnchorPair("head", (-5.0, 200.0), (540.0, 400.0)),
        AnchorPair("head", (240.0, 900.0), (540.0, 400.0)),
        AnchorPair("head", (240.0, 200.0), (1200.0, 400.0)),
    ],
)
def test_missing_or_invalid_points_are_refused(anchor):
    fit = fit_anchors(
        [anchor, AnchorPair("feet", (240.0, 700.0), (540.0, 1500.0))],
        driver=FrameSize(1080, 1920),
        target=PORTRAIT,
    )
    assert fit.status == ma.FIT_REFUSED and fit.issues[0].code == "invalid_anchor"


def test_too_many_anchor_pairs_are_refused():
    many = [
        AnchorPair("other", (240.0, 100.0 + i), (540.0, 100.0 + i))
        for i in range(ma.MAX_ANCHORS + 1)
    ]
    assert fit_anchors(many, driver=FrameSize(1080, 1920), target=PORTRAIT).status == ma.FIT_REFUSED


def test_conflicting_scale_estimates_are_reported_and_the_error_is_shown():
    driver = FrameSize(1080, 1920)
    # The two lower points imply a much larger scale than the pair involving the head.
    anchors = [
        AnchorPair("head", (240.0, 200.0), (540.0, 400.0)),
        AnchorPair("hip_center", (240.0, 300.0), (540.0, 1000.0)),
        AnchorPair("feet", (240.0, 700.0), (540.0, 1100.0)),
    ]
    fit = fit_anchors(anchors, driver=driver, target=PORTRAIT)
    assert fit.proposed and fit.status == ma.FIT_WARNING
    codes = {issue.code for issue in fit.issues}
    assert "conflicting_scale" in codes
    assert fit.rms_error > 0 and len(fit.residuals) == 3 and max(fit.residuals) == fit.max_error
    assert all(not issue.blocking for issue in fit.issues)  # the operator may adjust or discard


def test_an_implausible_fitted_scale_is_refused():
    anchors = [
        AnchorPair("head", (240.0, 200.0), (540.0, 400.0)),
        AnchorPair("feet", (240.0, 700.0), (540.0, 410.0 + 0.0)),
    ]
    # driver anchors only 10 px apart after mapping -> degenerate before the scale is even considered
    assert (
        fit_anchors(anchors, driver=FrameSize(1080, 1920), target=PORTRAIT).status == ma.FIT_REFUSED
    )


def test_a_suggestion_changes_nothing_until_it_is_applied():
    driver = FrameSize(1080, 1920)
    anchors = _anchors_for(AlignmentIntent(scale=1.1), driver, PORTRAIT, [(300, 300), (800, 1500)])
    fit = fit_anchors(anchors, driver=driver, target=PORTRAIT)
    # fitting returns a proposal object only; the identity transform is untouched
    assert IDENTITY == AlignmentIntent()
    assert fit.intent is not IDENTITY and fit.intent != IDENTITY


# ------------------------------------------------------------------------------ crop / reframing


def test_a_frame_region_expresses_the_same_constant_transform_as_a_crop():
    driver = FrameSize(1080, 1920)
    region = Rect(270.0, 480.0, 810.0, 1440.0)  # 540x960, centred
    intent = intent_from_frame_region(region, driver=driver, target=PORTRAIT)
    resolved = resolve_alignment(intent, driver=driver, target=PORTRAIT)
    assert intent.origin == ma.ORIGIN_FRAME_REGION and intent.frame_region == region
    # the region's centre sits on the target's centre and the region just covers the frame
    assert resolved.to_target(region.center) == pytest.approx((240.0, 416.0), abs=0.05)
    tl, br = (
        resolved.to_target((region.left, region.top)),
        resolved.to_target((region.right, region.bottom)),
    )
    assert tl[0] <= 0.05 and tl[1] <= 0.05 and br[0] >= 479.9 and br[1] >= 831.9
    assert resolved.placement.width > 480


def test_a_region_outside_the_driver_or_empty_is_refused():
    driver = FrameSize(1080, 1920)
    with pytest.raises(AlignmentError):
        intent_from_frame_region(Rect(-1.0, 0.0, 500.0, 500.0), driver=driver, target=PORTRAIT)
    with pytest.raises(AlignmentError):
        intent_from_frame_region(Rect(100.0, 100.0, 100.0, 300.0), driver=driver, target=PORTRAIT)


# ------------------------------------------------------------------------------ envelope


def test_envelope_maps_only_entered_bounds_and_never_claims_the_whole_window():
    driver = FrameSize(1080, 1920)
    resolved = resolve_alignment(
        AlignmentIntent(scale=1.0, translate_x=200.0), driver=driver, target=PORTRAIT
    )
    inside = Rect(400.0, 300.0, 600.0, 700.0)
    near_edge = Rect(900.0, 300.0, 1060.0, 700.0)
    report = inspect_envelope(resolved, {0: inside, 40: near_edge}, total_frames=41)
    assert report.sampled == 2 and not report.whole_window_verified
    assert report.frames[0].fully_visible and not report.frames[1].fully_visible
    assert "right" in report.frames[1].clipped_sides
    assert report.all_sampled_visible is False
    assert "2 sampled frame(s) of 41" in report.statement
    only_inside = inspect_envelope(resolved, {0: inside, 20: inside}, total_frames=41)
    assert only_inside.all_sampled_visible and "not inspected" in only_inside.statement
    assert "No subject bounds" in inspect_envelope(resolved, {}, total_frames=41).statement


def test_envelope_is_verified_for_the_whole_window_only_when_every_frame_is_covered():
    driver = FrameSize(1080, 1920)
    resolved = resolve_alignment(IDENTITY, driver=driver, target=PORTRAIT)
    bounds = {i: Rect(400.0, 300.0, 600.0, 700.0) for i in range(5)}
    report = inspect_envelope(resolved, bounds, total_frames=5)
    assert report.whole_window_verified and "all 5 frames" in report.statement


def test_module_has_no_side_effect_imports():
    import src.video.motion_alignment as module

    source = open(module.__file__, encoding="utf-8").read()
    for forbidden in (
        "subprocess",
        "src.gui",
        "src.queue",
        "src.controller",
        "src.pipeline",
        "open(",
    ):
        assert forbidden not in source
    assert math.isfinite(ma.MAX_SCALE)
