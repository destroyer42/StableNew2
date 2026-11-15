"""PR-AI-VL-222: the visual diagnostic (why the first LFM3-VL-2B synthetic run scored near zero, and what was fixed).

Hermetic, like the AI-VL-220 tests: the child is a Python script standing in for ``llama-mtmd-cli.exe``, launched through the real
``run_bounded``; no llama.cpp binary and no model is run, no GPU is touched, nothing is written under the real AI Assist root.

Covers: the scoring self-test (the by-construction answers score perfectly, and what plausible near-misses score), the per-case
response schema, the rendered prompts, the second (512 px) synthetic set and the unchanged first one, the diagnostic capture and
its refusal for any other case set, the free-text control and the closed argv vocabulary.
"""

# ruff: noqa: F811
from __future__ import annotations

import copy
import json
import re
import subprocess
import sys
import textwrap
from pathlib import Path
from typing import Any

import pytest

from tests.tools.test_ai_vl220_invocation import World, cli_args, world  # noqa: F401  (fixture)
from tools.qualification.vl220 import __main__ as cli
from tools.qualification.vl220 import (
    contract,
    diagnostics,
    driver,
    plan,
    prompts,
    scoring,
    synthetic,
    visual_argv,
)
from tools.qualification.vl220.contract import ContractViolation

REPO = Path(__file__).resolve().parents[2]

#: The first synthetic set is byte-identical to the one the first supervised run used (its evidence file pins the case digest).
SET1_CASE_SHA256 = "9c11172fa6af8d080673cf2c89ca6b87a7404cbcc439425cc9e726e197e0ccd1"
SET1_LABEL_SHA256 = "6598abbfac6385c976cf886e84cd4767cc74408607757125dca47aeeb72716dc"
SET512_CASE_SHA256 = "33c0f6e164970c576ea5a58efa8dc6bd7239d5bf26aca7b7ada71ad41f7ca721"
SET512_LABEL_SHA256 = "f81cc805b380d9ca2b70c2d86ce21ff83d3d79ddc722c0e9338a3f47b0f8e08f"
#: The generic per-kind schemas did not change (the plan of the first run carried these digests).
KIND_SCHEMA_SHA256 = {
    "adherence": "078f19472a9452eb5adf4c859e91ef27bdaaa002ea1ffc9a1332576c1fd1eebb",
    "defect_triage": "5d3f76df83e545e405ef6fad3ca887967bd2951884abbe2d20d04893d3e6a8ba",
    "consistency": "ca9359562aa26a4e716cb591808ed91f98f9f444fdd5a866c96730d172132b5a",
    "before_after": "2c7a6d38a03a5a2924249da0131075c861a2146e34daf03ee05e02922cf4c30e",
    "describe": "a75a0f6283a84dbf6a76d16fffa277c216a30a3687acaf5d566d5706d4a35f7c",
}

SET_IDS = (synthetic.SET_ID, synthetic.SET_ID_512)


def load(set_id: str) -> tuple[contract.CaseSet, contract.LabelSet, dict[str, Any], dict[str, Any]]:
    _, case_doc, label_doc = synthetic.build_synthetic_set(set_id)
    case_set = contract.validate_case_set(copy.deepcopy(case_doc))
    return (
        case_set,
        contract.validate_label_set(copy.deepcopy(label_doc), case_set),
        case_doc,
        label_doc,
    )


def oracle(case_set: contract.CaseSet, labels: contract.LabelSet) -> dict[str, str]:
    """The by-construction reference answers, written the way the contract's response shape asks."""

    out: dict[str, str] = {}
    for case in case_set.cases:
        reference = labels.references[case.case_id]
        head: dict[str, Any] = {
            "schema": contract.RESPONSE_SCHEMA,
            "status": "ok",
            "kind": case.kind,
        }
        if "answers" in reference:
            head["answers"] = [
                {"id": key, "value": reference["answers"][key]} for key, _ in case.elements
            ]
        elif "findings" in reference:
            head["findings"] = reference["findings"]
        elif "preferred" in reference:
            head.update(preferred=reference["preferred"], reason="more_complete")
        else:
            head["objects"] = list(reference["objects"])
        out[case.case_id] = json.dumps(head)
    return out


def respond(case: contract.Case, **fields: Any) -> str:
    return json.dumps(
        {"schema": contract.RESPONSE_SCHEMA, "status": "ok", "kind": case.kind, **fields}
    )


def named(case_set: contract.CaseSet, case_id: str) -> contract.Case:
    return case_set.case(case_id)


# ======================================================================================== A1: the scoring self-test


@pytest.mark.parametrize("set_id", SET_IDS)
def test_the_by_construction_answers_score_perfectly_on_every_dimension_of_every_case(
    set_id: str,
) -> None:
    case_set, labels, _, _ = load(set_id)
    assert len(case_set.cases) == 13
    responses = oracle(case_set, labels)
    for case in case_set.cases:  # each answer passes the validator on its own
        check = contract.validate_response(case, responses[case.case_id])
        assert check.status == "valid", (case.case_id, check)
    report = scoring.score_run(case_set, labels, responses)
    assert report[contract.DIM_ADHERENCE] == 1.0
    assert report[contract.DIM_CONSISTENCY] == 1.0
    assert report[contract.DIM_BEFORE_AFTER] == 1.0
    assert report[contract.DIM_DEFECT] == {
        "precision": 1.0,
        "recall": 1.0,
        "false_alarm_rate_on_clean_cases": 0.0,
    }
    assert report[contract.DIM_HALLUCINATION] == {
        "unsupported_mention_rate": 0.0,
        "object_recall": 1.0,
    }
    assert report["describe_detail"] == {"generic_mentions": 0}
    structured = report[contract.DIM_STRUCTURED]
    assert (
        structured["valid_rate"],
        structured["invalid_rate"],
        structured["invalid_reasons"],
    ) == (1.0, 0.0, {})


