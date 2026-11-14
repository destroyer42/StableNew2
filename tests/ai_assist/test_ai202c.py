"""AI-202c: the production output schema forces a complete answer, and the runtime detail names the validation reason.

Hermetic. No llama.cpp binary, grammar converter or model is run: the schema is checked against a small validator that
accepts ONLY the JSON Schema constructs the two pinned llama.cpp tags convert (see the AI-202 work package, section 10), so
a later edit that reaches for an unproven keyword fails here instead of on the owner's machine.
"""

from __future__ import annotations

import json
from typing import Any

import pytest

from src.ai_assist import framing, validators
from src.ai_assist.contracts import (
    CHANGE_CODES,
    MAX_PLAN_STEPS,
    MAX_RUNTIME_DETAIL_BYTES,
    SUGGESTION_SCHEMA_ID,
    AssistRequest,
    OutcomeCode,
    RuntimeDetail,
    SuggestionKind,
)
from src.gui_v2.ai_suggestion_view import runtime_detail_text

from .conftest import Install, request_for
from .test_service_runtime import make_service

#: Keywords proven supported by ``common/json-schema.cpp`` (``common_chat_schema_builder``) in b11840 and b11960.
SUPPORTED_KEYWORDS = frozenset(
    {
        "oneOf",
        "type",
        "const",
        "enum",
        "properties",
        "required",
        "additionalProperties",
        "items",
        "minItems",
        "maxItems",
        "maxLength",
        "minimum",
        "maximum",
    }
)
SUPPORTED_TYPES = frozenset({"object", "array", "string", "integer"})

REWRITE = AssistRequest(
    request_id="s1",
    kind=SuggestionKind.PROMPT_REWRITE,
    positive_text="a red barn <lora:barn:0.8> in [[season]]",
    negative_text="blurry",
)
TARGET = AssistRequest(
    request_id="s2",
    kind=SuggestionKind.TARGET_FIT_ADVICE,
    positive_text="a barn",
    allowed_targets=("sdxl", "klein"),
)
WORKFLOW = AssistRequest(
    request_id="s3",
    kind=SuggestionKind.WORKFLOW_CHOICE,
    positive_text="a barn",
    allowed_workflows=("wan22_ti2v_5b", "svd_xt"),
)
PLAN = AssistRequest(
    request_id="s4",
    kind=SuggestionKind.PLAN_PROPOSAL,
    goal_text="a poster, then animate it",
    allowed_targets=("sdxl",),
    allowed_workflows=("svd_xt",),
    allowed_stages=("txt2img", "video"),
)
REQUESTS = {r.kind: r for r in (REWRITE, TARGET, WORKFLOW, PLAN)}

#: One document the validator accepts for each kind (``changes`` omitted: it is the only optional field).
ACCEPTED: dict[SuggestionKind, dict[str, Any]] = {
    SuggestionKind.PROMPT_REWRITE: {
        "schema": SUGGESTION_SCHEMA_ID,
        "status": "ok",
        "kind": "prompt_rewrite",
        "positive": "a red barn <lora:barn:0.8> in [[season]], golden hour",
        "negative": "blurry",
    },
    SuggestionKind.TARGET_FIT_ADVICE: {
        "schema": SUGGESTION_SCHEMA_ID,
        "status": "ok",
        "kind": "target_fit_advice",
        "target": "klein",
    },
    SuggestionKind.WORKFLOW_CHOICE: {
        "schema": SUGGESTION_SCHEMA_ID,
        "status": "ok",
        "kind": "workflow_choice",
        "workflow": "svd_xt",
    },
    SuggestionKind.PLAN_PROPOSAL: {
        "schema": SUGGESTION_SCHEMA_ID,
        "status": "ok",
        "kind": "plan_proposal",
        "steps": [
            {
                "stage": "txt2img",
                "target": "sdxl",
                "workflow": None,
                "count": 2,
                "rationale": "A still first.",
            },
            {
                "stage": "video",
                "target": None,
                "workflow": "svd_xt",
                "count": 1,
                "rationale": "Then one clip.",
            },
        ],
    },
}
REFUSED = {"schema": SUGGESTION_SCHEMA_ID, "status": "refused", "refusal_reason": "cannot help"}
#: Fields the schema requires although the validator would tolerate their absence (the schema is the stricter of the two).
SCHEMA_STRICTER_THAN_VALIDATOR = {
    SuggestionKind.PROMPT_REWRITE: {"negative"},
    SuggestionKind.TARGET_FIT_ADVICE: set(),
    SuggestionKind.WORKFLOW_CHOICE: set(),
    SuggestionKind.PLAN_PROPOSAL: set(),
}


