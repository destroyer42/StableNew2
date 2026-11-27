"""ASSIST-FIX: no refusal branch is offered, a refusal is still surfaced, and a malformed remote answer is retried once.

Hermetic: a scripted transport stands in for the worker.
"""

from __future__ import annotations

import json
from typing import Any

import pytest

from src.ai_assist import framing, validators
from src.ai_assist.contracts import (
    SUGGESTION_SCHEMA_ID,
    AssistRequest,
    OutcomeCode,
    SuggestionKind,
)
from src.ai_assist.events import EventLog
from src.ai_assist.paths import events_path

from .test_ai202c import ACCEPTED, REQUESTS, conforms
from .test_remote_preview import REWRITE, Worker, assist_request, service_for

GOOD = json.dumps(REWRITE)


class Scripted(Worker):
    """Answers generation requests from a list; the last entry repeats."""

    def __init__(self, *outputs: str, done_reason: str = "stop") -> None:
        super().__init__()
        self.outputs = list(outputs)
        self.done_reason = done_reason

    def __call__(self, path, body, token, timeout, limit):
        if path == "/api/generate" and path not in self.failures:
            self.output = self.outputs.pop(0) if len(self.outputs) > 1 else self.outputs[0]
            status, raw = super().__call__(path, body, token, timeout, limit)
            return status, json.dumps({**json.loads(raw), "done_reason": self.done_reason}).encode()
        return super().__call__(path, body, token, timeout, limit)

    def prompts(self) -> list[str]:
        return [json.loads(body)["prompt"] for path, body in self.calls if path == "/api/generate"]


def last_event(installation) -> dict[str, Any]:
    return EventLog(events_path(installation.root)).tail(1)[0]


@pytest.mark.parametrize("kind", list(SuggestionKind))
def test_neither_schema_nor_instructions_offer_a_refusal(kind: SuggestionKind) -> None:
    request = REQUESTS[kind]
    schema = framing.build_json_schema(request)
    assert "refus" not in json.dumps(schema).lower()
    assert schema["properties"]["status"] == {"const": "ok"}
    for prompt in (framing.render_prompt(request), framing.render_prompt(request, retry=True)):
        instructions = prompt.split(framing.BEGIN_MARKER)[0].lower()
        assert "refus" not in instructions and "cannot or will not" not in instructions


def test_a_plan_schema_ties_each_stage_to_its_own_choice() -> None:
    schema = framing.build_json_schema(REQUESTS[SuggestionKind.PLAN_PROPOSAL])
    good = ACCEPTED[SuggestionKind.PLAN_PROPOSAL]
    assert conforms(good, schema)
    image, video = good["steps"]
    for bad in (
        {**image, "target": None},
        {**image, "workflow": "svd_xt"},
        {**video, "workflow": None},
        {**video, "target": "sdxl"},
    ):
        assert not conforms({**good, "steps": [bad]}, schema), bad


@pytest.mark.parametrize(
    ("kind", "payload"),
    [
        (SuggestionKind.PROMPT_REWRITE, {"positive": "I cannot help with that.", "negative": ""}),
        (
            SuggestionKind.SLOT_VARIETY,
            {"slots": [{"slot": "lighting", "values": ["I can't help"], "rationale": "no"}]},
        ),
        (
            SuggestionKind.SLOT_PROPOSAL,
            {
                "proposals": [
                    {
                        "slot_name": "weather",
                        "values": ["fog", "Sorry, I cannot", "rain"],
                        "insertion_point": 0,
                        "rationale": "x",
                    }
                ]
            },
        ),
    ],
)
def test_a_refusal_written_into_the_content_is_still_a_refusal(kind, payload) -> None:
    document = {"schema": SUGGESTION_SCHEMA_ID, "status": "ok", "kind": kind.value, **payload}
    request = REQUESTS[kind]
    if kind is SuggestionKind.PROMPT_REWRITE:
        request = AssistRequest("c1", kind, positive_text="a barn")
    result = validators.validate_output(json.dumps(document), request)
    assert result.code is OutcomeCode.REFUSED_BY_MODEL
    assert result.reason == "refusal_in_content" and result.suggestion is None


def test_authored_text_that_opens_like_a_refusal_is_not_called_one() -> None:
    request = AssistRequest(
        "c2", SuggestionKind.PROMPT_REWRITE, positive_text="I can't stop dancing"
    )
    document = {
        "schema": SUGGESTION_SCHEMA_ID,
        "status": "ok",
        "kind": "prompt_rewrite",
        "positive": "I can't stop dancing, golden hour",
        "negative": "",
    }
    assert validators.validate_output(json.dumps(document), request).code is OutcomeCode.SUGGESTION


def test_a_malformed_answer_is_retried_once_with_a_tighter_instruction(installation) -> None:
    worker = Scripted("{not json", GOOD)
    service, _spy, _ = service_for(installation, worker)
    outcome = service.run(assist_request())
    assert outcome.ok and outcome.details["attempts"] == 2
    first, second = worker.prompts()
    assert framing.RETRY_INSTRUCTION not in first and framing.RETRY_INSTRUCTION in second
    event = last_event(installation)
    assert (event["attempts"], event["first_reason"], event["outcome"]) == (
        2,
        "not_json",
        "suggestion",
    )


def test_two_malformed_answers_stay_malformed(installation) -> None:
    worker = Scripted("{not json")
    service, _spy, _ = service_for(installation, worker)
    outcome = service.run(assist_request())
    assert outcome.code is OutcomeCode.MALFORMED and outcome.details["attempts"] == 2
    assert len(worker.prompts()) == 2
    assert last_event(installation)["attempts"] == 2


def test_an_answer_cut_off_at_the_token_limit_says_so_and_is_retried(installation) -> None:
    worker = Scripted('{"schema":', done_reason="length")
    service, _spy, _ = service_for(installation, worker)
    outcome = service.run(assist_request())
    assert outcome.code is OutcomeCode.MALFORMED and outcome.reason == "remote_truncated"
    assert len(worker.prompts()) == 2


def test_a_missing_field_is_retried(installation) -> None:
    short = {key: value for key, value in REWRITE.items() if key != "negative"}
    worker = Scripted(json.dumps(short), GOOD)
    service, _spy, _ = service_for(installation, worker)
    assert service.run(assist_request()).ok
    assert last_event(installation)["first_reason"] == "remote_response_fields"


@pytest.mark.parametrize(
    "answer",
    [
        GOOD,
        '{"schema":"ai_assist.suggestion/1","status":"refused","refusal_reason":"no"}',
        "I cannot help with that.",
    ],
    ids=["suggestion", "status_refused", "text_refusal"],
)
def test_a_suggestion_or_a_refusal_is_never_retried(installation, answer) -> None:
    worker = Scripted(answer, GOOD)
    service, _spy, _ = service_for(installation, worker)
    outcome = service.run(assist_request())
    assert outcome.details["attempts"] == 1 and len(worker.prompts()) == 1
    assert (outcome.code is OutcomeCode.SUGGESTION) == (answer == GOOD)
    assert "first_reason" not in last_event(installation)


@pytest.mark.parametrize("failure", ["timeout", "response_lost", "invalid_json", 503])
def test_a_transport_failure_is_never_retried(installation, failure) -> None:
    worker = Scripted(GOOD)
    worker.failures["/api/generate"] = failure
    service, _spy, _ = service_for(installation, worker)
    outcome = service.run(assist_request())
    assert not outcome.ok
    assert [path for path, _ in worker.calls].count("/api/generate") == 1