def test_the_two_sets_have_the_same_labels_apart_from_their_set_id() -> None:
    _, _, case1, label1 = load(synthetic.SET_ID)
    _, _, case2, label2 = load(synthetic.SET_ID_512)
    assert {**label1, "set_id": ""} == {**label2, "set_id": ""}
    assert [c["case_id"] for c in case1["cases"]] == [c["case_id"] for c in case2["cases"]]


def describe_report(
    responses: dict[str, str], case_set: Any, labels: Any, case_id: str, objects: Any
) -> Any:
    responses = {**responses, case_id: respond(case_set.case(case_id), objects=objects)}
    return scoring.score_run(case_set, labels, responses)


@pytest.mark.parametrize(
    ("objects", "unsupported", "recall", "generic"),
    [
        # Exactly the reference names, any case, punctuation, article, separator or plural: a perfect answer.
        (["red square", "yellow circle"], 0.0, 1.0, 0),
        (["A Red Square.", "yellow-circle"], 0.0, 1.0, 0),
        (["RED_SQUARES", "the yellow circles"], 0.0, 1.0, 0),
        # The first run's likely failure: bare kinds. Not hallucinations, but they do not name the object asked for.
        (["square", "circle"], 0.0, 1 / 3, 2),
        # A different word, a different color, or something absent is a hallucination.
        (["red rectangle", "yellow circle"], 1 / 3, 2 / 3, 0),
        (["blue square", "yellow circle"], 1 / 3, 2 / 3, 0),
        (["red", "yellow circle"], 1 / 3, 2 / 3, 0),
        ([], None, 1 / 3, 0),
    ],
)
def test_near_miss_object_names_are_scored_as_documented(
    objects: list[str], unsupported: float | None, recall: float, generic: int
) -> None:
    case_set, labels, _, _ = load(synthetic.SET_ID)
    report = describe_report(oracle(case_set, labels), case_set, labels, "describe-1", objects)
    halluc = report[contract.DIM_HALLUCINATION]
    # describe-2 contributes one supported mention (green circle) and one found object.
    expected_rate = None if unsupported is None else unsupported
    if objects == []:
        expected_rate = 0.0  # only describe-2's single supported mention remains
    assert halluc["unsupported_mention_rate"] == pytest.approx(expected_rate, abs=1e-5)
    assert halluc["object_recall"] == pytest.approx(recall, abs=1e-5)
    assert report["describe_detail"]["generic_mentions"] == generic


def test_correct_verdicts_under_the_wrong_ids_are_invalid_not_guessed() -> None:
    case_set, labels, _, _ = load(synthetic.SET_ID)
    case = named(case_set, "adherence-1")
    reference = labels.references["adherence-1"]["answers"]
    base = oracle(case_set, labels)
    swapped = respond(
        case, answers=[{"id": "a", "value": reference["e1"]}, {"id": "b", "value": reference["e2"]}]
    )
    report = scoring.score_run(case_set, labels, {**base, "adherence-1": swapped})
    assert report[contract.DIM_ADHERENCE] == pytest.approx(4 / 6, abs=1e-5)
    assert report[contract.DIM_STRUCTURED]["invalid_reasons"] == {
        "answers_do_not_match_elements": 1
    }
    reordered = respond(
        case,
        answers=[{"id": "e2", "value": reference["e2"]}, {"id": "e1", "value": reference["e1"]}],
    )
    report = scoring.score_run(case_set, labels, {**base, "adherence-1": reordered})
    assert report[contract.DIM_STRUCTURED]["invalid_reasons"] == {"answers_out_of_order": 1}
    assert report[contract.DIM_ADHERENCE] == pytest.approx(4 / 6, abs=1e-5)


def test_a_defect_list_for_a_clean_figure_is_a_false_alarm() -> None:
    case_set, labels, _, _ = load(synthetic.SET_ID)
    clean = named(case_set, "defect-1")
    assert labels.references["defect-1"]["findings"] == []
    claim = [{"region": "arms", "category": "extra_limb", "severity": "major"}]
    report = scoring.score_run(
        case_set, labels, {**oracle(case_set, labels), "defect-1": respond(clean, findings=claim)}
    )
    assert report[contract.DIM_DEFECT] == {
        "precision": pytest.approx(3 / 4, abs=1e-5),
        "recall": 1.0,
        "false_alarm_rate_on_clean_cases": 1.0,
    }


def test_a_defect_in_the_wrong_region_or_category_is_both_a_miss_and_a_false_positive() -> None:
    case_set, labels, _, _ = load(synthetic.SET_ID)
    case = named(case_set, "defect-2")  # an extra arm
    wrong = [{"region": "legs", "category": "extra_limb", "severity": "major"}]
    report = scoring.score_run(
        case_set, labels, {**oracle(case_set, labels), "defect-2": respond(case, findings=wrong)}
    )
    assert report[contract.DIM_DEFECT]["recall"] == pytest.approx(2 / 3, abs=1e-5)
    assert report[contract.DIM_DEFECT]["precision"] == pytest.approx(2 / 3, abs=1e-5)


def test_normalization_does_not_widen_what_counts_as_the_same_object() -> None:
    normal = scoring._normal  # noqa: SLF001 - the unit under test
    assert (
        normal("A Red-Square.") == normal("red_squares") == normal("the red square") == "red square"
    )
    assert normal("glass") == "glass" and normal("circles") == "circle"
    assert normal("red rectangle") != normal("red square") and normal("blue square") != normal(
        "red square"
    )