def conforms(value: Any, schema: dict[str, Any]) -> bool:
    """Whether ``value`` satisfies ``schema``, for the supported keyword subset only (anything else raises)."""

    unknown = set(schema) - SUPPORTED_KEYWORDS
    assert not unknown, f"unproven JSON Schema keyword(s): {sorted(unknown)}"
    if "oneOf" in schema:
        assert set(schema) == {"oneOf"}, "llama.cpp ignores keywords next to oneOf"
        return any(conforms(value, branch) for branch in schema["oneOf"])
    if "const" in schema:
        return value == schema["const"] and type(value) is type(schema["const"])
    if "enum" in schema:
        assert schema["enum"], "llama.cpp refuses an empty enum"
        return any(value == item and type(value) is type(item) for item in schema["enum"])
    kind = schema.get("type")
    assert kind in SUPPORTED_TYPES, f"unproven type {kind!r}"
    if kind == "object":
        if not isinstance(value, dict):
            return False
        properties = schema.get("properties", {})
        assert schema.get("additionalProperties") is False, "every object must be closed"
        if set(value) - set(properties):
            return False
        if not set(schema.get("required", [])) <= set(value):
            return False
        return all(conforms(value[name], properties[name]) for name in value)
    if kind == "array":
        if not isinstance(value, list):
            return False
        if len(value) < schema.get("minItems", 0) or len(value) > schema.get("maxItems", 10**9):
            return False
        return all(conforms(item, schema["items"]) for item in value)
    if kind == "string":
        return isinstance(value, str) and len(value) <= schema.get("maxLength", 10**9)
    return (
        isinstance(value, int)
        and not isinstance(value, bool)
        and schema.get("minimum", value) <= value <= schema.get("maximum", value)
    )


def schema_nodes(schema: dict[str, Any]):
    """Every node in schema position (the root, ``oneOf`` branches, property values and ``items``), not property maps."""

    yield schema
    for branch in schema.get("oneOf", []):
        yield from schema_nodes(branch)
    for child in schema.get("properties", {}).values():
        yield from schema_nodes(child)
    if "items" in schema:
        yield from schema_nodes(schema["items"])


def verdict(document: dict[str, Any], kind: SuggestionKind) -> OutcomeCode:
    return validators.validate_output(json.dumps(document), REQUESTS[kind]).code


@pytest.mark.parametrize("kind", list(SuggestionKind))
def test_the_two_field_document_is_rejected_by_the_schema_and_by_the_validator(
    kind: SuggestionKind,
) -> None:
    schema = framing.build_json_schema(REQUESTS[kind])
    two_fields = {"schema": SUGGESTION_SCHEMA_ID, "status": "ok"}
    assert not conforms(two_fields, schema)
    assert verdict(two_fields, kind) is OutcomeCode.MALFORMED
    # Nor can the document stop after the kind: the payload is required too.
    assert not conforms({**two_fields, "kind": kind.value}, schema)


@pytest.mark.parametrize("kind", list(SuggestionKind))
def test_each_validator_accepted_document_satisfies_the_schema(kind: SuggestionKind) -> None:
    schema = framing.build_json_schema(REQUESTS[kind])
    assert verdict(ACCEPTED[kind], kind) is OutcomeCode.SUGGESTION
    assert conforms(ACCEPTED[kind], schema)
    with_changes = {**ACCEPTED[kind], "changes": sorted(CHANGE_CODES)[:2]}
    assert verdict(with_changes, kind) is OutcomeCode.SUGGESTION and conforms(with_changes, schema)
    assert verdict(REFUSED, kind) is OutcomeCode.REFUSED_BY_MODEL and conforms(REFUSED, schema)


@pytest.mark.parametrize("kind", list(SuggestionKind))
def test_the_schema_requires_what_the_validator_requires(kind: SuggestionKind) -> None:
    """Drift guard: the required fields are measured from the validator, not restated from the schema."""

    request = REQUESTS[kind]
    ok_branch = framing.build_json_schema(request)["oneOf"][0]
    schema_required = set(ok_branch["required"])
    validator_required = {
        key
        for key in ACCEPTED[kind]
        if verdict({k: v for k, v in ACCEPTED[kind].items() if k != key}, kind)
        is not OutcomeCode.SUGGESTION
    }
    assert validator_required <= schema_required
    assert schema_required - validator_required == SCHEMA_STRICTER_THAN_VALIDATOR[kind]
    # Every optional property is genuinely optional for the validator, and every property is one it knows.
    for key in set(ok_branch["properties"]) - schema_required:
        assert verdict(ACCEPTED[kind], kind) is OutcomeCode.SUGGESTION
        assert key == "changes"
    assert set(ok_branch["properties"]) <= validators._ALLOWED_KEYS
    # A payload field of another kind is rejected by both.
    foreign = {"positive": "x", "target": "sdxl", "workflow": "svd_xt", "steps": []}
    for key, value in foreign.items():
        if key in ok_branch["properties"]:
            continue
        mixed = {**ACCEPTED[kind], key: value}
        assert not conforms(mixed, framing.build_json_schema(request))
        assert verdict(mixed, kind) is OutcomeCode.MALFORMED


