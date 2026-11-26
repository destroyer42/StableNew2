"""PR-VID-MOTION-430 Workstreams C and D: effective-driver inspection and engine compatibility, without a runtime or a worker."""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from src.gui.view_contracts.video_motion_prep_contract import (
    BLOCKED_FIELD,
    PREPARED_FIELD,
    STATE_READY,
    MotionPreparationSession,
    PrepInputs,
)
from src.video.conditioning_advisories import ConditioningAdvisory
from src.video.conditioning_inspection import (
    KIND_ALIGNED,
    KIND_ORIGINAL,
    KIND_PREPARED,
    asset_representation,
    build_inspection_context,
    context_notes,
    effective_driver,
    engine_rows,
    preview_notes,
    shared_length_note,
    target_size_for,
)
from src.video.workflow_catalog import build_builtin_workflow_specs
from src.video.workflow_conditioning import (
    conditioning_contract,
    conditioning_lines,
    conditioning_projection,
)
from src.video.workflow_motion_guidance import motion_readiness_projection
from src.video.workflow_registry import build_default_workflow_registry

FUN = "wan22_fun_control_5b_canny_i2v_v1"
ANIMATE = "wan_animate2_drive_i2v_v1"
ORIGINAL = "o" * 64


def _spec(workflow_id, version):
    return build_default_workflow_registry().get(workflow_id, version, allow_experimental=True)


def _prepared(workflow_id, version, frames, *, aligned=False, original=ORIGINAL):
    record = {
        "schema": "stablenew.aligned-motion-source.v1" if aligned else "stablenew.motion-source.v1",
        "original": {"path": "/lib/o.mp4", "sha256": original},
        "derived": {"path": "/prep/d.mp4", "sha256": "d" * 64, "frames": frames},
        "contract": {
            "workflow_id": workflow_id,
            "workflow_version": version,
            "output_frames": frames,
        },
    }
    return record


def _asset(profile="", width=480, height=832, viewpoint="front"):
    derivation = SimpleNamespace(profile=profile) if profile else None
    return SimpleNamespace(
        sha256=ORIGINAL, derivation=derivation, width=width, height=height, viewpoint=viewpoint
    )


# ----------------------------------------------------------------------------------------------- effective driver


def test_without_a_preparation_the_original_clip_is_inspected():
    fun = conditioning_contract(_spec(FUN, "1.1.0"))
    driver = effective_driver(None, fun, 33, original_path="/lib/o.mp4", original_sha256=ORIGINAL)
    assert (driver.kind, driver.path, driver.stale_reason) == (KIND_ORIGINAL, "/lib/o.mp4", "")


def test_a_matching_preparation_is_the_effective_input_and_an_aligned_one_is_labelled_so():
    fun = conditioning_contract(_spec(FUN, "1.1.0"))
    prepared = effective_driver(
        _prepared(FUN, "1.1.0", 33), fun, 33, original_path="/lib/o.mp4", original_sha256=ORIGINAL
    )
    assert (prepared.kind, prepared.path, prepared.frames) == (KIND_PREPARED, "/prep/d.mp4", 33)
    aligned_record = _prepared(FUN, "1.1.0", 33, aligned=True)
    from src.video.motion_alignment_preparation import ALIGNED_SCHEMA

    aligned_record["schema"] = ALIGNED_SCHEMA
    aligned = effective_driver(
        aligned_record, fun, 33, original_path="/lib/o.mp4", original_sha256=ORIGINAL
    )
    assert aligned.kind == KIND_ALIGNED and aligned.derived_from_sha256 == ORIGINAL


@pytest.mark.parametrize(
    ("prepared", "frames", "expected"),
    [
        (_prepared(ANIMATE, "1.2.0", 33), 33, "not wan22_fun_control"),
        (_prepared(FUN, "1.0.0", 33), 33, "1.0.0"),
        (_prepared(FUN, "1.1.0", 49), 33, "49 frames"),
        (_prepared(FUN, "1.1.0", 33, original="x" * 64), 33, "different driving clip"),
    ],
)
def test_a_preparation_for_another_engine_version_length_or_clip_is_never_the_effective_input(
    prepared, frames, expected
):
    fun = conditioning_contract(_spec(FUN, "1.1.0"))
    driver = effective_driver(
        prepared, fun, frames, original_path="/lib/o.mp4", original_sha256=ORIGINAL
    )
    assert driver.kind == KIND_ORIGINAL and driver.path == "/lib/o.mp4"
    assert expected in driver.stale_reason