# ================================================================================================ A2/A4: per-case schema

ALLOWED_KEYWORDS = {
    "oneOf", "const", "enum", "required", "properties", "additionalProperties", "type", "items", "prefixItems", "minItems",
    "maxItems", "maxLength",
}  # fmt: skip


def schema_ok(schema: dict[str, Any], value: Any) -> bool:
    """A minimal checker for exactly the keyword subset a response schema may use (llama.cpp's converter supports each)."""

    assert set(schema) <= ALLOWED_KEYWORDS, set(schema) - ALLOWED_KEYWORDS
    if "oneOf" in schema:
        return any(schema_ok(branch, value) for branch in schema["oneOf"])
    if "const" in schema:
        return bool(value == schema["const"])
    if "enum" in schema:
        return value in schema["enum"]
    kind = schema.get("type")
    if kind == "boolean":
        return isinstance(value, bool)
    if kind == "string":
        return isinstance(value, str) and len(value) <= schema.get("maxLength", 10**9)
    if kind == "array":
        if (
            not isinstance(value, list)
            or not schema["minItems"] <= len(value) <= schema["maxItems"]
        ):
            return False
        if "prefixItems" in schema:
            return len(value) == len(schema["prefixItems"]) and all(
                schema_ok(part, item)
                for part, item in zip(schema["prefixItems"], value, strict=True)
            )
        return all(schema_ok(schema["items"], item) for item in value)
    assert kind == "object"
    if not isinstance(value, dict):
        return False
    if schema.get("additionalProperties") is False and set(value) - set(schema["properties"]):
        return False
    if set(schema["required"]) - set(value):
        return False
    return all(schema_ok(schema["properties"][key], item) for key, item in value.items())


def test_the_generic_kind_schemas_are_unchanged() -> None:
    for kind in contract.KINDS:
        assert contract.digest(contract.build_response_schema(kind)) == KIND_SCHEMA_SHA256[kind]
    assert plan.build_plan()["response_schema_digests"] == KIND_SCHEMA_SHA256


@pytest.mark.parametrize("set_id", SET_IDS)
def test_an_element_case_schema_pins_each_answer_id_in_order(set_id: str) -> None:
    case_set, labels, _, _ = load(set_id)
    answers = oracle(case_set, labels)
    for case in case_set.cases:
        schema = contract.build_response_schema(case.kind, case)
        assert schema_ok(schema, json.loads(answers[case.case_id])), case.case_id
        assert schema_ok(
            schema,
            {"schema": contract.RESPONSE_SCHEMA, "status": "refused", "refusal_reason": "no"},
        )
        if case.kind not in (contract.KIND_ADHERENCE, contract.KIND_CONSISTENCY):
            continue
        ok = schema["oneOf"][0]["properties"]["answers"]
        ids = [part["properties"]["id"]["const"] for part in ok["prefixItems"]]
        assert ids == [key for key, _ in case.elements]
        assert ok["minItems"] == ok["maxItems"] == len(case.elements)
        document = json.loads(answers[case.case_id])
        wrong_id = copy.deepcopy(document)
        wrong_id["answers"][0]["id"] = "zz"
        short = {**document, "answers": document["answers"][:1]}
        repeated = {**document, "answers": [document["answers"][0]] * len(document["answers"])}
        for bad in (wrong_id, short, repeated):
            assert not schema_ok(schema, bad)
            assert contract.validate_response(case, json.dumps(bad)).status == "invalid"


def test_the_decoder_schema_never_accepts_what_the_validator_rejects() -> None:
    for set_id in SET_IDS:
        case_set, labels, _, _ = load(set_id)
        answers = oracle(case_set, labels)
        for case in case_set.cases:
            schema = contract.build_response_schema(case.kind, case)
            document = json.loads(answers[case.case_id])
            variants = [document]
            if "answers" in document:
                variants.append({**document, "answers": list(reversed(document["answers"]))})
            if "objects" in document:
                variants.append({**document, "objects": [*document["objects"], "purple dragon"]})
                variants.append({**document, "objects": [*document["objects"], "x" * 41]})
            for variant in variants:
                if schema_ok(schema, variant):
                    # What the decoder lets through the validator also accepts (the validator is never looser).
                    assert (
                        contract.validate_response(case, json.dumps(variant)).status == "valid"
                    ), variant
                if contract.validate_response(case, json.dumps(variant)).status == "valid":
                    assert schema_ok(schema, variant)


def test_a_closed_vocabulary_constrains_the_schema_and_the_validator_alike() -> None:
    case_set, labels, _, _ = load(synthetic.SET_ID_512)
    describe = named(case_set, "describe-1")
    assert describe.vocabulary == tuple(synthetic.object_names()) and len(describe.vocabulary) == 8
    schema = contract.build_response_schema(describe.kind, describe)
    items = schema["oneOf"][0]["properties"]["objects"]["items"]
    assert items == {"enum": list(describe.vocabulary)}
    assert contract.validate_response(describe, respond(describe, objects=["red square"])).valid
    for outside in (["purple dragon"], ["red square", "blue triangle"]):
        check = contract.validate_response(describe, respond(describe, objects=outside))
        assert (check.status, check.reason) == ("invalid", "object_outside_vocabulary")
    # The first set's describe cases have no vocabulary: free names, as in the first run.
    first, _, _, _ = load(synthetic.SET_ID)
    assert named(first, "describe-1").vocabulary == ()
    assert contract.validate_response(
        named(first, "describe-1"), respond(named(first, "describe-1"), objects=["anything"])
    ).valid


