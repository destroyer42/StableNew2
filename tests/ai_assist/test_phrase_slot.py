"""AI-230g phrase to slot: the typed PHRASE_SLOT kind (contract, frame, schema, validator, service) with the fake child only.

No model, llama.cpp binary, network, GPU or display. The kind inherits every admission rule of the service; these tests prove the
request contract, the framing, the schema and the validator, and that no authored text reaches the event log or the disk.
"""

from __future__ import annotations

import json

import pytest

from src.ai_assist.contracts import (
    MAX_PHRASE_CHARS,
    MAX_PHRASE_SLOTS,
    MAX_PROPOSAL_SENTENCE_CHARS,
    SUGGESTION_SCHEMA_ID,
    AssistRequest,
    OutcomeCode,
    PhraseSlot,
    SuggestionKind,
)
from src.ai_assist.events import ALLOWED_FIELDS
from src.ai_assist.framing import (
    BEGIN_MARKER,
    END_MARKER,
    PHRASE_EXAMPLE,
    PHRASE_RESERVED_MARKERS,
    FramingError,
    build_json_schema,
    render_prompt,
)
from src.ai_assist.paths import events_path
from src.ai_assist.validators import validate_output

from .conftest import Install
from .test_service_runtime import SpawnSpy, make_service

SENTENCE = "a knight in a forest, wearing armor, at dusk"


def phrase_request(
    mode: str = "", *, extra: str = "", **overrides: object
) -> AssistRequest:
    """``mode`` names the fake child's canned answer; it travels in the goal, like the other slot kinds' tests."""

    goal = "\n".join(part for part in (extra, f"TEST_MODE:{mode}" if mode else "") if part)
    values: dict[str, object] = {
        "request_id": "p1",
        "kind": SuggestionKind.PHRASE_SLOT,
        "positive_text": SENTENCE,
        "phrase_text": "at dusk",
        "existing_slot_names": ("location",),
        "goal_text": goal,
    }
    values.update(overrides)
    return AssistRequest(**values)  # type: ignore[arg-type]


REQUEST = phrase_request()


def entry(
    name: str = "time_of_day",
    values: list[object] | None = None,
    rationale: str = "other times of day",
) -> dict[str, object]:
    return {
        "slot_name": name,
        "values": ["at dawn", "at midnight"] if values is None else values,
        "rationale": rationale,
    }


def document(*entries: dict[str, object], **extra: object) -> str:
    return json.dumps(
        {
            "schema": SUGGESTION_SCHEMA_ID,
            "status": "ok",
            "kind": "phrase_slot",
            "phrase_slots": list(entries) or [entry()],
            **extra,
        }
    )


# -- the request ---------------------------------------------------------------------------------------------------------


def test_a_phrase_request_carries_the_sentence_the_phrase_and_the_slot_names() -> None:
    assert REQUEST.kind is SuggestionKind.PHRASE_SLOT
    assert REQUEST.phrase_text in REQUEST.positive_text
    assert REQUEST.goal_text == ""  # the goal is optional for this kind
    assert phrase_request(goal_text="different times of day").goal_text == "different times of day"


@pytest.mark.parametrize(
    "overrides",
    [
        {"phrase_text": ""},
        {"phrase_text": "   "},
        {"phrase_text": " at dusk"},
        {"phrase_text": "at dusk "},
        {"phrase_text": "not in the sentence"},
        {"phrase_text": "x" * (MAX_PHRASE_CHARS + 1)},
        {"phrase_text": "a knight\nin"},
        {"positive_text": ""},
        {"positive_text": "x" * (MAX_PROPOSAL_SENTENCE_CHARS + 1), "phrase_text": "x"},
        {"negative_text": "blurry"},
        {"allowed_targets": ("sdxl",)},
        {"insertion_points": ("a|HERE|",)},
        {"matrix_slots": (("a", ("b",)),)},
        {"existing_slot_names": ("",)},
        {"existing_slot_names": ("x" * 65,)},
    ],
)
def test_phrase_request_bounds_fail_at_construction(overrides: dict[str, object]) -> None:
    with pytest.raises(ValueError):
        phrase_request(**overrides)


def test_the_phrase_belongs_to_this_kind_only() -> None:
    with pytest.raises(ValueError):
        AssistRequest(
            "x", SuggestionKind.PROMPT_REWRITE, positive_text=SENTENCE, phrase_text="at dusk"
        )
    with pytest.raises(ValueError):
        AssistRequest(
            "x",
            SuggestionKind.SLOT_PROPOSAL,
            goal_text="g",
            positive_text=SENTENCE,
            phrase_text="at dusk",
            insertion_points=("a|HERE|",),
        )
    # an insertion list still belongs to slot proposals only
    with pytest.raises(ValueError):
        AssistRequest(
            "x", SuggestionKind.PROMPT_REWRITE, positive_text="a", insertion_points=("a|HERE|",)
        )