def test_the_inspection_context_states_representation_geometry_and_engine():
    spec = _spec(FUN, "1.1.0")
    context = build_inspection_context(
        spec, _asset("skeleton_reference"), "/lib/o.mp4", None, frame_count=33
    )
    assert context.representation == "rendered_skeleton"
    assert context.target_size == (480, 832) and context.generation_frames == 33
    assert "Fun Control" in context.heading or "wan22_fun" in context.heading.lower()
    wide = build_inspection_context(
        spec, _asset(width=1280, height=720), "/m.mp4", None, frame_count=17
    )
    assert wide.target_size == (832, 480)
    assert asset_representation(_asset()) == "rgb_footage"
    assert (
        build_inspection_context(
            _spec("wan22_ti2v_5b_i2v_v1", "1.3.0"), _asset(), "/m.mp4", None, frame_count=17
        )
        is None
    )
    assert target_size_for(conditioning_contract(spec), None, None) == (480, 832)


def test_context_notes_carry_the_engine_answer_and_the_stale_reason_with_their_basis():
    fun = _spec(FUN, "1.1.0")
    context = build_inspection_context(
        fun,
        _asset("high_contrast_silhouette"),
        "/lib/o.mp4",
        _prepared(ANIMATE, "1.2.0", 33),
        frame_count=33,
    )
    notes = {n.code: n for n in context_notes(context)}
    assert notes["engine_representation"].text.startswith("Accepted:")
    assert "not an externally computed edge tensor" in notes["engine_representation"].text
    assert notes["stale_preparation"].basis == "measured"
    refused = build_inspection_context(
        _spec(FUN, "1.0.0"), _asset(), "/m.mp4", None, frame_count=17
    )
    assert "workflow_refused" in {n.code for n in context_notes(refused)}


def test_preview_notes_separate_exact_from_approximate_and_tag_every_advisory():
    preview = SimpleNamespace(
        fidelity={
            "source_frame": "S",
            "prepared_driving_frame": "P",
            "conditioning": "Approximate: C",
        },
        advisories=(
            ConditioningAdvisory("a", "text one", "heuristic"),
            ConditioningAdvisory("b", "text two", "measured"),
        ),
        warnings=("ignored",),
    )
    lines = preview_notes(preview)
    assert (
        lines[0] == "Exact: S"
        and lines[1].startswith("Exact when prepared")
        and lines[2] == "Approximate: C"
    )
    assert (
        "[heuristic] text one" in lines
        and "[measured from the files in front of you] text two" in lines
    )
    legacy = SimpleNamespace(fidelity={}, advisories=(), warnings=("old warning",))
    assert preview_notes(legacy) == ("old warning",)


# ----------------------------------------------------------------------------------------------- engine rows


def test_engine_rows_show_both_engines_without_selecting_one_or_hiding_a_refusal():
    specs = [s for s in build_builtin_workflow_specs() if "pose_video" in s.declared_input_names]
    rows = engine_rows(specs, selected=(ANIMATE, "1.2.0"), representation="rendered_silhouette")
    by_id = {r.workflow_id: r for r in rows}
    assert {FUN, ANIMATE} <= set(by_id)
    assert by_id[ANIMATE].selected and not by_id[FUN].selected
    fun = by_id[FUN]
    assert fun.workflow_version == "1.1.0" and fun.status == "Experimental trial (not qualified)"
    assert fun.usable and "10000 MiB" in fun.resource and "16 GB" in fun.resource
    assert fun.legal_lengths.startswith("17-49")
    assert any("4K" in text or "pre-scaled" in text for text in fun.limitations)
    assert "Align Motion is not available" in fun.required_preparation[-1]
    assert by_id[ANIMATE].legal_lengths.startswith("17-81")
    assert "17-49 frames" in shared_length_note(rows, specs)


