"""AI-212 slot variety: the typed SLOT_VARIETY kind through the real contained service with the fake child only.

No model, llama.cpp binary, network, GPU or display. The kind inherits every admission rule of the service; these tests prove
the contract, the framing, the schema and the validator, and that no authored text reaches the event log or the disk.
"""

from __future__ import annotations

import json

import pytest

from src.ai_assist.contracts import (
    MAX_GOAL_CHARS,
    MAX_VARIETY_EXISTING_VALUES,
    MAX_VARIETY_INPUT_CHARS,
    MAX_VARIETY_NEW_VALUES,
    MAX_VARIETY_RATIONALE_CHARS,
    MAX_VARIETY_SLOTS,
    MAX_VARIETY_VALUE_CHARS,
    SUGGESTION_SCHEMA_ID,
    AssistRequest,
    OutcomeCode,
    SlotValues,
    SuggestionKind,
)
from src.ai_assist.events import ALLOWED_FIELDS
from src.ai_assist.framing import (
    BEGIN_MARKER,
    END_MARKER,
    VARIETY_RESERVED_MARKERS,
    FramingError,
    build_json_schema,
    render_prompt,
)
from src.ai_assist.paths import events_path
from src.ai_assist.validators import validate_output

from .conftest import Install
from .test_service_runtime import SpawnSpy, make_service

SLOTS = (("lighting", ("soft light", "rim light")), ("location", ("forest",)))


def variety_request(
    mode: str = "variety_ok", *, request_id: str = "v1", extra: str = "", **overrides
):
    values = {
        "request_id": request_id,
        "kind": SuggestionKind.SLOT_VARIETY,
        "goal_text": f"more variety in the lighting\nTEST_MODE:{mode}\n{extra}".rstrip("\n"),
        "matrix_slots": SLOTS,
    }
    values.update(overrides)
    return AssistRequest(**values)


def entry(**overrides):
    value = {"slot": "lighting", "values": ["golden hour"], "rationale": "warmer light"}
    value.update(overrides)
    return value


def document(slots, **extra):
    return json.dumps(
        {
            "schema": SUGGESTION_SCHEMA_ID,
            "status": "ok",
            "kind": "slot_variety",
            "slots": slots,
            **extra,
        }
    )


REQUEST = variety_request()


# -- request contract ----------------------------------------------------------------------------------------------------


def test_a_variety_request_carries_only_a_goal_and_the_slots() -> None:
    assert REQUEST.matrix_slots == SLOTS
    for field, value in (
        ("positive_text", "a prompt"),
        ("negative_text", "blurry"),
        ("target_policy_id", "sdxl"),
        ("allowed_targets", ("model-a",)),
        ("allowed_workflows", ("wf-a",)),
        ("allowed_stages", ("txt2img",)),
    ):
        with pytest.raises(ValueError):
            variety_request(**{field: value})


@pytest.mark.parametrize(
    "overrides",
    [
        {"goal_text": "   "},
        {"goal_text": "x" * (MAX_GOAL_CHARS + 1)},
        {"matrix_slots": ()},
        {"matrix_slots": tuple((f"s{i}", ()) for i in range(MAX_VARIETY_SLOTS + 1))},
        {"matrix_slots": (("", ("a",)),)},
        {"matrix_slots": (("x" * 65, ("a",)),)},
        {"matrix_slots": (("a", ()), ("a", ()))},
        {"matrix_slots": (("a", ("v",) * (MAX_VARIETY_EXISTING_VALUES + 1)),)},
        {"matrix_slots": (("a", ("v" * (MAX_VARIETY_INPUT_CHARS),)),)},
        {"matrix_slots": (("a", (1,)),)},
        {"matrix_slots": (("a", ["v"]),)},
    ],
)
def test_request_bounds_fail_at_construction(overrides) -> None:
    with pytest.raises(ValueError):
        variety_request(**overrides)


def test_matrix_slots_belong_to_the_variety_kind_only() -> None:
    with pytest.raises(ValueError):
        AssistRequest("r1", SuggestionKind.PROMPT_REWRITE, "a barn", matrix_slots=SLOTS)


def test_input_chars_count_goal_names_and_values_and_other_digests_are_unchanged() -> None:
    names_and_values = sum(len(n) + sum(len(v) for v in vs) for n, vs in SLOTS)
    assert REQUEST.input_chars() == len(REQUEST.goal_text) + names_and_values
    assert (
        REQUEST.digest() != variety_request(matrix_slots=(("lighting", ("soft light",)),)).digest()
    )
    # The slot component is appended only when present: a rewrite request digests exactly as before AI-212.
    rewrite = AssistRequest("r1", SuggestionKind.PROMPT_REWRITE, "a barn", "blurry", "sdxl")
    import hashlib

    legacy = "\x1f".join(("prompt_rewrite", "a barn", "blurry", "sdxl", "", "", "", ""))
    assert rewrite.digest() == hashlib.sha256(legacy.encode("utf-8")).hexdigest()[:12]