def test_a_vocabulary_is_only_for_describe_cases_and_must_be_a_proper_list() -> None:
    for change, code in (
        (lambda d: d["cases"][0].update(vocabulary=["red square"]), "unexpected_vocabulary"),
        (lambda d: d["cases"][-1].update(vocabulary=["a", "a"]), "duplicate_vocabulary_name"),
        (lambda d: d["cases"][-1].update(vocabulary=[]), "bad_list"),
        (lambda d: d["cases"][-1].update(vocabulary=["x" * 41]), "bad_object_name"),
        (lambda d: d["cases"][-1].update(vocabulary="red square"), "bad_list"),
    ):
        _, _, case_doc, _ = load(synthetic.SET_ID)
        change(case_doc)
        with pytest.raises(ContractViolation) as caught:
            contract.validate_case_set(case_doc)
        assert caught.value.code == code
    with pytest.raises(ContractViolation):
        contract.build_response_schema("describe", named(load(synthetic.SET_ID)[0], "adherence-1"))


def test_the_plan_digest_covers_every_prompt_and_per_case_schema_of_both_sets() -> None:
    section = plan.build_plan()["diagnostic"]
    assert section["decision"] == "D23" and set(section["sets"]) == set(SET_IDS)
    assert (
        section["invocation_unchanged"]["new_flags"] == []
        and section["invocation_unchanged"]["jinja"] == "refused"
    )
    for set_id in SET_IDS:
        case_set, _, case_doc, label_doc = load(set_id)
        entry = section["sets"][set_id]
        assert entry["case_set_sha256"] == contract.digest(case_doc)
        assert entry["label_set_sha256"] == contract.digest(label_doc)
        assert set(entry["requests"]) == {case.case_id for case in case_set.cases}
        assert [row["request_id"] for row in entry["controls"]] == [
            "control-describe-1",
            "control-describe-2",
        ]
    assert section["invocations"] == 2 * (13 + 2)


# ================================================================================================= A2: rendered prompts


@pytest.mark.parametrize("set_id", SET_IDS)
def test_every_rendered_prompt_carries_the_request_the_ids_the_shape_and_the_naming_rule(
    set_id: str,
) -> None:
    case_set, _, _, _ = load(set_id)
    for case in case_set.cases:
        text = prompts.render_visual_prompt(case)
        assert text == prompts.render_visual_prompt(case) and f"Request: {case.prompt}" in text
        assert "Answer shape: {" in text and f'"kind":"{case.kind}"' in text
        assert '"value":true' not in text and "<true or false>" in text or case.kind not in (
            contract.KIND_ADHERENCE, contract.KIND_CONSISTENCY
        )  # fmt: skip
        assert not re.search(r"reference|ground.?truth|label", text, re.IGNORECASE)
        if case.elements:
            for key, element in case.elements:
                assert (
                    f"- {key}: {element}" in text
                    and f'{{"id":"{key}","value":<true or false>}}' in text
                )
            ids = [key for key, _ in case.elements]
            assert f"using exactly these ids: {', '.join(ids)}." in text
        if case.kind == contract.KIND_DESCRIBE:
            assert "Name each object with its color and its kind" in text
            if case.vocabulary:
                assert all(name in text for name in case.vocabulary)
        if case.kind == contract.KIND_BEFORE_AFTER:
            assert "image a is the first and image b is the second" in text
        if case.kind == contract.KIND_DEFECT:
            assert "extra_limb means more arms or legs" in text


def test_the_control_prompt_is_free_text_with_no_json_or_schema_wording() -> None:
    text = prompts.render_control_prompt()
    assert (
        text == prompts.CONTROL_PROMPT + "\n"
        and "JSON" not in text
        and "schema" not in text.lower()
    )


def test_the_work_package_prints_the_rendered_prompts_it_describes() -> None:
    document = (REPO / "docs/work_packages/AI-VL-222_visual_diagnostic.md").read_text(
        encoding="utf-8"
    )
    case_set, _, _, _ = load(synthetic.SET_ID)
    for kind in contract.KINDS:
        case = next(c for c in case_set.cases if c.kind == kind)
        assert prompts.render_visual_prompt(case).strip() in document, kind
    big, _, _, _ = load(synthetic.SET_ID_512)
    assert prompts.render_visual_prompt(named(big, "describe-1")).strip() in document
    assert prompts.CONTROL_PROMPT in document
    assert plan.build_plan()["plan_sha256"] in document


# ======================================================================================== A5: the two synthetic sets


def test_the_first_set_is_byte_identical_to_the_one_the_first_run_used() -> None:
    _, _, case_doc, label_doc = load(synthetic.SET_ID)
    assert contract.digest(case_doc) == SET1_CASE_SHA256
    assert contract.digest(label_doc) == SET1_LABEL_SHA256
    assert case_doc["set_id"] == "vl220-synthetic-1"