def test_a_published_refusal_stays_visible_when_that_version_is_the_only_one_offered():
    spec = _spec(FUN, "1.0.0")
    (row,) = engine_rows([spec], selected=None, representation="rgb_footage")
    assert row.refusal and not row.usable and row.status == "Refused"


def test_a_representation_an_engine_cannot_take_makes_the_row_unusable_with_the_reason():
    specs = [_spec(FUN, "1.1.0")]
    (row,) = engine_rows(specs, selected=None, representation="pose_map")
    assert (
        not row.representation_accepted and "OpenPose" in row.representation_note and not row.usable
    )


def test_row_preparation_state_distinguishes_unprepared_matching_and_stale():
    specs = [_spec(FUN, "1.1.0")]
    assert (
        engine_rows(specs, selected=None, representation="rgb_footage")[0].preparation_state
        == "not prepared"
    )
    ok = engine_rows(
        specs,
        selected=None,
        representation="rgb_footage",
        prepared=_prepared(FUN, "1.1.0", 33),
        frame_count=33,
    )
    assert ok[0].preparation_state == "prepared for this engine and length"
    stale = engine_rows(
        specs,
        selected=None,
        representation="rgb_footage",
        prepared=_prepared(ANIMATE, "1.2.0", 33),
        frame_count=33,
    )
    assert stale[0].preparation_state.startswith("stale:")


# ----------------------------------------------------------------------------------------------- readiness details


def test_the_readiness_projection_carries_a_conditioning_block_for_driving_workflows_only():
    fun = motion_readiness_projection(_spec(FUN, "1.1.0"))
    assert fun["conditioning"]["mechanism"] == "rgb_canny_edges_then_resize"
    assert len(fun["conditioning"]["representations"]) == 6
    assert (
        motion_readiness_projection(_spec("wan22_ti2v_5b_i2v_v1", "1.3.0"))["conditioning"] is None
    )


def test_the_operator_lines_explain_order_representations_and_limits():
    lines = "\n".join(conditioning_lines(conditioning_projection(_spec(FUN, "1.1.0"))))
    assert "experimental trial, not qualified" in lines and "does not make it a default" in lines
    assert (
        "edge detection runs on the prepared clip at its own size, before the crop and resize"
        in lines
    )
    assert "Precomputed edge map (refused)" in lines and "OpenPose image) (refused)" in lines
    assert "[historical observation" in lines and "[read from the pinned ComfyUI source]" in lines
    animate = "\n".join(conditioning_lines(conditioning_projection(_spec(ANIMATE, "1.2.0"))))
    assert "edge detection runs" not in animate and "17-81 frames" in animate


# ----------------------------------------------------------------------------------------------- AC-09 on the form


class _Outcome:
    status = "prepared"
    message = "ok"

    def __init__(self, record):
        self.record = record


def _ready_session(workflow_id, version, frames):
    inputs = PrepInputs(
        available=True,
        workflow_id=workflow_id,
        workflow_version=version,
        frame_count=frames,
        clip_path="/lib/o.mp4",
    )
    session = MotionPreparationSession(
        prepare=lambda form, request, cancel: _Outcome(_prepared(workflow_id, version, frames))
    )
    work = session.begin(inputs)
    session.finish(work, session.run(work))
    assert session.state == STATE_READY
    return session


def test_changing_the_engine_or_length_blocks_a_preparation_made_for_the_old_one():
    session = _ready_session(ANIMATE, "1.2.0", 33)
    assert PREPARED_FIELD in session.submission_fields()
    session.refresh(
        PrepInputs(
            available=True,
            workflow_id=FUN,
            workflow_version="1.1.0",
            frame_count=33,
            clip_path="/lib/o.mp4",
        )
    )
    fields = session.submission_fields()
    assert (
        PREPARED_FIELD not in fields
        and "out of date" in fields[BLOCKED_FIELD]
        and "workflow" in fields[BLOCKED_FIELD]
    )
    session = _ready_session(FUN, "1.1.0", 33)
    session.refresh(
        PrepInputs(
            available=True,
            workflow_id=FUN,
            workflow_version="1.1.0",
            frame_count=49,
            clip_path="/lib/o.mp4",
        )
    )
    assert "length" in session.submission_fields()[BLOCKED_FIELD]
