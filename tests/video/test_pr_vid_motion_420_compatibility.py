"""PR-VID-MOTION-420 Workstream A: compatibility advisories are transparent, named and never block (pure)."""

from __future__ import annotations

import ast
import dataclasses
from pathlib import Path

import pytest

from src.video import motion_alignment_compatibility as compat
from src.video.motion_alignment import AlignmentIntent, FrameSize, Rect, resolve_alignment
from src.video.motion_alignment_compatibility import (
    BASIS_DERIVED,
    BASIS_OPERATOR,
    MediaFacts,
    SubjectObservations,
    assess_compatibility,
)

TARGET, DRIVER = FrameSize(480, 832), FrameSize(1080, 1920)
MEDIA = MediaFacts(
    target=TARGET,
    driver=DRIVER,
    source_original=(600, 900),
    driver_rate=30.0,
    driver_frame_count=90,
    window_start=5,
    window_end=60,
    output_frames=41,
    output_fps=24,
    held_frames=3,
)


def _codes(assessment) -> set[str]:
    return {advisory.code for advisory in assessment.advisories}


def _assess(source=None, driver=None, **kwargs):
    return assess_compatibility(
        source=source or SubjectObservations(),
        driver=driver or SubjectObservations(),
        media=kwargs.pop("media", MEDIA),
        **kwargs,
    )


def test_the_kinds_of_statement_are_kept_apart_and_nothing_is_a_score():
    source = SubjectObservations(kind="human", framing="upper_body", viewpoint="front", count=1)
    driver = SubjectObservations(kind="human", framing="full_body", viewpoint="front", count=1)
    assessment = _assess(
        source,
        driver,
        readiness_notes=("The clip is enlarged 1.8x.",),
        historical=("tested once [tested]",),
    )
    assert any("Target frame 480x832" in line for line in assessment.measured)
    assert (
        "The clip is enlarged 1.8x." in assessment.measured
    )  # an existing advisory is carried, not recomputed
    assert any("reported, not verified" in line for line in assessment.annotations)
    assert assessment.historical == ("tested once [tested]",)
    assert any("window starts at frame 5" in line for line in assessment.measured)
    assert any("last 3 repeat" in line for line in assessment.measured)
    # no probability, ranking or numeric verdict exists on the result
    fields = {f.name for f in dataclasses.fields(assessment)}
    assert not {"score", "probability", "rank", "verdict"} & fields
    assert assessment.blocking is False and compat.ADVISORY_ONLY is True


@pytest.mark.parametrize(
    ("source", "driver", "code", "severity", "basis"),
    [
        (
            SubjectObservations(framing="upper_body"),
            SubjectObservations(framing="full_body"),
            "framing_full_body_into_closeup",
            "caution",
            BASIS_OPERATOR,
        ),
        (
            SubjectObservations(framing="partial"),
            SubjectObservations(framing="full_body"),
            "framing_full_body_into_closeup",
            "caution",
            BASIS_OPERATOR,
        ),
        (
            SubjectObservations(framing="full_body"),
            SubjectObservations(framing="upper_body"),
            "framing_closeup_into_full_body",
            "note",
            BASIS_OPERATOR,
        ),
        (
            SubjectObservations(viewpoint="front"),
            SubjectObservations(viewpoint="side"),
            "viewpoint_mismatch",
            "caution",
            BASIS_OPERATOR,
        ),
        (
            SubjectObservations(viewpoint="front"),
            SubjectObservations(viewpoint="three_quarter"),
            "viewpoint_mismatch",
            "note",
            BASIS_OPERATOR,
        ),
        (
            SubjectObservations(start_pose="arms down"),
            SubjectObservations(start_pose="arms raised"),
            "start_pose_mismatch",
            "caution",
            BASIS_OPERATOR,
        ),
        (
            SubjectObservations(kind="human"),
            SubjectObservations(kind="nonhuman"),
            "subject_kind",
            "caution",
            BASIS_OPERATOR,
        ),
        (
            SubjectObservations(count=2),
            SubjectObservations(count=1),
            "multiple_subjects",
            "caution",
            BASIS_OPERATOR,
        ),
        (
            SubjectObservations(count=1),
            SubjectObservations(count=3),
            "multiple_subjects",
            "caution",
            BASIS_OPERATOR,
        ),
        (
            SubjectObservations(),
            SubjectObservations(camera_movement="tracking"),
            "camera_movement",
            "caution",
            BASIS_OPERATOR,
        ),
    ],
)
def test_each_reported_mismatch_gets_an_actionable_advisory_with_its_basis(
    source, driver, code, severity, basis
):
    found = {a.code: a for a in _assess(source, driver).advisories}
    assert code in found
    assert (found[code].severity, found[code].basis) == (severity, basis)
    assert found[code].message


def test_matching_or_unreported_subjects_raise_no_false_alarm_and_the_gaps_are_listed():
    same = SubjectObservations(
        kind="human",
        framing="full_body",
        viewpoint="front",
        start_pose="Arms Down",
        count=1,
        camera_movement="static",
        root_displacement="small",
    )
    other = dataclasses.replace(same, start_pose="arms  down")
    assessment = _assess(same, other)
    assert _codes(assessment) == set()  # equal after normalising case and spacing
    unknown = " ".join(_assess().unknown)
    for gap in (
        "Framing",
        "Viewpoint",
        "Starting poses",
        "camera movement",
        "Subject bounds",
        "Root displacement",
    ):
        assert gap in unknown, gap
    assert "has not been tested" in unknown  # the one thing no advisory can say is that it works