def test_the_larger_set_has_its_own_pins_and_the_same_scenes_drawn_larger() -> None:
    images1, case1, _ = synthetic.build_synthetic_set(synthetic.SET_ID)
    images4, case4, label4 = synthetic.build_synthetic_set(synthetic.SET_ID_512)
    assert (
        contract.digest(case4) == SET512_CASE_SHA256
        and contract.digest(label4) == SET512_LABEL_SHA256
    )
    assert case4["set_id"] == "vl220-synthetic-512-1" and set(images4) == set(images1)
    pinned = {asset["asset_id"]: asset for asset in case4["assets"]}
    for asset_id, data in images4.items():
        width, height = (int.from_bytes(data[16:20], "big"), int.from_bytes(data[20:24], "big"))
        small = images1[asset_id]
        small_w, small_h = (
            int.from_bytes(small[16:20], "big"),
            int.from_bytes(small[20:24], "big"),
        )
        assert (width, height) == (4 * small_w, 4 * small_h) and height == 512
        assert (
            pinned[asset_id]["sha256"]
            != next(a for a in case1["assets"] if a["asset_id"] == asset_id)["sha256"]
        )
        assert len(data) <= visual_argv.MAX_IMAGE_BYTES and pinned[asset_id]["bytes"] == len(data)
    # The scenes are the same: the center of every drawn shape has the same color at both sizes.
    for asset_id in ("adh-1", "des-1", "des-2", "ba-1-a"):
        for index in range(3):
            x, y = 32 + 32 * index, 64
            pixel1 = _pixel(images1[asset_id], x, y)
            pixel4 = _pixel(images4[asset_id], 4 * x, 4 * y)
            assert pixel1 == pixel4, (asset_id, index)


def _pixel(png: bytes, x: int, y: int) -> bytes:
    import zlib

    width = int.from_bytes(png[16:20], "big")
    start = png.index(b"IDAT") + 4
    raw = zlib.decompress(png[start : png.index(b"IEND") - 8])
    row = 1 + 3 * width
    offset = y * row + 1 + 3 * x
    return raw[offset : offset + 3]


def test_build_synthetic_set_returns_independent_copies_and_refuses_an_unknown_set() -> None:
    _, first, _ = synthetic.build_synthetic_set()
    first["cases"].clear()
    _, again, _ = synthetic.build_synthetic_set()
    assert len(again["cases"]) == 13
    with pytest.raises(KeyError):
        synthetic.build_synthetic_set("vl220-synthetic-9")


def test_a_128_pixel_scene_is_upscaled_by_the_runtime_so_the_set_that_is_larger_is_a_second_wiring_check() -> (
    None
):
    # llama.cpp b11960 smart_resize (tools/mtmd/mtmd-image.cpp:844-848) with the projector's 16-pixel patch and 2x2 merge and
    # --image-min-tokens 64: a 128 x 128 image is below the 65536-pixel floor and is stretched to 256 x 256 -> 8 x 8 = 64 tokens;
    # 512 x 512 sits exactly on the 262144-pixel ceiling of --image-max-tokens 256 and stays 512 -> 16 x 16 = 256 tokens.
    def tokens(width: int, height: int, lo: int = 64, hi: int = 256, f: int = 32) -> int:
        import math

        area = f * f
        h = round(height / f) * f
        w = round(width / f) * f
        if h * w > hi * area:
            beta = math.sqrt(height * width / (hi * area))
            h, w = math.floor(height / beta / f) * f, math.floor(width / beta / f) * f
        elif h * w < lo * area:
            beta = math.sqrt(lo * area / (height * width))
            h, w = math.ceil(height * beta / f) * f, math.ceil(width * beta / f) * f
        return (w // 16 // 2) * (h // 16 // 2)

    assert (
        tokens(128, 128) == 64
        and tokens(512, 512) == 256
        and tokens(256, 128) == 72
        and tokens(1024, 512) == 242
    )


# =========================================================================== B: the capture, its refusal, and the control


def test_a_capture_exists_only_for_exactly_a_builtin_synthetic_set() -> None:
    for set_id in SET_IDS:
        _, _, case_doc, label_doc = load(set_id)
        assert diagnostics.refusal_for(case_doc, label_doc) == ""
        assert diagnostics.DiagnosticCapture(case_doc, label_doc).set_id == set_id
    _, _, case_doc, label_doc = load(synthetic.SET_ID)

    def refused(case: Any, label: Any, code: str) -> None:
        assert diagnostics.refusal_for(case, label) == code
        with pytest.raises(diagnostics.DiagnosticsRefused) as caught:
            diagnostics.DiagnosticCapture(case, label)
        assert caught.value.code == code

    # a human-labeled set, even over the same synthetic images
    refused(case_doc, {**label_doc, "labeler": "human"}, diagnostics.REFUSED_LABELER)
    # a built-in set with one word of one prompt changed, or one asset digest changed
    edited = copy.deepcopy(case_doc)
    edited["cases"][0]["prompt"] += " Please."
    refused(edited, label_doc, diagnostics.REFUSED_NOT_BUILTIN)
    swapped = copy.deepcopy(case_doc)
    swapped["assets"][0]["sha256"] = "0" * 64
    refused(swapped, label_doc, diagnostics.REFUSED_NOT_BUILTIN)
    # labels edited
    relabeled = copy.deepcopy(label_doc)
    relabeled["labels"][0]["reference"]["answers"]["e1"] = not relabeled["labels"][0]["reference"][
        "answers"
    ]["e1"]
    refused(case_doc, relabeled, diagnostics.REFUSED_NOT_BUILTIN)
    # a different set id, existing (non-synthetic) assets with human labels, and non-documents
    other = copy.deepcopy(case_doc)
    other["set_id"] = "someone-elses-set"
    refused(other, label_doc, diagnostics.REFUSED_NOT_BUILTIN)
    existing = copy.deepcopy(case_doc)
    for asset in existing["assets"]:
        asset["origin"] = "existing"
    refused(existing, {**label_doc, "labeler": "human"}, diagnostics.REFUSED_LABELER)
    refused(existing, label_doc, diagnostics.REFUSED_NOT_BUILTIN)
    refused([], label_doc, diagnostics.REFUSED_NOT_BUILTIN)
    refused(case_doc, None, diagnostics.REFUSED_LABELER)


def test_the_cli_refuses_diagnostics_for_any_other_case_set_before_launching_anything(
    world: World,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],  # noqa: F811
) -> None:
    digest = plan.build_plan()["plan_sha256"]
    (world.tmp / "ack.json").write_text("{}", encoding="utf-8")
    _, _, case_doc, label_doc = load(synthetic.SET_ID)
    human = {**label_doc, "labeler": "human"}
    edited = copy.deepcopy(case_doc)
    edited["cases"][0]["prompt"] += " Please."
    for index, (cases, labels) in enumerate(((case_doc, human), (edited, label_doc))):
        (world.tmp / f"c{index}.json").write_text(json.dumps(cases), encoding="utf-8")
        (world.tmp / f"l{index}.json").write_text(json.dumps(labels), encoding="utf-8")
        built: list[Any] = []
        monkeypatch.setattr(driver, "VisualDriver", lambda *a, _built=built, **k: _built.append(1))
        args = cli_args(
            world, digest, "--generation-idle", "--cases", str(world.tmp / f"c{index}.json"),
            "--labels", str(world.tmp / f"l{index}.json"), "--diagnostics-out", str(world.tmp / "diag.json"),
        )  # fmt: skip
        assert cli.main(args) == 2
        assert "diagnostics_" in capsys.readouterr().err
        assert built == [] and world.launches == []
        assert not (world.tmp / "diag.json").exists() and not (world.tmp / "evidence.json").exists()
    # --controls needs --diagnostics-out
    assert cli.main(cli_args(world, digest, "--generation-idle", "--controls")) == 2
    assert "--controls needs --diagnostics-out" in capsys.readouterr().err


