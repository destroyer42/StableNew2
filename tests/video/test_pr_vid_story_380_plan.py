"""PR-VID-STORY-380: sequence plan policy v2 and the storyboard link (pure data; no files, no backend)."""

from __future__ import annotations

import os
from dataclasses import replace
from typing import Any

import pytest

from src.video.sequence_plan import (
    ANCHOR_CARRY,
    ANCHOR_SOURCE,
    PLAN_KEYS,
    ROOT_PARENT,
    SEQUENCE_POLICIES,
    SEQUENCE_POLICY_VERSION,
    SEQUENCE_POLICY_VERSION_V2,
    STAGE_VIDEO_WORKFLOW,
    SegmentSpec,
    SequenceColorMatch,
    SequencePlan,
    SequencePlanError,
    StoryboardLeadIn,
    StoryboardPlanLink,
)

WORKFLOW = "wan22_ti2v_5b_i2v_v1"
#: ``plan_sha256()`` of ``_v1_fixture()``, captured on the module before policy v2 existed.
V1_GOLDEN = "5ffc58f297dec47b85cfe265fef7b6f139a69a973007219cb41213fece269088"
HANDOFF_PATH = "storyboards/sb-1/root/frame_0004.png"
HANDOFF_SHA = "b" * 64
MANIFEST_SHA = "c" * 64
LEAD_IN_FRAMES = 5


def _segment(index: int, **kw: Any) -> SegmentSpec:
    base: dict[str, Any] = {
        "index": index,
        "seed": 100 + index,
        "frame_count": 5,
        "anchor_policy": ANCHOR_SOURCE if index == 0 else ANCHOR_CARRY,
        "workflow_id": WORKFLOW,
        "workflow_version": "1.3.0",
    }
    base.update(kw)
    return SegmentSpec(**base)


def _v1_fixture() -> SequencePlan:
    return SequencePlan(
        sequence_id="seq-test",
        stage=STAGE_VIDEO_WORKFLOW,
        fps=24,
        segments=tuple(_segment(i, overlap_frames=0 if i == 0 else 1) for i in range(3)),
        source={"path": "source.png", "sha256": "a" * 64},
    )


def _lead_in(**kw: Any) -> StoryboardLeadIn:
    base: dict[str, Any] = {
        "manifest_path": "storyboards/sb-1/cut.json",
        "manifest_sha256": MANIFEST_SHA,
        "frame_count": LEAD_IN_FRAMES,
        "handoff_path": HANDOFF_PATH,
        "handoff_sha256": HANDOFF_SHA,
    }
    base.update(kw)
    return StoryboardLeadIn(**base)


def _v2_fixture(lead_in: bool, segments: int = 1) -> SequencePlan:
    link = StoryboardPlanLink(
        storyboard_id="sb-1",
        parent_id="take-0" if lead_in else ROOT_PARENT,
        take_ids=tuple(f"t{n}" for n in range(1, segments + 1)),
        handoff_index=LEAD_IN_FRAMES - 1 if lead_in else None,
        lead_in=_lead_in() if lead_in else None,
    )
    source = (
        {"path": HANDOFF_PATH, "sha256": HANDOFF_SHA}
        if lead_in
        else {"path": "source.png", "sha256": "a" * 64}
    )
    return SequencePlan(
        sequence_id="seq-story",
        stage=STAGE_VIDEO_WORKFLOW,
        fps=24,
        segments=tuple(
            _segment(i, overlap_frames=1 if (lead_in or i > 0) else 0) for i in range(segments)
        ),
        source=source,
        policy_version=SEQUENCE_POLICY_VERSION_V2,
        storyboard=link,
    )


def test_policy_constants():
    assert SEQUENCE_POLICY_VERSION == "stablenew.video_sequence_policy.v1"
    assert SEQUENCE_POLICY_VERSION_V2 == "stablenew.video_sequence_policy.v2"
    assert SEQUENCE_POLICIES == (SEQUENCE_POLICY_VERSION, SEQUENCE_POLICY_VERSION_V2)
    assert ROOT_PARENT == "root"
    assert "storyboard" in PLAN_KEYS


def test_v1_digest_is_unchanged():
    plan = _v1_fixture()
    assert plan.validate() == []
    assert plan.plan_sha256() == V1_GOLDEN
    assert "storyboard" not in plan._content()
    assert "storyboard" not in plan.to_dict()
    assert SequencePlan.from_dict(plan.to_dict()).plan_sha256() == V1_GOLDEN


def test_v2_round_trips_and_the_digest_covers_the_link():
    plan = _v2_fixture(lead_in=True)
    assert plan.validate() == []
    again = SequencePlan.from_dict(plan.to_dict())
    assert again == plan and again.storyboard is not None
    assert again.storyboard.take_ids == ("t1",)
    assert again.storyboard.lead_in == _lead_in()
    assert plan.storyboard is not None
    other = replace(plan, storyboard=replace(plan.storyboard, take_ids=("t2",)))
    assert other.plan_sha256() != plan.plan_sha256()


def test_v2_without_lead_in_round_trips():
    plan = _v2_fixture(lead_in=False)
    again = SequencePlan.from_dict(plan.to_dict())
    assert again == plan
    assert again.storyboard is not None and again.storyboard.lead_in is None
    assert again.storyboard.handoff_index is None