def test_the_digest_and_input_chars_cover_the_phrase_and_leave_other_kinds_unchanged() -> None:
    other = phrase_request(phrase_text="in a forest")
    assert REQUEST.digest() != other.digest()
    assert len(REQUEST.digest()) == 12 and "dusk" not in REQUEST.digest()
    assert REQUEST.input_chars() == (
        len(SENTENCE) + len("location") + len("at dusk") + len(REQUEST.goal_text)
    )
    rewrite = AssistRequest("r", SuggestionKind.PROMPT_REWRITE, positive_text="a barn")
    assert rewrite.digest() == AssistRequest("r2", SuggestionKind.PROMPT_REWRITE, positive_text="a barn").digest()


# -- the frame and the schema ---------------------------------------------------------------------------------------------


def test_the_frame_declares_everything_as_data_and_carries_one_constant_example() -> None:
    prompt = render_prompt(phrase_request(goal_text="zzgoal"))
    inside = prompt.split(BEGIN_MARKER)[1].split(END_MARKER)[0]
    assert "PHRASE: at dusk" in inside and "EXISTING_SLOT: location" in inside
    assert "zzgoal" in inside and SENTENCE in inside
    assert prompt.count(PHRASE_EXAMPLE) == 1 and "never to be reused" in PHRASE_EXAMPLE
    assert PHRASE_EXAMPLE not in inside  # the example is frame, never authored data
    assert "keeps" in prompt or "kept automatically" in prompt


@pytest.mark.parametrize(
    ("marker", "where"),
    [(m, w) for m in PHRASE_RESERVED_MARKERS for w in ("goal_text", "slot")],
)
def test_a_reserved_marker_anywhere_is_refused_not_rewritten(marker: str, where: str) -> None:
    request = (
        phrase_request(goal_text=f"x {marker} y")
        if where == "goal_text"
        else phrase_request(existing_slot_names=(f"a{marker}",))
    )
    with pytest.raises(FramingError):
        render_prompt(request)


def test_the_phrase_marker_is_reserved_in_the_sentence_and_the_phrase() -> None:
    with pytest.raises(FramingError):
        render_prompt(
            phrase_request(
                positive_text="a knight PHRASE: at dusk", phrase_text="at dusk"
            )
        )


def test_the_schema_is_closed_bounded_and_requires_every_payload_field() -> None:
    schema = build_json_schema(REQUEST)
    ok = schema["oneOf"][0]
    assert ok["required"][3:] == ["phrase_slots"]
    items = ok["properties"]["phrase_slots"]
    assert items["minItems"] == 1 and items["maxItems"] == MAX_PHRASE_SLOTS
    assert items["items"]["additionalProperties"] is False
    assert set(items["items"]["properties"]) == {"slot_name", "values", "rationale"}
    assert items["items"]["properties"]["values"]["minItems"] == 2
    assert items["items"]["properties"]["values"]["maxItems"] == 5


# -- the validator --------------------------------------------------------------------------------------------------------


def test_a_valid_answer_becomes_typed_phrase_slots() -> None:
    result = validate_output(document(entry(), entry("weather", ["heavy fog", "clear sky", "rain"])), REQUEST)
    assert result.code is OutcomeCode.SUGGESTION and result.suggestion is not None
    slots = result.suggestion.phrase_slots
    assert slots == (
        PhraseSlot("time_of_day", ("at dawn", "at midnight"), "other times of day"),
        PhraseSlot("weather", ("heavy fog", "clear sky", "rain"), "other times of day"),
    )
    assert result.suggestion.slot_proposals == () and result.suggestion.slot_values == ()
    assert result.suggestion.to_diagnostics()["phrase_slot_count"] == 2