def test_diagnostics_are_written_only_outside_git_and_never_over_an_existing_file(
    tmp_path: Path,
) -> None:
    case_set, _, case_doc, label_doc = load(synthetic.SET_ID)
    capture = diagnostics.DiagnosticCapture(case_doc, label_doc)
    document = capture.document(plan_sha256="0" * 64, evidence_file="evidence.json")
    target = tmp_path / "run.diagnostics.json"
    diagnostics.write_diagnostics(target, document)
    assert (
        json.loads(target.read_text(encoding="utf-8"))["schema"] == diagnostics.DIAGNOSTICS_SCHEMA
    )
    with pytest.raises(diagnostics.DiagnosticsRefused) as exists:
        diagnostics.write_diagnostics(target, document)
    assert exists.value.code == diagnostics.REFUSED_EXISTS
    for inside in (REPO / "docs" / "leak.json", REPO / "leak.json", REPO / "tools" / "leak.json"):
        with pytest.raises(diagnostics.DiagnosticsRefused) as refused:
            diagnostics.write_diagnostics(inside, document)
        assert refused.value.code == diagnostics.REFUSED_PATH and not inside.exists()
    with pytest.raises(diagnostics.DiagnosticsRefused):
        diagnostics.write_diagnostics(tmp_path / "missing-dir" / "x.json", document)
    assert case_set.set_id == synthetic.SET_ID


DIAG_CHILD = textwrap.dedent(
    r"""
    import json, os, re, sys
    record, answer = sys.argv[1], sys.argv[2]
    argv = sys.argv[3:]
    prompt = open(argv[argv.index("-f") + 1], encoding="utf-8").read()
    with open(record, "a", encoding="utf-8") as handle:
        handle.write(json.dumps({"argv": argv, "prompt": prompt, "env": dict(os.environ)}) + "\n")
    sys.stderr.write("llm: chat template example:\n<|im_start|>user\nHELLO<|im_end|>\n")
    sys.stderr.write("STDERR-MARKER-zz mtmd: image tokens 64 (128x128 -> 256x256)\n")
    sys.stderr.write("x" * 40000 + "\nTAIL-MARKER-zz warning: something\n")
    if "--json-schema-file" in argv:
        kind = re.search(r'"kind":"([a-z_]+)"', prompt).group(1)
        ids = re.findall(r"^- ([a-z0-9_.-]+): ", prompt, re.M)
        payload = {"adherence": {"answers": [{"id": i, "value": True} for i in ids]},
                   "consistency": {"answers": [{"id": i, "value": False} for i in ids]},
                   "defect_triage": {"findings": []},
                   "before_after": {"preferred": "tie", "reason": "no_difference"},
                   "describe": {"objects": ["ANSWER-MARKER-zz"]}}[kind]
        sys.stdout.write(json.dumps({"schema": "stablenew.vl220.response/1", "status": "ok", "kind": kind, **payload}))
    else:
        sys.stdout.write("\nANSWER-MARKER-zz: I see a red square.\n")
    sys.stdout.flush()
    """
)


@pytest.fixture
def diag_world(world: World) -> World:  # noqa: F811
    child = world.tmp / "records" / "diag_child.py"
    child.write_text(DIAG_CHILD, encoding="utf-8")

    def factory(executable: Path, argv: list[str]) -> list[str]:
        world.launches.append((executable, list(argv)))
        return [sys.executable, str(child), str(world.record), str(world.response), *argv]

    world.kwargs["command_factory"] = factory
    return world


def launched(world: World) -> list[dict[str, Any]]:
    return [json.loads(line) for line in world.record.read_text(encoding="utf-8").splitlines()]


def test_a_control_needs_a_capture_and_launches_nothing_without_one(diag_world: World) -> None:
    request = diagnostics.control_requests(synthetic.SET_ID)[0]
    run = diag_world.driver().run_control(diag_world.case_set, request)
    assert run.refusal is not None and run.refusal.code == driver.REFUSED_DIAGNOSTICS
    assert run.evidence.status == driver.STATUS_NOT_RUN and diag_world.launches == []