# -- framing -------------------------------------------------------------------------------------------------------------


def test_framing_declares_goal_slots_and_values_as_data_and_sends_no_lists() -> None:
    prompt = render_prompt(REQUEST)
    data = prompt.split(BEGIN_MARKER, 1)[1].split(END_MARKER, 1)[0]
    assert "GOAL:\nmore variety in the lighting" in data
    assert (
        "SLOT: lighting\nVALUE: soft light\nVALUE: rim light\nSLOT: location\nVALUE: forest" in data
    )
    before = prompt.split(BEGIN_MARKER, 1)[0]
    assert "soft light" not in before and "forest" not in before
    for absent in ("Allowed targets:", "Allowed workflows:", "Allowed stages:"):
        assert absent not in prompt


@pytest.mark.parametrize("marker", VARIETY_RESERVED_MARKERS)
@pytest.mark.parametrize("where", ["goal", "name", "value"])
def test_a_reserved_marker_anywhere_is_refused_not_rewritten(marker, where) -> None:
    goal, slots = "more light", SLOTS
    if where == "goal":
        goal = f"more {marker} light"
    elif where == "name":
        slots = ((f"x{marker}", ("a",)),)
    else:
        slots = (("lighting", (f"soft {marker}",)),)
    with pytest.raises(FramingError):
        render_prompt(variety_request(goal_text=goal, matrix_slots=slots))


@pytest.mark.parametrize(
    "slots",
    [(("light\ning", ("a",)),), (("lighting", ("soft\nlight",)),), (("lighting", ("a\rb",)),)],
)
def test_a_line_break_in_a_name_or_value_is_refused(slots) -> None:
    with pytest.raises(FramingError):
        render_prompt(variety_request(matrix_slots=slots))


def test_the_goal_may_span_lines_like_the_plan_goal() -> None:
    assert "line one\nline two" in render_prompt(variety_request(goal_text="line one\nline two"))


# -- schema --------------------------------------------------------------------------------------------------------------


def test_the_schema_is_closed_bounded_and_requires_every_payload_field() -> None:
    ok, refused = build_json_schema(REQUEST)["oneOf"]
    assert ok["required"] == ["schema", "status", "kind", "slots"]
    assert list(ok["properties"]) == ["schema", "status", "kind", "slots", "changes"]
    slots = ok["properties"]["slots"]
    assert (slots["minItems"], slots["maxItems"]) == (1, len(SLOTS))
    item = slots["items"]
    assert item["required"] == ["slot", "values", "rationale"]
    assert item["additionalProperties"] is False
    assert item["properties"]["slot"] == {"enum": ["lighting", "location"]}
    values = item["properties"]["values"]
    assert (values["minItems"], values["maxItems"]) == (1, MAX_VARIETY_NEW_VALUES)
    assert values["items"] == {"type": "string", "maxLength": MAX_VARIETY_VALUE_CHARS}
    assert item["properties"]["rationale"]["maxLength"] == MAX_VARIETY_RATIONALE_CHARS
    assert refused["required"] == ["schema", "status", "refusal_reason"]


# -- validator -----------------------------------------------------------------------------------------------------------


def test_a_valid_answer_becomes_typed_slot_values() -> None:
    result = validate_output(
        document([entry(), entry(slot="location", values=["desert", "harbor"])]), REQUEST
    )
    assert result.code is OutcomeCode.SUGGESTION and result.suggestion is not None
    assert result.suggestion.slot_values == (
        SlotValues("lighting", ("golden hour",), "warmer light"),
        SlotValues("location", ("desert", "harbor"), "warmer light"),
    )
    assert result.suggestion.to_diagnostics()["slot_count"] == 2
    assert result.suggestion.to_diagnostics()["value_count"] == 3


@pytest.mark.parametrize(
    ("slots", "reason"),
    [
        ([], "slots_missing"),
        ("lighting", "slots_missing"),
        ([entry(), entry(slot="location"), entry(slot="lighting")], "too_many_slots"),
        ([entry(slot="weather")], "slot_not_in_closed_list"),
        ([entry(), entry()], "slot_repeated"),
        ([entry(values=[])], "values_missing"),
        ([entry(values=["a"] * (MAX_VARIETY_NEW_VALUES + 1))], "too_many_values"),
        ([entry(values=["x" * (MAX_VARIETY_VALUE_CHARS + 1)])], "value_too_long"),
        ([entry(values=[3])], "value_not_text"),
        ([entry(values=[None])], "value_not_text"),
        ([entry(values=["a\x07"])], "value_control_characters"),
        ([entry(rationale="")], "rationale_missing"),
        ([entry(rationale="r" * (MAX_VARIETY_RATIONALE_CHARS + 1))], "rationale_too_long"),
        ([{"slot": "lighting", "values": ["a"]}], "slot_fields_invalid"),
        ([{**entry(), "extra": 1}], "slot_fields_invalid"),
    ],
)
def test_structural_problems_are_malformed_and_never_repaired(slots, reason) -> None:
    result = validate_output(document(slots), REQUEST)
    assert (result.code, result.reason) == (OutcomeCode.MALFORMED, reason)


