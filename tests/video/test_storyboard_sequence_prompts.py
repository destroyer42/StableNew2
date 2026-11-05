"""GP832-F4: a Storyboard whose every shot has its own motion prompt does not also need the form's prompt.

A blank shot prompt still inherits the form's (STORYBOARDS.md); with both blank the refusal names the shot. A single
video, an explicitly empty prompt and the experimental opt-in keep their existing refusals. No backend is started.
"""

from __future__ import annotations

from dataclasses import replace
from types import SimpleNamespace
from typing import Any

import pytest

from src.gui.view_contracts.video_sequence_contract import SequenceSession
from src.video.sequence_plan import SequencePlanError
from src.video.sequence_shots import ShotDraft, build_sequence_intent
from src.video.storyboard import StoryboardDraft
from src.video.storyboard_readiness import readiness, record_images
from src.video.video_workflow_intent import capability_errors
from tests.helpers.make_video_313 import ANIMATE2_ID, TI2V_ID, make_app, make_image

PROMPTS = ("a hero walks forward", "the hero turns to the camera", "the hero waves goodbye")


def _setup(tmp_path: Any, prompts: tuple[str, ...], *, form_prompt: str = "") -> SimpleNamespace:
    app, controller, service = make_app(tmp_path)
    form = {"workflow_id": TI2V_ID, "workflow_version": "1.3.0", "prompt": form_prompt, "seed": ""}
    shots = tuple(
        ShotDraft(prompt=text, frame_count=17, seed=str(10 + i)) for i, text in enumerate(prompts)
    )
    draft = replace(
        StoryboardDraft.new("Walk"),
        source_path=make_image(tmp_path / "source.png", (480, 832)),
        workflow_id=TI2V_ID,
        workflow_version="1.3.0",
        shots=shots,
    )
    return SimpleNamespace(
        controller=controller, service=service, form=form, draft=record_images(draft)
    )


def _submit(case: SimpleNamespace):
    return SequenceSession(get_controller=lambda: case.controller).submit(
        source_image_path=case.draft.source_path,
        form_data=case.form,
        shots=case.draft.shots,
        storyboard=case.draft,
    )


def _plan(case: SimpleNamespace) -> dict[str, Any]:
    return dict(case.service.submitted[0].stage_chain[0].extra)["sequence_metadata"]


def test_three_prompted_shots_queue_one_sequence_with_a_blank_form_prompt(tmp_path):
    case = _setup(tmp_path, PROMPTS)

    outcome = _submit(case)

    assert outcome.ok, outcome.message
    assert len(case.service.calls) == 1 and len(case.service.submitted) == 1  # exactly one NJR
    njr = case.service.submitted[0]
    plan = _plan(case)
    assert [s["prompt"] for s in plan["segments"]] == list(PROMPTS)
    assert [(s["workflow_id"], s["workflow_version"]) for s in plan["segments"]] == [
        (TI2V_ID, "1.3.0")
    ] * 3
    assert [s["seed"] for s in plan["segments"]] == [10, 11, 12]
    assert plan["source"]["sha256"] and plan["stage"] == "video_workflow"
    # No form prompt exists to copy: nothing frozen at job level pretends to be one of the shots.
    config = njr.workload.config["video_workflow"]
    assert config["prompt"] == "" and not njr.positive_prompt
    assert config["workflow_id"] == TI2V_ID and config["sequence_metadata"] == plan
    assert config["video_execution"]["workflow_id"] == TI2V_ID


def test_every_shot_keeps_its_own_prompt_and_only_a_blank_shot_inherits_the_form_prompt(tmp_path):
    case = _setup(tmp_path, (PROMPTS[0], "", PROMPTS[2]), form_prompt="FORM PROMPT")

    outcome = _submit(case)

    assert outcome.ok, outcome.message
    assert [s["prompt"] for s in _plan(case)["segments"]] == [PROMPTS[0], "FORM PROMPT", PROMPTS[2]]


def test_a_blank_shot_with_a_blank_form_prompt_is_refused_naming_the_shot(tmp_path):
    case = _setup(tmp_path, (PROMPTS[0], "", PROMPTS[2]))

    outcome = _submit(case)

    assert not outcome.ok and case.service.calls == []
    assert "Shot 2" in outcome.message and "Shot 1" not in outcome.message
    assert "Shot 3" not in outcome.message
    assert "needs a prompt describing the motion" in outcome.message
    assert "form's Motion prompt is empty" in outcome.message


def test_every_unprompted_shot_is_named_when_the_form_prompt_is_blank_too(tmp_path):
    case = _setup(tmp_path, ("", PROMPTS[1], ""))

    outcome = _submit(case)

    assert not outcome.ok and case.service.calls == []
    assert "Shot 1" in outcome.message and "Shot 3" in outcome.message
    assert "Shot 2" not in outcome.message


def test_an_explicitly_empty_shot_prompt_is_refused_by_shot_even_with_a_form_prompt(tmp_path):
    case = _setup(tmp_path, PROMPTS, form_prompt="FORM PROMPT")
    intent = build_sequence_intent(case.draft.shots)
    intent["segments"][1]["prompt"] = ""

    with pytest.raises(SequencePlanError, match=r"Shot 2: .*explicitly empty prompt is refused"):
        case.controller.build_sequence_job(
            source_image_path=case.draft.source_path, form_data=case.form, sequence_intent=intent
        )

    assert case.service.calls == []


def test_preview_names_the_shot_without_a_prompt_and_is_quiet_when_all_are_prompted(tmp_path):
    prompted = _setup(tmp_path, PROMPTS)
    registry = prompted.controller._workflow_registry
    assert not [
        p for p in readiness(prompted.draft, registry, prompted.form).problems if "prompt" in p
    ]

    gap = _setup(tmp_path / "gap", (PROMPTS[0], PROMPTS[1], ""))
    problems = readiness(gap.draft, gap.controller._workflow_registry, gap.form).problems
    assert [p for p in problems if p.startswith("Shot 3: ")], problems
    assert readiness(
        gap.draft, gap.controller._workflow_registry, {**gap.form, "prompt": "FORM PROMPT"}
    ).problems == tuple(p for p in problems if not p.startswith("Shot 3: "))


def test_a_single_video_with_a_blank_prompt_is_still_refused(tmp_path):
    case = _setup(tmp_path, PROMPTS)
    builder = case.controller._njr_builder

    valid, reason = case.controller.validate_form_data(dict(case.form))
    assert not valid and "needs a prompt describing the motion" in str(reason)
    with pytest.raises(ValueError, match="needs a prompt describing the motion"):
        builder.freeze_inputs(case.draft.source_path, case.form)
    frozen = builder.freeze_inputs(case.draft.source_path, case.form, prompt_per_segment=True)
    with pytest.raises(ValueError, match="needs a prompt describing the motion"):
        builder.build_job(case.form, frozen)  # no sequence plan: the form prompt is required again
    assert case.service.calls == []


def test_the_experimental_opt_in_is_still_required_for_a_sequence_form(tmp_path):
    case = _setup(tmp_path, PROMPTS)
    spec = case.controller._workflow_registry.get(ANIMATE2_ID, "1.2.0")
    form = {"workflow_id": ANIMATE2_ID, "prompt": ""}

    refused = capability_errors(spec, form, prompt_per_segment=True)
    granted = capability_errors(
        spec, {**form, "experimental_opt_in": True}, prompt_per_segment=True
    )

    assert any("experimental workflow" in text for text in refused)
    assert not any("experimental workflow" in text for text in granted)
    assert not any("needs a prompt" in text for text in refused + granted)
    assert any("needs a prompt" in text for text in capability_errors(spec, form))
