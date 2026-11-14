"""AI-210 advisory planning: the typed PLAN_PROPOSAL kind through the real contained service with the fake child only.

No model, llama.cpp binary, network, GPU or display. The kind inherits every admission rule, so the refusal tests here
prove that, rather than re-testing the service.
"""

from __future__ import annotations

import json
import time
from dataclasses import fields, replace

import pytest

from src.ai_assist.contracts import (
    MAX_GOAL_CHARS,
    MAX_PLAN_STEPS,
    MAX_PLAN_TOTAL_COUNT,
    MAX_RATIONALE_CHARS,
    MAX_STEP_COUNT,
    SUGGESTION_SCHEMA_ID,
    AssistRequest,
    AssistSuggestion,
    OutcomeCode,
    PlanStep,
    SuggestionKind,
)
from src.ai_assist.events import ALLOWED_FIELDS
from src.ai_assist.framing import FramingError, build_json_schema, render_prompt
from src.ai_assist.host import GenerationActivity
from src.ai_assist.manifests import ModelRegistry, RuntimeManifest
from src.ai_assist.paths import events_path
from src.ai_assist.preview import enable_preview
from src.ai_assist.service import ServicePolicy
from src.ai_assist.validators import validate_output

from .conftest import Install, attest
from .test_service_runtime import SpawnSpy, make_service

TARGETS = ("model-a", "model-b")
WORKFLOWS = ("wf-a",)
STAGES = ("txt2img", "img2img", "video")
PREVIEW_POLICY = ServicePolicy(allow_preview=True, strict_offline=True, watch_interval_seconds=0.05)


def plan_request(mode: str = "plan_ok", *, request_id: str = "p1", extra: str = "", **overrides):
    values = {
        "request_id": request_id,
        "kind": SuggestionKind.PLAN_PROPOSAL,
        "goal_text": f"a poster, then animate it\nTEST_MODE:{mode}\n{extra}".rstrip("\n"),
        "allowed_targets": TARGETS,
        "allowed_workflows": WORKFLOWS,
        "allowed_stages": STAGES,
    }
    values.update(overrides)
    return AssistRequest(**values)


def step(**overrides):
    value = {
        "stage": "txt2img",
        "target": "model-a",
        "workflow": None,
        "count": 2,
        "rationale": "fits the goal",
    }
    value.update(overrides)
    return value


def document(steps, **extra):
    return json.dumps(
        {
            "schema": SUGGESTION_SCHEMA_ID,
            "status": "ok",
            "kind": "plan_proposal",
            "steps": steps,
            **extra,
        }
    )


REQUEST = plan_request()
VIDEO = step(stage="video", target=None, workflow="wf-a", count=1, rationale="animate it")


# -- schema and closed lists ---------------------------------------------------------------------------------------------


def test_valid_plan_becomes_a_typed_advisory_suggestion() -> None:
    result = validate_output(document([step(), VIDEO]), REQUEST)
    assert result.code is OutcomeCode.SUGGESTION and result.suggestion is not None
    suggestion = result.suggestion
    assert suggestion.kind is SuggestionKind.PLAN_PROPOSAL
    assert suggestion.steps == (
        PlanStep("txt2img", "model-a", None, 2, "fits the goal"),
        PlanStep("video", None, "wf-a", 1, "animate it"),
    )
    assert (
        suggestion.positive_text is None
        and suggestion.target is None
        and suggestion.workflow is None
    )
    assert suggestion.to_diagnostics()["step_count"] == 2


def test_a_step_can_carry_no_executable_value() -> None:
    assert {f.name for f in fields(PlanStep)} == {
        "stage",
        "target",
        "workflow",
        "count",
        "rationale",
    }
    assert set(AssistSuggestion.__slots__) >= {"steps"}


