"""PR-VID-UX-313: friendly workflow labels and the recommended (approved) workflow, as pure functions."""

from __future__ import annotations

from types import SimpleNamespace

from src.controller.video_workflow_controller import VideoWorkflowController
from src.video.workflow_picker import (
    EXPERIMENTAL_SUFFIX,
    RECOMMENDED_SUFFIX,
    recommended_workflow_id,
    workflow_choices,
)


def _record(workflow_id: str, *, state: str = "approved", name: str = "", experimental=None):
    return {
        "workflow_id": workflow_id,
        "display_name": name,
        "governance_state": state,
        "experimental": state == "experimental" if experimental is None else experimental,
    }


def test_the_recommended_workflow_is_the_first_approved_one_never_an_experimental_one() -> None:
    records = [
        _record("exp_first", state="experimental"),
        _record("approved_a"),
        _record("approved_b"),
    ]
    assert recommended_workflow_id(records) == "approved_a"
    assert recommended_workflow_id([_record("exp_only", state="experimental")]) == ""
    assert recommended_workflow_id([]) == ""
    assert recommended_workflow_id([_record("disabled_one", state="disabled")]) == ""


def test_labels_are_friendly_marked_by_governance_and_unique() -> None:
    choices = workflow_choices(
        [
            _record("wf_a", name="Alpha"),
            _record("wf_b", state="experimental", name="Beta"),
            _record("wf_c", state="experimental", name="Gamma (Experimental)"),
            _record("wf_d", name=""),
        ]
    )
    labels = {choice.workflow_id: choice.label for choice in choices}
    assert labels["wf_a"] == "Alpha" + RECOMMENDED_SUFFIX
    assert labels["wf_b"] == "Beta" + EXPERIMENTAL_SUFFIX
    assert labels["wf_c"] == "Gamma (Experimental)"  # already says so: not marked twice
    assert labels["wf_d"] == "wf_d"  # no display name: the id is the only name there is
    assert [choice.recommended for choice in choices] == [True, False, False, False]
    assert [choice.experimental for choice in choices] == [False, True, True, False]


def test_two_workflows_with_the_same_name_stay_distinguishable() -> None:
    choices = workflow_choices(
        [
            _record("one", state="experimental", name="Same"),
            _record("two", state="experimental", name="Same"),
        ]
    )
    labels = [choice.label for choice in choices]
    assert len(set(labels)) == 2 and all("[" in label for label in labels)


def test_records_without_an_id_are_not_offered() -> None:
    assert workflow_choices([{"display_name": "No id"}]) == []


def test_the_default_form_state_prefers_the_recommended_workflow(monkeypatch) -> None:
    app = SimpleNamespace(job_service=None, output_dir="output")
    controller = VideoWorkflowController(app_controller=app)
    records = [
        {**_record("exp_first", state="experimental"), "workflow_version": "1"},
        {**_record("approved_one"), "workflow_version": "2"},
    ]
    monkeypatch.setattr(controller, "list_workflow_specs", lambda: records)
    assert controller.recommended_workflow_id() == "approved_one"
    assert controller.build_default_form_state()["workflow_id"] == "approved_one"
    monkeypatch.setattr(controller, "list_workflow_specs", lambda: records[:1])
    assert (
        controller.build_default_form_state()["workflow_id"] == "exp_first"
    )  # nothing approved: unchanged


def test_the_real_catalog_recommends_the_approved_ti2v_workflow() -> None:
    app = SimpleNamespace(job_service=None, output_dir="output")
    controller = VideoWorkflowController(app_controller=app)
    assert controller.recommended_workflow_id() == "wan22_ti2v_5b_i2v_v1"
    experimental = [s for s in controller.list_workflow_specs() if s["experimental"]]
    assert experimental and all(
        s["workflow_id"] != controller.recommended_workflow_id() for s in experimental
    )