@pytest.mark.parametrize("kind", list(SuggestionKind))
def test_the_schema_has_the_decided_shape(kind: SuggestionKind) -> None:
    schema = framing.build_json_schema(REQUESTS[kind])
    assert set(schema) == {"oneOf"} and len(schema["oneOf"]) == 2
    ok_branch, refused_branch = schema["oneOf"]
    assert ok_branch["properties"]["status"] == {"const": "ok"}
    assert refused_branch["properties"]["status"] == {"const": "refused"}
    assert list(ok_branch["properties"])[:3] == ["schema", "status", "kind"]
    assert list(refused_branch["properties"]) == ["schema", "status", "refusal_reason"]
    assert refused_branch["required"] == ["schema", "status", "refusal_reason"]
    assert ok_branch["required"][:3] == ["schema", "status", "kind"]
    assert "changes" in ok_branch["properties"] and "changes" not in ok_branch["required"]
    for node in schema_nodes(schema):
        assert set(node) <= SUPPORTED_KEYWORDS, sorted(set(node) - SUPPORTED_KEYWORDS)
        if node.get("type") == "object":
            assert node["additionalProperties"] is False


def test_the_payload_requirements_are_per_kind() -> None:
    required = {
        kind: framing.build_json_schema(REQUESTS[kind])["oneOf"][0]["required"] for kind in REQUESTS
    }
    assert required[SuggestionKind.PROMPT_REWRITE][3:] == ["positive", "negative"]
    assert required[SuggestionKind.TARGET_FIT_ADVICE][3:] == ["target"]
    assert required[SuggestionKind.WORKFLOW_CHOICE][3:] == ["workflow"]
    assert required[SuggestionKind.PLAN_PROPOSAL][3:] == ["steps"]
    steps = framing.build_json_schema(PLAN)["oneOf"][0]["properties"]["steps"]
    assert steps["minItems"] == 1 and steps["maxItems"] == MAX_PLAN_STEPS


def test_choices_stay_pinned_to_the_closed_lists() -> None:
    target = {**ACCEPTED[SuggestionKind.TARGET_FIT_ADVICE], "target": "evil"}
    assert not conforms(target, framing.build_json_schema(TARGET))
    plan = json.loads(json.dumps(ACCEPTED[SuggestionKind.PLAN_PROPOSAL]))
    plan["steps"][0]["count"] = 99
    assert not conforms(plan, framing.build_json_schema(PLAN))
    plan["steps"][0]["count"] = 1
    plan["steps"][0]["stage"] = "inpaint"
    assert not conforms(plan, framing.build_json_schema(PLAN))


def test_the_runtime_writes_the_schema_in_declared_order(installation: Install, tmp_path) -> None:
    """llama.cpp emits properties in file order, so the file must keep ``schema``, ``status``, ``kind`` first."""

    record = tmp_path / "record.json"
    outcome = make_service(installation).run(request_for("ok", extra=f"TEST_RECORD:{record}"))
    assert outcome.ok
    seen = json.loads(record.read_text(encoding="utf-8"))
    text = seen.get("schema_text")
    assert text is not None, "the fake child must record the schema file it was given"
    document = json.loads(text)
    assert list(document["oneOf"][0]["properties"])[:3] == ["schema", "status", "kind"]


# -- the review dialog's runtime detail -----------------------------------------------------------------------------------


def test_runtime_detail_names_the_reason_and_puts_stdout_above_stderr() -> None:
    detail = RuntimeDetail(
        exit_code=0,
        reason="kind_mismatch",
        stderr_tail="load_tensors: done\nsystem_info: n_threads = 8",
        stdout_head='{"schema": "ai_assist.suggestion/1", "status": "ok"}',
    )
    text = runtime_detail_text(detail)
    assert text.startswith("Exit code: 0\nReason: kind_mismatch")
    assert text.index("stdout (first part):") < text.index("stderr (last part):")
    assert '"status": "ok"' in text


def test_runtime_detail_without_a_reason_is_unchanged_in_shape() -> None:
    text = runtime_detail_text(RuntimeDetail(exit_code=7, stderr_tail="boom"))
    assert text == "Exit code: 7\n\nstderr (last part):\nboom"
    assert runtime_detail_text(None) == ""


def test_a_malformed_outcome_carries_its_validation_reason_in_memory_only(
    installation: Install,
) -> None:
    outcome = make_service(installation).run(request_for("two_field"))
    assert (outcome.code, outcome.reason) == (OutcomeCode.MALFORMED, "kind_mismatch")
    detail = outcome.runtime_detail
    assert detail is not None and detail.reason == "kind_mismatch"
    assert '"status": "ok"' in detail.stdout_head
    assert len(detail.stdout_head.encode("utf-8")) <= MAX_RUNTIME_DETAIL_BYTES
    shown = runtime_detail_text(detail)
    assert "Reason: kind_mismatch" in shown
    assert "stdout (first part):" in shown
    log_text = (installation.root / "events.jsonl").read_text(encoding="utf-8")
    assert detail.stdout_head not in log_text and "stdout (first part)" not in log_text
    assert "kind_mismatch" in log_text  # the reason code is content-free and is recorded, as before


def test_a_runtime_failure_also_shows_its_reason(installation: Install) -> None:
    outcome = make_service(installation).run(request_for("stderr_fail"))
    detail = outcome.runtime_detail
    assert detail is not None and detail.reason == "child_exit_nonzero"
    assert "Reason: child_exit_nonzero" in runtime_detail_text(detail)