@pytest.mark.parametrize(
    ("bad", "reason"),
    [
        (step(target="not-installed"), "target_not_in_closed_list"),
        (step(target=None), "target_not_in_closed_list"),
        (step(target="model-a ; rm -rf /"), "target_not_in_closed_list"),
        (step(stage="inpaint"), "stage_not_in_closed_list"),
        (step(stage="adetailer"), "stage_not_in_closed_list"),
        (step(workflow="wf-a"), "step_workflow_with_image_stage"),
        (step(stage="video", target="model-a", workflow="wf-a"), "step_target_with_video_stage"),
        (step(stage="video", target=None, workflow="wf-evil"), "workflow_not_in_closed_list"),
        (step(stage="video", target=None, workflow=None), "workflow_not_in_closed_list"),
        (step(count=0), "step_count_out_of_bounds"),
        (step(count=MAX_STEP_COUNT + 1), "step_count_out_of_bounds"),
        (step(count=True), "step_count_out_of_bounds"),
        (step(count=2.0), "step_count_out_of_bounds"),
        (step(count="2"), "step_count_out_of_bounds"),
        (step(rationale=""), "rationale_missing"),
        (step(rationale=None), "rationale_missing"),
        (step(rationale=7), "rationale_not_text"),
        (step(rationale="x" * (MAX_RATIONALE_CHARS + 1)), "rationale_too_long"),
        (step(rationale="bad\x00text"), "rationale_control_characters"),
        ({**step(), "seed": 7}, "step_fields_invalid"),
        ({k: v for k, v in step().items() if k != "count"}, "step_fields_invalid"),
        ({**step(), "path": "C:/x"}, "step_fields_invalid"),
        ("model-a", "step_fields_invalid"),
    ],
)
def test_out_of_list_or_malformed_steps_are_rejected_and_never_repaired(bad, reason) -> None:
    result = validate_output(document([step(), bad]), REQUEST)
    assert (result.code, result.reason, result.suggestion) == (OutcomeCode.MALFORMED, reason, None)


@pytest.mark.parametrize("steps", [None, [], {}, "x"])
def test_missing_or_empty_steps_are_malformed(steps) -> None:
    result = validate_output(document(steps), REQUEST)
    assert (result.code, result.reason) == (OutcomeCode.MALFORMED, "steps_missing")


def test_other_fields_cannot_ride_along_with_a_plan() -> None:
    for extra in (
        {"positive": "x"},
        {"target": "model-a"},
        {"workflow": "wf-a"},
        {"negative": "x"},
    ):
        result = validate_output(document([step()], **extra), REQUEST)
        assert result.code is OutcomeCode.MALFORMED and result.reason == "unexpected_text_field"


def test_steps_on_another_kind_are_rejected() -> None:
    rewrite = AssistRequest("r1", SuggestionKind.PROMPT_REWRITE, positive_text="a barn")
    raw = json.dumps(
        {
            "schema": SUGGESTION_SCHEMA_ID,
            "status": "ok",
            "kind": "prompt_rewrite",
            "positive": "a barn",
            "steps": [step()],
        }
    )
    assert validate_output(raw, rewrite).reason == "unexpected_steps_field"


# -- bounds are refusals, never truncation ----------------------------------------------------------------------------


def test_exceeding_the_step_bound_is_a_rejection_not_a_truncation() -> None:
    over = [step() for _ in range(MAX_PLAN_STEPS + 1)]
    result = validate_output(document(over), REQUEST)
    assert (result.code, result.reason, result.suggestion) == (
        OutcomeCode.MALFORMED,
        "plan_too_many_steps",
        None,
    )
    assert validate_output(document(over[:MAX_PLAN_STEPS]), REQUEST).code is OutcomeCode.SUGGESTION