def test_scale_and_position_are_derived_from_entered_bounds_with_named_thresholds():
    # the driving subject is the whole 1920-high frame (832 px in the target); the source subject is 300 px high
    driver = SubjectObservations(bounds=Rect(300.0, 100.0, 800.0, 1800.0))
    source = SubjectObservations(bounds=Rect(40.0, 300.0, 140.0, 600.0))
    assessment = _assess(source, driver)
    found = {a.code: a for a in assessment.advisories}
    assert found["scale_mismatch"].basis == BASIS_DERIVED
    assert (
        found["scale_mismatch"].threshold == f"SCALE_RATIO_ADVISORY={compat.SCALE_RATIO_ADVISORY:g}"
    )
    assert float(found["scale_mismatch"].observed) > compat.SCALE_RATIO_ADVISORY
    assert found["position_mismatch"].threshold.startswith("POSITION_OFFSET_ADVISORY_FRACTION")
    assert any("before alignment" in line for line in assessment.derived)


def test_a_matching_scale_and_position_are_not_flagged_and_the_alignment_effect_is_stated():
    cover = compat.baseline_scale(DRIVER, TARGET)
    left = (TARGET.width - DRIVER.width * cover) / 2
    top = (TARGET.height - DRIVER.height * cover) / 2
    box = Rect(540.0 - 100, 700.0, 540.0 + 100, 1200.0)  # driver pixels
    x0, y0 = left + box.left * cover, top + box.top * cover
    x1, y1 = left + box.right * cover, top + box.bottom * cover
    source = SubjectObservations(bounds=Rect(x0, y0, x1, y1))
    plain = _assess(source, SubjectObservations(bounds=box))
    assert "scale_mismatch" not in _codes(plain) and "position_mismatch" not in _codes(plain)
    aligned = resolve_alignment(
        AlignmentIntent(scale=1.0, translate_x=60.0), driver=DRIVER, target=TARGET
    )
    after = _assess(source, SubjectObservations(bounds=box), alignment=aligned)
    assert any("After the current alignment" in line for line in after.derived)


@pytest.mark.parametrize(
    ("ratio", "flagged"), [(1.49, False), (1.5, True), (1.0 / 1.5, True), (1.2, False)]
)
def test_the_scale_threshold_is_inclusive_in_both_directions(ratio, flagged):
    cover = compat.baseline_scale(DRIVER, TARGET)
    top = (TARGET.height - DRIVER.height * cover) / 2
    height_px = 200.0
    driver_height = height_px * ratio / cover
    driver = SubjectObservations(bounds=Rect(500.0, 800.0, 600.0, 800.0 + driver_height))
    source = SubjectObservations(bounds=Rect(100.0, top, 200.0, top + height_px))
    assert ("scale_mismatch" in _codes(_assess(source, driver))) is flagged


def test_alignment_dependent_advisories_name_clipping_cropping_and_fill():
    cropped = resolve_alignment(
        AlignmentIntent(scale=1.0, translate_x=200.0), driver=DRIVER, target=TARGET
    )
    codes = _codes(_assess(alignment=cropped))
    assert "driver_cropped" in codes  # most of the driving frame left the target
    small = resolve_alignment(AlignmentIntent(scale=0.4), driver=DRIVER, target=TARGET)
    advisories = {a.code: a for a in _assess(alignment=small).advisories}
    assert (
        advisories["border_fill"].severity == "note"
        and "edge-based conditioning" in advisories["border_fill"].message
    )
    near_edge = resolve_alignment(AlignmentIntent(scale=1.0), driver=DRIVER, target=TARGET)
    risky = _assess(
        driver=SubjectObservations(bounds=Rect(1000.0, 800.0, 1075.0, 1200.0)), alignment=near_edge
    )
    assert "subject_clipping_risk" in _codes(risky)
    centred = _assess(
        driver=SubjectObservations(bounds=Rect(400.0, 800.0, 700.0, 1200.0)), alignment=near_edge
    )
    assert "subject_clipping_risk" not in _codes(centred)


def test_a_large_root_displacement_with_a_wide_source_subject_warns_about_space():
    driver = SubjectObservations(root_displacement="large")
    wide = SubjectObservations(bounds=Rect(40.0, 100.0, 440.0, 700.0))  # 83% of the frame width
    narrow = SubjectObservations(bounds=Rect(200.0, 100.0, 300.0, 700.0))
    assert "insufficient_space" in _codes(_assess(wide, driver))
    assert "insufficient_space" not in _codes(_assess(narrow, driver))
    assert "insufficient_space" not in _codes(
        _assess(wide, SubjectObservations(root_displacement="small"))
    )


def test_the_module_reads_nothing_and_blocks_nothing():
    tree = ast.parse(Path(compat.__file__).read_text(encoding="utf-8"))
    imported = {n.module or "" for n in ast.walk(tree) if isinstance(n, ast.ImportFrom)}
    assert not any(
        name.startswith(("src.gui", "src.queue", "src.controller", "src.pipeline"))
        for name in imported
    )
    text = Path(compat.__file__).read_text(encoding="utf-8")
    assert (
        "open(" not in text and "subprocess" not in text and "raise " not in text
    )  # advisory: it never refuses