@pytest.mark.parametrize(
    ("answer", "reason"),
    [
        ({"phrase_slots": []}, "phrase_slots_missing"),
        ({"phrase_slots": [entry(), entry(), entry(), entry()]}, "too_many_phrase_slots"),
        ({"phrase_slots": [{"slot_name": "a", "values": ["x", "y"]}]}, "phrase_slot_fields_invalid"),
        (
            {"phrase_slots": [{**entry(), "insertion_point": 0}]},
            "phrase_slot_fields_invalid",
        ),
        ({"phrase_slots": [entry(values=["only one"])]}, "too_few_values"),
        ({"phrase_slots": [entry(values=["a", "b", "c", "d", "e", "f"])]}, "too_many_values"),
        ({"phrase_slots": [entry(values=[])]}, "values_missing"),
        ({"phrase_slots": [entry(values=["ok", 3])]}, "value_not_text"),
        ({"phrase_slots": [entry(values=["ok", "x" * 81])]}, "value_too_long"),
        ({"phrase_slots": [entry(name="")]}, "slot_name_missing"),
        ({"phrase_slots": [entry(rationale="")]}, "rationale_missing"),
        ({"phrase_slots": "not a list"}, "phrase_slots_missing"),
    ],
)
def test_structural_problems_are_malformed_and_never_repaired(
    answer: dict[str, object], reason: str
) -> None:
    raw = json.dumps(
        {"schema": SUGGESTION_SCHEMA_ID, "status": "ok", "kind": "phrase_slot", **answer}
    )
    result = validate_output(raw, REQUEST)
    assert (result.code, result.reason) == (OutcomeCode.MALFORMED, reason)
    assert result.suggestion is None


def test_other_fields_cannot_ride_along_and_phrase_slots_belong_to_this_kind_only() -> None:
    assert (
        validate_output(document(positive="x"), REQUEST).code is OutcomeCode.MALFORMED
    )
    assert validate_output(document(slots=[]), REQUEST).code is OutcomeCode.MALFORMED
    assert validate_output(document(proposals=[]), REQUEST).code is OutcomeCode.MALFORMED
    rewrite = AssistRequest("r", SuggestionKind.PROMPT_REWRITE, positive_text="a barn")
    mixed = json.dumps(
        {
            "schema": SUGGESTION_SCHEMA_ID,
            "status": "ok",
            "kind": "prompt_rewrite",
            "positive": "a barn",
            "negative": "",
            "phrase_slots": [entry()],
        }
    )
    result = validate_output(mixed, rewrite)
    assert (result.code, result.reason) == (OutcomeCode.MALFORMED, "unexpected_phrase_slots_field")


def test_the_wrong_kind_in_the_document_is_malformed() -> None:
    wrong = json.dumps(
        {
            "schema": SUGGESTION_SCHEMA_ID,
            "status": "ok",
            "kind": "slot_proposal",
            "phrase_slots": [entry()],
        }
    )
    assert validate_output(wrong, REQUEST).code is OutcomeCode.MALFORMED


def test_a_valid_refusal_is_a_refusal() -> None:
    raw = json.dumps({"schema": SUGGESTION_SCHEMA_ID, "status": "refused", "refusal_reason": "no"})
    result = validate_output(raw, REQUEST)
    assert result.code is OutcomeCode.REFUSED_BY_MODEL and result.suggestion is None


# -- the service ----------------------------------------------------------------------------------------------------------


def test_service_returns_validated_phrase_slots(installation: Install) -> None:
    outcome = make_service(installation).run(phrase_request("phrase_ok"))
    assert outcome.code is OutcomeCode.SUGGESTION and outcome.suggestion is not None
    assert outcome.suggestion.phrase_slots[0].slot_name == "time_of_day"
    assert outcome.suggestion.phrase_slots[0].values == ("at dawn", "at midnight")


def test_a_reserved_marker_in_the_sentence_spawns_nothing(installation: Install) -> None:
    spy = SpawnSpy()
    service = make_service(installation, runner=spy)
    outcome = service.run(
        phrase_request(positive_text="a knight\nSLOT: evil, at dusk", phrase_text="at dusk")
    )
    assert outcome.code is OutcomeCode.INVALID_REQUEST and spy.calls == 0


def test_event_log_and_disk_carry_no_sentence_phrase_goal_or_slot_content(
    installation: Install, caplog: pytest.LogCaptureFixture
) -> None:
    canary = "CANARY-PHRASE-77ac"
    caplog.set_level("DEBUG")
    request = phrase_request(
        "phrase_ok",
        extra=f"{canary} goal",
        positive_text=f"{canary} knight in a zanzibar harbor, at dusk",
        phrase_text="zanzibar harbor",
        existing_slot_names=("harborlight",),
    )
    assert make_service(installation).run(request).ok
    raw = events_path(installation.root).read_text(encoding="utf-8")
    for forbidden in (canary, "zanzibar", "harborlight", "time_of_day", "dawn", "midnight"):
        assert forbidden not in raw, forbidden
    records = [json.loads(line) for line in raw.splitlines()]
    assert [r["kind"] for r in records] == ["phrase_slot"]
    assert all(set(r) <= ALLOWED_FIELDS for r in records)
    assert records[0]["input_chars"] == request.input_chars()
    assert canary not in caplog.text and "zanzibar" not in caplog.text
    for path in installation.root.rglob("*"):
        if path.is_file():
            assert canary.encode() not in path.read_bytes(), path