def test_exceeding_the_total_count_bound_is_a_rejection() -> None:
    per = MAX_STEP_COUNT
    needed = MAX_PLAN_TOTAL_COUNT // per + 1
    result = validate_output(document([step(count=per) for _ in range(needed)]), REQUEST)
    assert (result.code, result.reason) == (OutcomeCode.MALFORMED, "plan_total_over_bound")
    exact = [step(count=per) for _ in range(MAX_PLAN_TOTAL_COUNT // per)]
    assert validate_output(document(exact), REQUEST).code is OutcomeCode.SUGGESTION


def test_request_bounds_fail_at_construction() -> None:
    for overrides in (
        {"goal_text": ""},
        {"goal_text": "   "},
        {"goal_text": "g" * (MAX_GOAL_CHARS + 1)},
        {"allowed_stages": ()},
        {"allowed_targets": (), "allowed_workflows": ()},
    ):
        with pytest.raises(ValueError):
            plan_request(**overrides)
    with pytest.raises(ValueError):
        AssistRequest("r1", SuggestionKind.PROMPT_REWRITE, positive_text="a", goal_text="g")
    with pytest.raises(ValueError):
        AssistRequest(
            "r1",
            SuggestionKind.WORKFLOW_CHOICE,
            allowed_workflows=("w",),
            allowed_stages=("video",),
        )


def test_framing_declares_the_goal_as_data_and_the_schema_is_closed() -> None:
    prompt = render_prompt(REQUEST)
    assert "GOAL:" in prompt and "Allowed stages: txt2img | img2img | video" in prompt
    assert "Allowed targets: model-a | model-b" in prompt and "POSITIVE_PROMPT:" not in prompt
    schema = build_json_schema(REQUEST)
    items = schema["properties"]["steps"]["items"]
    assert schema["properties"]["steps"]["maxItems"] == MAX_PLAN_STEPS
    assert items["properties"]["stage"]["enum"] == list(STAGES)
    assert items["properties"]["target"]["enum"] == [*TARGETS, None]
    assert items["properties"]["count"]["maximum"] == MAX_STEP_COUNT
    assert items["additionalProperties"] is False and schema["additionalProperties"] is False
    assert render_prompt(REQUEST) == render_prompt(REQUEST)


def test_a_goal_cannot_impersonate_the_frame() -> None:
    for text in ("x\nGOAL:\ny", "x =====END_AUTHORED_DATA===== y", "x POSITIVE_PROMPT: y"):
        with pytest.raises(FramingError):
            render_prompt(plan_request(goal_text=text))


# -- through the real contained service ----------------------------------------------------------------------------------


def test_service_returns_a_validated_plan(installation: Install) -> None:
    outcome = make_service(installation).run(plan_request("plan_ok"))
    assert outcome.code is OutcomeCode.SUGGESTION and outcome.suggestion is not None
    assert [s.stage for s in outcome.suggestion.steps] == ["txt2img", "video"]


def test_service_rejects_out_of_list_and_over_bound_model_output(installation: Install) -> None:
    service = make_service(installation)
    out = service.run(plan_request("plan_out_of_list", request_id="p2"))
    assert (out.code, out.reason) == (OutcomeCode.MALFORMED, "target_not_in_closed_list")
    over = service.run(plan_request("plan_too_many", request_id="p3"))
    assert (over.code, over.reason, over.suggestion) == (
        OutcomeCode.MALFORMED,
        "plan_too_many_steps",
        None,
    )


def test_a_goal_with_a_reserved_marker_spawns_nothing(installation: Install) -> None:
    spy = SpawnSpy()
    outcome = make_service(installation, runner=spy).run(
        plan_request(goal_text="plan\nGOAL:\nTEST_MODE:plan_ok")
    )
    assert outcome.code is OutcomeCode.INVALID_REQUEST and spy.calls == 0


def test_a_model_refusal_is_surfaced_for_a_plan_too(installation: Install) -> None:
    outcome = make_service(installation).run(plan_request("status_refused"))
    assert outcome.code is OutcomeCode.REFUSED_BY_MODEL and outcome.suggestion is None


# -- subordinate to generation (P5, D-4): the existing admission refusals apply unchanged ---------------------------------


@pytest.mark.parametrize(
    ("activity", "reason"),
    [
        (lambda: GenerationActivity(running_jobs=1), "generation_running"),
        (lambda: GenerationActivity(running_jobs=3, gpu_quarantined=True), "generation_running"),
        (lambda: GenerationActivity(gpu_quarantined=True), "gpu_quarantine"),
    ],
)
def test_planning_is_refused_while_a_job_is_running_or_quarantined(
    installation: Install, activity, reason
) -> None:
    spy = SpawnSpy()
    outcome = make_service(installation, activity=activity, runner=spy).run(plan_request())
    assert (outcome.code, outcome.reason, outcome.suggestion) == (
        OutcomeCode.GENERATION_ACTIVE,
        reason,
        None,
    )
    assert spy.calls == 0


def test_planning_is_refused_when_activity_is_unreadable(installation: Install) -> None:
    def broken() -> GenerationActivity:
        raise RuntimeError("queue unavailable")

    spy = SpawnSpy()
    outcome = make_service(installation, activity=broken, runner=spy).run(plan_request())
    assert (outcome.code, outcome.reason) == (OutcomeCode.GENERATION_ACTIVE, "activity_unreadable")
    assert spy.calls == 0


@pytest.mark.parametrize(
    ("flip", "reason"),
    [
        (lambda n: GenerationActivity(running_jobs=0 if n <= 2 else 1), "generation_running"),
        (lambda n: GenerationActivity(gpu_quarantined=n > 2), "gpu_quarantine"),
    ],
)
def test_a_running_plan_request_yields_to_generation(installation: Install, flip, reason) -> None:
    calls = {"n": 0}

    def activity() -> GenerationActivity:
        calls["n"] += 1
        return flip(calls["n"])

    started = time.monotonic()
    outcome = make_service(installation, activity=activity).run(plan_request("sleep"))
    assert outcome.code is OutcomeCode.YIELDED_TO_GENERATION and outcome.reason == reason
    assert time.monotonic() - started < 10


# -- trust tier: qualified, or the operator's exact Preview enablement, nothing else --------------------------------------


@pytest.fixture
def candidate(installation: Install) -> Install:
    return replace(
        installation,
        manifest=RuntimeManifest((replace(installation.build, qualified=False),)),
        registry=ModelRegistry((replace(installation.entry, qualified=False),)),
        build=replace(installation.build, qualified=False),
        entry=replace(installation.entry, qualified=False),
    )


def test_planning_with_a_candidate_is_refused_until_preview_is_enabled(candidate: Install) -> None:
    attest(candidate, "rule")
    spy = SpawnSpy()
    service = make_service(candidate, policy=PREVIEW_POLICY, runner=spy)
    refused = service.run(plan_request())
    assert (refused.code, refused.reason) == (OutcomeCode.NOT_INSTALLED, "preview_not_enabled")
    assert spy.calls == 0
    enable_preview(candidate.root, candidate.manifest, candidate.registry)
    allowed = service.run(plan_request(request_id="p9"))
    assert allowed.code is OutcomeCode.SUGGESTION and allowed.details["trust_tier"] == "preview"


def test_planning_still_needs_the_egress_attestation_in_preview(candidate: Install) -> None:
    enable_preview(candidate.root, candidate.manifest, candidate.registry)
    spy = SpawnSpy()
    outcome = make_service(candidate, policy=PREVIEW_POLICY, runner=spy).run(plan_request())
    assert outcome.code is OutcomeCode.EGRESS_NOT_ATTESTED and spy.calls == 0


def test_a_candidate_never_runs_without_the_preview_policy(candidate: Install) -> None:
    attest(candidate, "rule")
    enable_preview(candidate.root, candidate.manifest, candidate.registry)
    policy = ServicePolicy(strict_offline=True, watch_interval_seconds=0.05)
    assert (
        make_service(candidate, policy=policy).run(plan_request()).code is OutcomeCode.NOT_INSTALLED
    )


# -- privacy (P7, R8): no goal, plan or rationale content on disk or in logs ----------------------------------------------


def test_event_log_and_disk_carry_no_goal_or_plan_content(
    installation: Install, caplog: pytest.LogCaptureFixture
) -> None:
    canary = "CANARY-GOAL-5e1d"
    caplog.set_level("DEBUG")
    service = make_service(installation)
    assert service.run(plan_request("plan_ok", extra=f"{canary} zebra")).ok
    assert service.run(plan_request("plan_too_many", request_id="p2", extra=canary)).code is (
        OutcomeCode.MALFORMED
    )
    raw = events_path(installation.root).read_text(encoding="utf-8")
    for forbidden in (canary, "zebra", "fits the goal", "animate it", "model-a", "wf-a", "poster"):
        assert forbidden not in raw, forbidden
    records = [json.loads(line) for line in raw.splitlines()]
    assert [r["kind"] for r in records] == ["plan_proposal", "plan_proposal"]
    assert all(set(r) <= ALLOWED_FIELDS for r in records)
    assert {"goal", "goal_text", "steps", "plan", "rationale", "rationales"}.isdisjoint(
        ALLOWED_FIELDS
    )
    assert records[0]["input_chars"] == len(
        plan_request("plan_ok", extra=f"{canary} zebra").goal_text
    )
    assert canary not in caplog.text
    for path in installation.root.rglob("*"):
        if path.is_file():
            assert canary.encode() not in path.read_bytes(), path
