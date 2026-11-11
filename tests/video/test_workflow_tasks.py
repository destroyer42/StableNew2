"""PR-VID-UX-360: task eligibility, engine choice and suggested settings for the Video Workflow tab.

Pure rules over the plain workflow records ``VideoWorkflowController.list_workflow_specs`` returns; no Tk,
no runtime, no catalog.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from src.video import workflow_tasks
from src.video.workflow_tasks import (
    TASK_ANIMATE,
    TASK_BATCH,
    TASK_FOLLOW_CLIP,
    TASK_SEQUENCE,
    TASKS,
    choose_workflow,
    eligible_workflows,
    infer_task,
)


def _rec(
    wid: str,
    *,
    approved: bool = False,
    experimental: bool = False,
    pose: bool = False,
    frame_count: bool = True,
    block: str = "",
) -> dict[str, Any]:
    return {
        "workflow_id": wid,
        "display_name": f"Engine {wid}",
        "governance_state": "approved" if approved else "experimental",
        "experimental": experimental,
        "form_visibility": {
            "pose_video": pose,
            "frame_count": frame_count,
            "motion_profile": True,
            "seed": True,
        },
        "frame_count": {"default": 81, "choices": [{"frames": 49}, {"frames": 81}]}
        if frame_count
        else None,
        "operator_projection": {"admission_block_reason": block} if block else {},
    }


def test_four_tasks_in_display_order():
    assert [task.task_id for task in TASKS] == [
        TASK_ANIMATE,
        TASK_FOLLOW_CLIP,
        TASK_SEQUENCE,
        TASK_BATCH,
    ]
    assert all(task.label and task.description for task in TASKS)


def test_eligibility_splits_on_driving_clip():
    recs = [_rec("a", approved=True), _rec("b", experimental=True, pose=True)]
    assert [r["workflow_id"] for r in eligible_workflows(TASK_ANIMATE, recs)] == ["a"]
    assert [r["workflow_id"] for r in eligible_workflows(TASK_FOLLOW_CLIP, recs)] == ["b"]
    assert [r["workflow_id"] for r in eligible_workflows(TASK_BATCH, recs)] == ["a"]


def test_sequence_needs_a_frame_count_policy():
    recs = [_rec("a", approved=True, frame_count=False), _rec("c", approved=True)]
    assert [r["workflow_id"] for r in eligible_workflows(TASK_SEQUENCE, recs)] == ["c"]


def test_choice_order_pinned_then_approved_then_unblocked_then_blocked():
    recs = [_rec("x", experimental=True), _rec("a", approved=True), _rec("a2", approved=True)]
    assert choose_workflow(TASK_ANIMATE, recs).workflow_id == "a"
    assert choose_workflow(TASK_ANIMATE, recs, "a2").workflow_id == "a2"
    assert choose_workflow(TASK_ANIMATE, recs, "not-eligible").workflow_id == "a"


def test_approved_choice_needs_no_opt_in():
    choice = choose_workflow(TASK_ANIMATE, [_rec("a", approved=True)])
    assert (choice.needs_opt_in, choice.block_reason) == (False, "")
    assert choice.reason


def test_experimental_only_task_needs_opt_in_and_is_not_blocked():
    choice = choose_workflow(TASK_FOLLOW_CLIP, [_rec("b", experimental=True, pose=True)])
    assert (choice.workflow_id, choice.needs_opt_in, choice.block_reason) == ("b", True, "")


def test_unblocked_experimental_beats_blocked_one():
    recs = [
        _rec("f", experimental=True, pose=True, block="hardware unqualified"),
        _rec("b", experimental=True, pose=True),
    ]
    assert choose_workflow(TASK_FOLLOW_CLIP, recs).workflow_id == "b"
    only = choose_workflow(TASK_FOLLOW_CLIP, recs[:1])
    assert only.workflow_id == "f"
    assert only.block_reason == "hardware unqualified"


def test_no_eligible_engine_returns_none():
    assert choose_workflow(TASK_FOLLOW_CLIP, [_rec("a", approved=True)]) is None


def test_infer_task():
    assert infer_task(_rec("b", pose=True)) == TASK_FOLLOW_CLIP
    assert infer_task(_rec("a")) == TASK_ANIMATE
    assert infer_task(_rec("a"), "sequence") == TASK_SEQUENCE  # a saved valid task wins
    assert infer_task(_rec("a"), "nonsense") == TASK_ANIMATE
    assert (
        infer_task(_rec("a"), "follow_clip") == TASK_ANIMATE
    )  # saved task the engine cannot serve
    assert infer_task(None, None) == TASK_ANIMATE


def test_module_names_no_workflow_or_model():
    text = Path(workflow_tasks.__file__).read_text(encoding="utf-8").lower()
    assert not any(word in text for word in ("wan", "ti2v", "animate2", "svd", "comfy"))


# ---------------------------------------------------------------- suggested settings and pins


def _suggest(task_id: str, rec: dict[str, Any], *, rife: bool = True):
    return workflow_tasks.suggest_settings(task_id, rec, rife_available=rife)


def test_suggestions_come_from_the_record():
    s = _suggest(TASK_ANIMATE, _rec("a", approved=True))
    assert s[workflow_tasks.FIELD_LENGTH].value == 81
    assert s[workflow_tasks.FIELD_SMOOTH].value is True
    assert s[workflow_tasks.FIELD_SEED].value == ""
    assert s[workflow_tasks.FIELD_NEGATIVE].value == ""
    assert s[workflow_tasks.FIELD_MOTION].value == "gentle"
    assert all(item.reason and item.field == key for key, item in s.items())


def test_no_length_suggestion_without_a_frame_count_policy():
    s = _suggest(TASK_ANIMATE, _rec("a", frame_count=False))
    assert workflow_tasks.FIELD_LENGTH not in s


def test_motion_only_when_declared():
    rec = _rec("a")
    rec["form_visibility"]["motion_profile"] = False
    assert workflow_tasks.FIELD_MOTION not in _suggest(TASK_ANIMATE, rec)


def test_smoothing_off_without_rife_and_in_a_sequence():
    rec = _rec("a", approved=True)
    missing = _suggest(TASK_ANIMATE, rec, rife=False)[workflow_tasks.FIELD_SMOOTH]
    assert missing.value is False and "tools/rife" in missing.reason
    seq = _suggest(TASK_SEQUENCE, rec)[workflow_tasks.FIELD_SMOOTH]
    assert seq.value is False and "sequence" in seq.reason


def test_reconcile_keeps_legal_pins_and_replaces_illegal_ones():
    rec = _rec("a")
    s = _suggest(TASK_ANIMATE, rec)
    length, smooth = workflow_tasks.FIELD_LENGTH, workflow_tasks.FIELD_SMOOTH
    values, notes = workflow_tasks.reconcile({length: 49, smooth: False}, {length, smooth}, s, rec)
    assert length not in values and smooth not in values and notes == []
    values, notes = workflow_tasks.reconcile({length: 33}, {length}, s, rec)
    assert values[length] == 81 and len(notes) == 1 and "33" in notes[0]


def test_reconcile_applies_every_unpinned_suggestion():
    rec = _rec("a")
    s = _suggest(TASK_ANIMATE, rec)
    values, notes = workflow_tasks.reconcile({}, set(), s, rec)
    assert values == {key: item.value for key, item in s.items()} and notes == []


def test_pinned_smoothing_without_rife_is_kept_and_warned():
    warn = workflow_tasks.smoothing_warning
    assert warn(TASK_ANIMATE, True, rife_available=False).startswith("Smoothing cannot run")
    assert warn(TASK_ANIMATE, True, rife_available=True) == ""
    assert warn(TASK_ANIMATE, False, rife_available=False) == ""
    assert "sequence" in warn(TASK_SEQUENCE, True, rife_available=True)
