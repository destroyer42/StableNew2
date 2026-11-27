"""N13: video picker hygiene over the real catalog records (no Tk, no Comfy, no network).

Wan-Animate-2 prompt mode is never offered; unrated speed arms and superseded arms are offered only with
Show experimental; approved engines and the only driving-clip engines are always offered; the selected engine is
always offered so a restored form or a handoff never loses it. Nothing is removed from the catalog.
"""

from __future__ import annotations

import pytest

from src.controller.ports.default_runtime_ports import DefaultWorkflowRegistryPort
from src.controller.video_workflow_controller import VideoWorkflowController
from src.video import workflow_picker as picker
from src.video.workflow_tasks import TASK_ANIMATE, TASK_FOLLOW_CLIP, choose_workflow

PROMPT_MODE = "wan_animate2_prompt_i2v_v1"
ARMS = {
    "wan22_i2v_a14b_4step_ck_v1",
    "wan22_i2v_a14b_4step_full_picture_v1",
    "wan22_i2v_a14b_svi",
    "hunyuan_video15_i2v_480p_8step_v1",
    "hunyuan_video15_i2v_480p_12step_v1",
    "ltx25_distilled_i2v_v1",
    "ltx25_distilled_i2v_audio_v1",
}
ALWAYS = {
    "wan22_i2v_a14b_4step_v1",
    "wan22_i2v_a14b_flf_v1",  # the only engine that takes an end image
    "wan22_ti2v_5b_i2v_v1",
    "wan22_ti2v_5b_i2v_720p_v1",
    "wan_animate2_drive_i2v_v1",
    "wan22_fun_control_5b_canny_i2v_v1",
}


@pytest.fixture(scope="module")
def records() -> list[dict]:
    controller = VideoWorkflowController(
        app_controller=None, workflow_registry=DefaultWorkflowRegistryPort()
    )
    return controller.list_workflow_specs()


def _ids(records: list[dict]) -> set[str]:
    return {str(record["workflow_id"]) for record in records}


def test_the_catalog_still_lists_every_workflow(records) -> None:
    assert _ids(records) == ALWAYS | ARMS | {PROMPT_MODE}


def test_the_default_picker_offers_approved_engines_and_the_only_driving_clip_engines(
    records,
) -> None:
    offered = picker.offered_workflow_ids(records, show_experimental=False)
    assert offered == ALWAYS


def test_show_experimental_adds_the_unrated_arms_but_never_prompt_mode(records) -> None:
    offered = picker.offered_workflow_ids(records, show_experimental=True)
    assert offered == ALWAYS | ARMS
    assert PROMPT_MODE not in offered


def test_every_hidden_entry_says_why(records) -> None:
    by_id = {record["workflow_id"]: record for record in records}
    retired = picker.picker_tier(by_id[PROMPT_MODE])
    assert retired.tier == picker.TIER_RETIRED
    assert "31 of 31" in retired.reason
    for workflow_id in ARMS:
        tier = picker.picker_tier(by_id[workflow_id])
        assert tier.tier == picker.TIER_EXPERIMENTAL_ONLY and "unrated" in tier.reason.lower()
    for workflow_id in ALWAYS:
        assert picker.picker_tier(by_id[workflow_id]).tier == picker.TIER_DEFAULT


def test_an_approved_workflow_is_never_hidden_even_if_listed(records) -> None:
    approved = [record for record in records if record["governance_state"] == "approved"]
    assert approved
    for record in approved:
        assert (
            picker.picker_tier({**record, "workflow_id": PROMPT_MODE}).tier == picker.TIER_DEFAULT
        )


def test_the_selected_engine_is_always_offered(records) -> None:
    for kept in (PROMPT_MODE, "wan22_i2v_a14b_4step_ck_v1"):
        offered = picker.offered_workflow_ids(records, show_experimental=False, keep=(kept,))
        assert kept in offered
        assert offered - {kept} == ALWAYS


def test_choices_carry_their_tier_and_labels_stay_unique(records) -> None:
    choices = picker.workflow_choices(records)
    assert len({choice.label for choice in choices}) == len(choices)
    tiers = {choice.workflow_id: choice.picker_tier for choice in choices}
    assert tiers[PROMPT_MODE] == picker.TIER_RETIRED
    assert {
        workflow_id for workflow_id, tier in tiers.items() if tier == picker.TIER_EXPERIMENTAL_ONLY
    } == ARMS


def test_tasks_still_resolve_with_only_the_offered_engines(records) -> None:
    offered = picker.offered_workflow_ids(records, show_experimental=False)
    visible = [record for record in records if record["workflow_id"] in offered]
    assert choose_workflow(TASK_ANIMATE, visible).workflow_id == "wan22_i2v_a14b_4step_v1"
    assert choose_workflow(TASK_FOLLOW_CLIP, visible) is not None