def test_the_control_is_free_text_and_adds_no_flag(diag_world: World) -> None:
    _, _, case_doc, label_doc = load(synthetic.SET_ID)
    capture = diagnostics.DiagnosticCapture(case_doc, label_doc)
    results = diag_world.driver(capture=capture).run_controls(
        diag_world.case_set, diagnostics.control_requests(synthetic.SET_ID)
    )
    assert results.complete and results.refusal is None and results.report is None
    assert [row.status for row in results.evidence] == [driver.STATUS_CONTROL_ANSWERED] * 2
    assert [row.case_id for row in results.evidence] == ["control-describe-1", "control-describe-2"]
    seen = launched(diag_world)
    for argv_line, request in zip(
        seen, diagnostics.control_requests(synthetic.SET_ID), strict=True
    ):
        argv = argv_line["argv"]
        assert (
            "--json-schema-file" not in argv
            and argv.count("--image") == 1
            and argv.count("--mmproj") == 1
        )
        flags = {
            token
            for token in argv
            if token.startswith("-") and not token.lstrip("-").replace(".", "").isdigit()
        }
        assert (
            flags <= visual_argv.VISUAL_ALLOWED_FLAGS and "--jinja" not in argv and "-p" not in argv
        )
        assert argv[argv.index("-ngl") + 1] == "0" and "--no-mmproj-offload" in argv
        assert argv[argv.index("-n") + 1] == str(driver.CONTROL_MAX_NEW_TOKENS)
        assert argv_line[
            "prompt"
        ] == prompts.render_control_prompt() and request.asset_id.startswith("des-")
        assert (
            argv_line["env"]["CUDA_VISIBLE_DEVICES"] == "-1"
            and "SECRET_TOKEN" not in argv_line["env"]
        )
    # The control is not scored: no answer text leaves the capture and no evidence row carries any.
    assert all(row.reason == "" for row in results.evidence)
    assert "ANSWER-MARKER" not in json.dumps([row.record() for row in results.evidence])


def test_the_capture_keeps_the_answer_and_bounded_runtime_output_for_every_request(
    diag_world: World,
) -> None:
    _, _, case_doc, label_doc = load(synthetic.SET_ID)
    capture = diagnostics.DiagnosticCapture(case_doc, label_doc)
    visual = diag_world.driver(capture=capture)
    scored = visual.run_cases(diag_world.case_set, diag_world.labels)
    controls = visual.run_controls(
        diag_world.case_set, diagnostics.control_requests(synthetic.SET_ID)
    )
    assert scored.complete and controls.complete
    document = capture.document(
        plan_sha256=plan.build_plan()["plan_sha256"], evidence_file="e.json"
    )
    rows = document["requests"]
    assert [row["request_id"] for row in rows[:13]] == [
        case.case_id for case in diag_world.case_set.cases
    ]
    assert [row["request_kind"] for row in rows] == ["case"] * 13 + ["control"] * 2
    assert (
        document["labeler"] == contract.LABELER_SYNTHETIC and document["set_id"] == synthetic.SET_ID
    )
    assert document["case_set_sha256"] == contract.digest(case_doc)
    for row in rows:
        assert "ANSWER-MARKER-zz" in row["answer_text"] or row["kind"] != "describe"
        assert row["exit_code"] == 0 and row["answer_bytes"] == len(row["answer_text"].encode())
        assert (
            "chat template example" in row["stderr_head"]
            and "STDERR-MARKER-zz" in row["stderr_head"]
        )
        assert any("image tokens 64" in fact for fact in row["stderr_facts"])
        assert any("chat template" in fact for fact in row["stderr_facts"])
        assert len(row["stderr_head"]) <= diagnostics.STDERR_HEAD_BYTES
        assert (
            len(row["stderr_tail"]) <= diagnostics.STDERR_TAIL_BYTES
            and "TAIL-MARKER-zz" in row["stderr_tail"]
        )
        assert len(row["stderr_facts"]) <= diagnostics.MAX_FACT_LINES
        assert all(len(fact) <= diagnostics.FACT_LINE_CHARS for fact in row["stderr_facts"])
    control = rows[-1]
    assert control["kind"] == "free_text" and "I see a red square" in control["answer_text"]
    # The evidence document stays free of answer text and runtime output.
    evidence = driver.evidence_document(
        scored,
        plan_sha256="0" * 64,
        case_set_sha256="1" * 64,
        candidate=diag_world.candidate,
        controls=controls,
    )
    text = json.dumps(evidence)
    assert (
        "ANSWER-MARKER" not in text and "STDERR-MARKER" not in text and "chat template" not in text
    )
    assert [row["case_id"] for row in evidence["controls"]] == [
        "control-describe-1",
        "control-describe-2",
    ]
    assert evidence["report"] is not None and evidence["complete"] is True


def test_without_a_capture_no_answer_or_runtime_output_is_kept_anywhere(diag_world: World) -> None:
    visual = diag_world.driver()
    scored = visual.run_cases(diag_world.case_set, diag_world.labels)
    assert scored.complete
    evidence = driver.evidence_document(
        scored, plan_sha256="0" * 64, case_set_sha256="1" * 64, candidate=diag_world.candidate
    )
    secrets = (b"ANSWER-MARKER", b"STDERR-MARKER", b"TAIL-MARKER", b"chat template")
    candidates = [diag_world.kwargs["evaluation_root"], diag_world.ai_root]
    for root in candidates:
        for path in sorted(root.rglob("*")):
            if path.is_file() and path.parent != diag_world.staged:
                data = path.read_bytes()
                assert not any(secret in data for secret in secrets), path
    text = json.dumps(evidence).encode()
    assert not any(secret in text for secret in secrets)
    assert evidence["controls"] == []