def test_the_two_field_and_payload_free_answers_are_malformed() -> None:
    two_field = json.dumps({"schema": SUGGESTION_SCHEMA_ID, "status": "ok"})
    assert validate_output(two_field, REQUEST).reason == "kind_mismatch"
    no_slots = json.dumps({"schema": SUGGESTION_SCHEMA_ID, "status": "ok", "kind": "slot_variety"})
    assert validate_output(no_slots, REQUEST).reason == "slots_missing"


def test_other_fields_cannot_ride_along_and_slots_belong_to_this_kind() -> None:
    assert (
        validate_output(document([entry()], positive="x"), REQUEST).reason
        == "unexpected_text_field"
    )
    plan = json.dumps(
        {
            "schema": SUGGESTION_SCHEMA_ID,
            "status": "ok",
            "kind": "slot_variety",
            "slots": [entry()],
            "steps": [],
        }
    )
    assert validate_output(plan, REQUEST).reason == "unexpected_steps_field"
    rewrite = AssistRequest("r1", SuggestionKind.PROMPT_REWRITE, "a barn")
    doc = json.dumps(
        {
            "schema": SUGGESTION_SCHEMA_ID,
            "status": "ok",
            "kind": "prompt_rewrite",
            "positive": "a barn",
            "negative": "",
            "slots": [entry()],
        }
    )
    assert validate_output(doc, rewrite).reason == "unexpected_slots_field"


def test_values_with_list_breaking_characters_pass_structure_for_the_judge_to_reject() -> None:
    # Per-value checks belong to the GUI-side judge, which shows each rejected value with its reason.
    result = validate_output(
        document([entry(values=["", "a, b", "[[x]]", "<lora:x:1>", "two\nlines"])]), REQUEST
    )
    assert result.code is OutcomeCode.SUGGESTION


# -- the real contained service with the fake child ----------------------------------------------------------------------


def test_service_returns_validated_slot_values(installation: Install) -> None:
    outcome = make_service(installation).run(variety_request())
    assert outcome.code is OutcomeCode.SUGGESTION and outcome.suggestion is not None
    assert outcome.suggestion.slot_values[0].values == ("golden hour", "neon glow")


def test_service_rejects_an_invented_slot(installation: Install) -> None:
    outcome = make_service(installation).run(variety_request("variety_invented_slot"))
    assert (outcome.code, outcome.reason) == (OutcomeCode.MALFORMED, "slot_not_in_closed_list")


def test_service_rejects_an_empty_answer(installation: Install) -> None:
    outcome = make_service(installation).run(variety_request("two_field"))
    assert (outcome.code, outcome.reason) == (OutcomeCode.MALFORMED, "kind_mismatch")


def test_a_reserved_marker_in_a_value_spawns_nothing(installation: Install) -> None:
    spy = SpawnSpy()
    service = make_service(installation, runner=spy)
    outcome = service.run(variety_request(matrix_slots=(("lighting", ("SLOT: evil",)),)))
    assert outcome.code is OutcomeCode.INVALID_REQUEST and spy.calls == 0


def test_event_log_and_disk_carry_no_goal_slot_or_value_content(
    installation: Install, caplog: pytest.LogCaptureFixture
) -> None:
    canary = "CANARY-SLOT-7c2a"
    caplog.set_level("DEBUG")
    service = make_service(installation)
    slots = (("lighting", (f"{canary} soft light",)), ("location", ("zanzibar harbor",)))
    request = variety_request(extra=f"{canary} goal", matrix_slots=slots)
    assert service.run(request).ok
    assert service.run(
        variety_request("variety_invented_slot", request_id="v2", matrix_slots=slots)
    ).code is (OutcomeCode.MALFORMED)
    raw = events_path(installation.root).read_text(encoding="utf-8")
    for forbidden in (
        canary,
        "zanzibar",
        "lighting",
        "location",
        "golden hour",
        "neon glow",
        "warmer",
        "weather",
    ):
        assert forbidden not in raw, forbidden
    records = [json.loads(line) for line in raw.splitlines()]
    assert [r["kind"] for r in records] == ["slot_variety", "slot_variety"]
    assert all(set(r) <= ALLOWED_FIELDS for r in records)
    assert {"slots", "matrix_slots", "values", "goal", "goal_text"}.isdisjoint(ALLOWED_FIELDS)
    assert records[0]["input_chars"] == request.input_chars()
    assert canary not in caplog.text and "zanzibar" not in caplog.text
    for path in installation.root.rglob("*"):
        if path.is_file():
            assert canary.encode() not in path.read_bytes(), path


def test_content_class_is_carried_like_other_prompt_requests() -> None:
    assert variety_request(content_class="sensitive").content_class == "sensitive"
    with pytest.raises(ValueError):
        variety_request(content_class="adult")