@pytest.mark.parametrize(
    "mutate, message",
    [
        (lambda p: replace(p, storyboard=None), "v2 plan needs its storyboard link"),
        (
            lambda p: replace(p, policy_version=SEQUENCE_POLICY_VERSION),
            "only a v2 plan carries a storyboard link",
        ),
        (
            lambda p: replace(p, storyboard=replace(p.storyboard, take_ids=())),
            "one take id per segment",
        ),
        (
            lambda p: replace(p, segments=(replace(p.segments[0], overlap_frames=0),)),
            "segment 0 overlaps the handoff frame by 1",
        ),
        (
            lambda p: replace(p, segments=(replace(p.segments[0], overlap_frames=2),)),
            "segment 0 overlaps the handoff frame by 1",
        ),
        (
            lambda p: replace(p, source={"path": "x.png", "sha256": "0" * 64}),
            "segment 0 starts from the handoff frame",
        ),
        (lambda p: replace(p, source=None), "segment 0 starts from the handoff frame"),
        (
            lambda p: replace(p, source={"path": HANDOFF_PATH, "sha256": "0" * 64}),
            "segment 0 starts from the handoff frame",
        ),
        (
            lambda p: replace(p, assembly=replace(p.assembly, enabled=False)),
            "a storyboard take is always assembled",
        ),
        (
            lambda p: replace(p, color_match=SequenceColorMatch(enabled=True)),
            "colour matching is off for storyboard takes",
        ),
        (
            lambda p: replace(p, policy_version="stablenew.video_sequence_policy.v3"),
            "unsupported sequence execution policy",
        ),
        (
            lambda p: replace(p, storyboard=replace(p.storyboard, handoff_index=None)),
            "handoff_index must be 4",
        ),
        (
            lambda p: replace(p, storyboard=replace(p.storyboard, handoff_index=2)),
            "handoff_index must be 4",
        ),
        (
            lambda p: replace(p, storyboard=replace(p.storyboard, lead_in=_lead_in(frame_count=0))),
            "lead-in frame_count must be at least 1",
        ),
        (
            lambda p: replace(
                p, storyboard=replace(p.storyboard, lead_in=_lead_in(manifest_sha256="zz"))
            ),
            "lead-in manifest SHA-256",
        ),
        (
            lambda p: replace(
                p, storyboard=replace(p.storyboard, lead_in=_lead_in(handoff_sha256="zz"))
            ),
            "lead-in handoff SHA-256",
        ),
        (
            lambda p: replace(p, storyboard=replace(p.storyboard, storyboard_id=" ")),
            "storyboard_id must not be empty",
        ),
        (
            lambda p: replace(p, storyboard=replace(p.storyboard, parent_id="")),
            "parent_id must not be empty",
        ),
        (
            lambda p: replace(p, storyboard=replace(p.storyboard, take_ids=("",))),
            "take ids must not be empty",
        ),
    ],
)
def test_v2_validation_refusals(mutate, message):
    errors = mutate(_v2_fixture(lead_in=True)).validate()
    assert any(message in error for error in errors), errors


def test_v2_without_lead_in_keeps_segment_zero_overlap_zero():
    plan = _v2_fixture(lead_in=False)
    assert plan.validate() == [] and plan.segments[0].overlap_frames == 0
    overlapped = replace(plan, segments=(replace(plan.segments[0], overlap_frames=1),))
    assert any("nothing before it to overlap" in e for e in overlapped.validate())


def test_v2_without_lead_in_refuses_a_handoff_index():
    plan = _v2_fixture(lead_in=False)
    bad = replace(plan, storyboard=replace(plan.storyboard, handoff_index=0))
    assert any("handoff_index must be empty" in e for e in bad.validate())


def test_v1_plan_still_refuses_segment_zero_overlap():
    plan = _v1_fixture()
    bad = replace(plan, segments=(replace(plan.segments[0], overlap_frames=1), *plan.segments[1:]))
    assert any("nothing before it to overlap" in e for e in bad.validate())


def test_take_ids_must_be_unique():
    plan = _v2_fixture(lead_in=False, segments=2)
    assert plan.validate() == []
    bad = replace(plan, storyboard=replace(plan.storyboard, take_ids=("t1", "t1")))
    assert any("take ids must be unique" in e for e in bad.validate())


def test_source_path_compares_after_normalising_but_the_hash_is_exact():
    plan = _v2_fixture(lead_in=True, segments=2)
    variant = HANDOFF_PATH.replace("/", os.sep)
    if os.name == "nt":
        variant = variant.upper()
    assert replace(plan, source={"path": variant, "sha256": HANDOFF_SHA}).validate() == []
    upper = replace(plan, source={"path": HANDOFF_PATH, "sha256": HANDOFF_SHA.upper()})
    assert any("segment 0 starts from the handoff frame" in e for e in upper.validate())


@pytest.mark.parametrize(
    "mutate",
    [
        lambda d: {**d, "storyboard": {**d["storyboard"], "extra": 1}},
        lambda d: {
            **d,
            "storyboard": {
                **d["storyboard"],
                "lead_in": {**d["storyboard"]["lead_in"], "extra": 1},
            },
        },
        lambda d: {
            **d,
            "storyboard": {k: v for k, v in d["storyboard"].items() if k != "take_ids"},
        },
        lambda d: {**d, "storyboard": {**d["storyboard"], "take_ids": "t1"}},
        lambda d: {**d, "storyboard": "nope"},
        lambda d: {**d, "storyboard": {**d["storyboard"], "lead_in": "nope"}},
        lambda d: {**d, "storyboard": {**d["storyboard"], "lead_in": {"manifest_path": "x"}}},
    ],
)
def test_malformed_storyboard_link_is_refused(mutate):
    data = _v2_fixture(lead_in=True).to_dict()
    with pytest.raises(SequencePlanError):
        SequencePlan.from_dict(mutate(data))


def test_a_tampered_link_fails_the_digest():
    data = _v2_fixture(lead_in=True).to_dict()
    data["storyboard"] = {**data["storyboard"], "take_ids": ["t9"]}
    with pytest.raises(SequencePlanError, match="digest"):
        SequencePlan.from_dict(data)