def test_the_cli_writes_the_capture_next_to_the_evidence_for_a_builtin_set(
    diag_world: World, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setattr(cli, "find_candidate", lambda _name: diag_world.candidate)
    digest = plan.build_plan(diag_world.candidate)["plan_sha256"]
    real = driver.VisualDriver
    monkeypatch.setattr(
        driver,
        "VisualDriver",
        lambda candidate, **k: real(candidate, **{**diag_world.kwargs, "capture": k["capture"]}),
    )
    out = diag_world.tmp / "diagnostics"
    out.mkdir()
    args = cli_args(
        diag_world,
        digest,
        "--generation-idle",
        "--controls",
        "--diagnostics-out",
        str(out / "run.diagnostics.json"),
    )
    (diag_world.tmp / "ack.json").write_text("{}", encoding="utf-8")
    assert cli.main(args) == 0, capsys.readouterr().err
    evidence = json.loads((diag_world.tmp / "evidence.json").read_text(encoding="utf-8"))
    captured = json.loads((out / "run.diagnostics.json").read_text(encoding="utf-8"))
    assert (
        evidence["complete"] is True
        and len(evidence["controls"]) == 2
        and len(captured["requests"]) == 15
    )
    assert captured["evidence_file"] == "evidence.json" and captured["plan_sha256"] == digest
    assert "ANSWER-MARKER" not in json.dumps(evidence)
    assert cli.main(args) == 2  # an existing diagnostics file is never overwritten


# ============================================================================== argv: the vocabulary is closed, unchanged


def test_free_text_mode_changes_one_thing_only(tmp_path: Path) -> None:
    from tests.tools.test_ai_vl220_invocation import good_argv, make_files

    files = make_files(tmp_path)
    kwargs: dict[str, Any] = {
        "model_path": files.model, "projector_path": files.projector, "prompt_file": files.prompt,
        "image_paths": files.images, "evaluation_root": files.root, "work_dir": files.work,
    }  # fmt: skip
    structured = visual_argv.build_visual_argv(schema_file=files.schema, **kwargs)
    free = visual_argv.build_visual_argv(schema_file=None, free_text=True, **kwargs)
    index = structured.index("--json-schema-file")
    assert free == structured[:index] + structured[index + 2 :]
    assert "--json-schema-file" not in free
    visual_argv.check_visual_argv(free, free_text=True)
    with pytest.raises(visual_argv.VisualArgvRefused) as one:
        visual_argv.check_visual_argv(free)  # a structured request must carry its schema
    assert one.value.code == "model_prompt_and_schema_required"
    with pytest.raises(visual_argv.VisualArgvRefused) as two:
        visual_argv.check_visual_argv(structured, free_text=True)  # a free-text request must not
    assert two.value.code == "model_prompt_and_schema_required"
    for bad in (
        {"free_text": True, "schema_file": files.schema},
        {"free_text": False, "schema_file": None},
    ):
        with pytest.raises(visual_argv.VisualArgvRefused) as mismatch:
            visual_argv.build_visual_argv(**{**kwargs, **bad})
        assert mismatch.value.code == "schema_file_does_not_match_the_request_mode"
    assert good_argv is not None


def test_no_flag_was_added_and_jinja_stays_refused(tmp_path: Path) -> None:
    from tests.tools.test_ai_vl220_invocation import ROW_FLAGS, good_argv

    assert visual_argv.VISUAL_ALLOWED_FLAGS == ROW_FLAGS and len(ROW_FLAGS) == 22
    for flag in ("--jinja", "--no-jinja", "--chat-template", "--chat-template-file", "--chat-template-kwargs", "--system-prompt",
                 "--mmproj-url", "-hf", "-p", "--log-disable"):  # fmt: skip
        assert flag not in visual_argv.VISUAL_ALLOWED_FLAGS
    argv = good_argv(tmp_path)
    for flag in ("--jinja", "--chat-template-kwargs"):
        with pytest.raises(visual_argv.VisualArgvRefused):
            visual_argv.check_visual_argv([*argv, flag, "x"])
        with pytest.raises(visual_argv.VisualArgvRefused):
            visual_argv.check_visual_argv([*argv, flag], free_text=False)
    assert "--jinja" in visual_argv.VISUAL_REFUSED_FLAGS


def test_production_argv_module_is_untouched_by_this_package() -> None:
    source = (REPO / "src" / "ai_assist" / "argv.py").read_text(encoding="utf-8")
    assert "free_text" not in source and "image-min-tokens" not in source
    result = subprocess.run(  # noqa: S603
        ["git", "diff", "--quiet", "origin/main", "--", "src/ai_assist/argv.py"],
        cwd=REPO,
        check=False,
    )
    assert result.returncode in (
        0,
        128,
    )  # 128: no origin/main in this checkout (a source archive); the PR gate checks it


def test_the_diagnostic_modules_import_no_network_or_process_library() -> None:
    import ast

    banned = {
        "socket",
        "subprocess",
        "threading",
        "urllib",
        "http",
        "requests",
        "ctypes",
        "multiprocessing",
    }
    for name in ("diagnostics", "prompts", "scoring", "plan"):
        tree = ast.parse(
            (REPO / "tools" / "qualification" / "vl220" / f"{name}.py").read_text(encoding="utf-8")
        )
        imported = {
            alias.name.split(".")[0]
            for node in ast.walk(tree)
            if isinstance(node, ast.Import)
            for alias in node.names
        } | {
            node.module.split(".")[0]
            for node in ast.walk(tree)
            if isinstance(node, ast.ImportFrom) and node.module
        }
        assert not imported & banned, (name, imported & banned)
