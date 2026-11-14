"""PR-AI-VL-220: the visual evaluation contract, scoring and plan, on deterministic synthetic data. No model is run."""

from __future__ import annotations

import copy
import json
import struct
import zlib
from pathlib import Path
from typing import Any

import pytest

from tools.qualification.vl220 import contract, plan, scoring, synthetic
from tools.qualification.vl220.contract import ContractViolation, Measurement, ResourceLimits

REPO = Path(__file__).resolve().parents[2]


@pytest.fixture(scope="module")
def built() -> tuple[dict[str, bytes], dict[str, Any], dict[str, Any]]:
    return synthetic.build_synthetic_set()


@pytest.fixture
def case_set(built: Any) -> contract.CaseSet:
    return contract.validate_case_set(copy.deepcopy(built[1]))


@pytest.fixture
def labels(built: Any, case_set: contract.CaseSet) -> contract.LabelSet:
    return contract.validate_label_set(copy.deepcopy(built[2]), case_set)


def perfect_responses(case_set: contract.CaseSet, labels: contract.LabelSet) -> dict[str, str]:
    """What an oracle that read the labels would answer; used only to prove the scorer rewards a correct system."""

    out: dict[str, str] = {}
    for case in case_set.cases:
        reference = labels.references[case.case_id]
        head: dict[str, Any] = {
            "schema": contract.RESPONSE_SCHEMA,
            "status": "ok",
            "kind": case.kind,
        }
        if "answers" in reference:
            head["answers"] = [{"id": k, "value": v} for k, v in reference["answers"].items()]
        elif "findings" in reference:
            head["findings"] = reference["findings"]
        elif "preferred" in reference:
            head.update(preferred=reference["preferred"], reason="more_complete")
        else:
            head["objects"] = list(reference["objects"])
        out[case.case_id] = json.dumps(head)
    return out


# ------------------------------------------------------------------------------------------ synthetic assets


def test_synthetic_set_is_byte_deterministic_and_pinned(built: Any) -> None:
    images, case_doc, label_doc = built
    again_images, again_cases, again_labels = synthetic.build_synthetic_set()
    assert again_images == images and again_cases == case_doc and again_labels == label_doc
    pinned = {asset["asset_id"]: asset for asset in case_doc["assets"]}
    assert set(pinned) == set(images)
    for asset_id, data in images.items():
        assert data.startswith(b"\x89PNG\r\n\x1a\n")
        width, height = struct.unpack(">II", data[16:24])
        assert (height, width % synthetic.CELL) == (synthetic.CELL, 0)
        assert pinned[asset_id]["bytes"] == len(data)
        idat = data[data.index(b"IDAT") + 4 : data.index(b"IEND") - 8]
        assert zlib.decompress(idat)  # a valid zlib stream
    assert all(asset["origin"] == "synthetic" for asset in case_doc["assets"])
    assert label_doc["labeler"] == contract.LABELER_SYNTHETIC


def test_synthetic_set_covers_every_kind_and_dimension(case_set: contract.CaseSet) -> None:
    assert {case.kind for case in case_set.cases} == set(contract.KINDS)
    assert set(contract.DIMENSION_OF_KIND.values()) | {
        contract.DIM_STRUCTURED,
        contract.DIM_RESOURCES,
    } == set(contract.DIMENSIONS)
    clean = [c for c in case_set.cases if c.kind == contract.KIND_DEFECT]
    assert len(clean) >= 4


def test_cases_carry_no_reference_data_and_labels_are_separate(built: Any) -> None:
    _, case_doc, label_doc = built
    text = json.dumps(case_doc).lower()
    for word in ("reference", "answers", "findings", "preferred", "ground_truth", "expected"):
        assert word not in text
    assert "reference" in json.dumps(label_doc)


# ----------------------------------------------------------------------------------- case and label validation


def mutated(document: dict[str, Any], change: Any) -> dict[str, Any]:
    copy_ = copy.deepcopy(document)
    change(copy_)
    return copy_


@pytest.mark.parametrize(
    ("code", "change"),
    [
        ("case_carries_reference_data", lambda d: d["cases"][0].update(answers={"e1": True})),
        ("case_carries_reference_data", lambda d: d["cases"][0]["elements"][0].update(label="x")),
        ("unknown_keys", lambda d: d["cases"][0].update(extra=1)),
        ("unknown_keys", lambda d: d.update(extra=1)),
        ("bad_schema", lambda d: d.update(schema="other/1")),
        ("bad_kind", lambda d: d["cases"][0].update(kind="chat")),
        ("unknown_asset", lambda d: d["cases"][0].update(asset_ids=["nope"])),
        ("bad_asset_count", lambda d: d["cases"][0].update(asset_ids=["adh-1", "adh-2"])),
        ("bad_prompt", lambda d: d["cases"][0].update(prompt="x" * 1001)),
        ("bad_prompt", lambda d: d["cases"][0].update(prompt="  ")),
        ("duplicate_case", lambda d: d["cases"].append(copy.deepcopy(d["cases"][0]))),
        ("duplicate_asset", lambda d: d["assets"].append(copy.deepcopy(d["assets"][0]))),
        ("bad_asset_digest", lambda d: d["assets"][0].update(sha256="zz")),
        ("bad_asset_size", lambda d: d["assets"][0].update(bytes=0)),
        ("bad_origin", lambda d: d["assets"][0].update(origin="web")),
        ("bad_media_type", lambda d: d["assets"][0].update(media_type="application/pdf")),
        ("bad_identifier", lambda d: d["cases"][0].update(case_id="Has Space")),
        (
            "duplicate_element",
            lambda d: d["cases"][0]["elements"].append(copy.deepcopy(d["cases"][0]["elements"][0])),
        ),
        ("bad_list", lambda d: d["cases"][0].update(elements=[])),
        (
            "unexpected_elements",
            lambda d: d["cases"][5].update(elements=[{"id": "x", "text": "y"}]),
        ),
        ("not_an_object", lambda d: d.update(cases=[1])),
    ],
)
def test_invalid_case_documents_are_refused(built: Any, code: str, change: Any) -> None:
    with pytest.raises(ContractViolation) as caught:
        contract.validate_case_set(mutated(built[1], change))
    assert caught.value.code == code


@pytest.mark.parametrize(
    ("code", "change"),
    [
        ("label_set_mismatch", lambda d: d.update(set_id="other")),
        ("bad_labeler", lambda d: d.update(labeler="model")),
        ("labels_do_not_cover_cases", lambda d: d["labels"].pop()),
        ("duplicate_label", lambda d: d["labels"].append(copy.deepcopy(d["labels"][0]))),
        ("label_for_unknown_case", lambda d: d["labels"][0].update(case_id="nope")),
        (
            "answers_do_not_match_elements",
            lambda d: d["labels"][0]["reference"]["answers"].pop("e1"),
        ),
        ("bad_answer", lambda d: d["labels"][0]["reference"]["answers"].update(e1="yes")),
        (
            "bad_finding",
            lambda d: next(
                x
                for x in d["labels"]
                if "findings" in x["reference"] and x["reference"]["findings"]
            )["reference"]["findings"][0].update(region="knee"),
        ),
        (
            "bad_preference",
            lambda d: next(x for x in d["labels"] if "preferred" in x["reference"])[
                "reference"
            ].update(preferred="c"),
        ),
        (
            "bad_synonyms",
            lambda d: next(x for x in d["labels"] if "objects" in x["reference"])["reference"][
                "synonyms"
            ].update(ghost=["x"]),
        ),
        ("unknown_keys", lambda d: d["labels"][0]["reference"].update(extra=1)),
        ("bad_schema", lambda d: d.update(schema="stablenew.vl220.cases/1")),
    ],
)
def test_invalid_label_documents_are_refused(
    built: Any, case_set: contract.CaseSet, code: str, change: Any
) -> None:
    with pytest.raises(ContractViolation) as caught:
        contract.validate_label_set(mutated(built[2], change), case_set)
    assert caught.value.code == code


def test_existing_assets_need_labels_written_by_a_person(built: Any) -> None:
    case_doc = mutated(built[1], lambda d: d["assets"][0].update(origin="existing"))
    existing = contract.validate_case_set(case_doc)
    with pytest.raises(ContractViolation) as caught:
        contract.validate_label_set(built[2], existing)
    assert caught.value.code == "existing_assets_need_human_labels"
    human = mutated(built[2], lambda d: d.update(labeler="human"))
    assert contract.validate_label_set(human, existing).labeler == "human"


# ----------------------------------------------------------------------------------------- response validation


def case_of(case_set: contract.CaseSet, kind: str) -> contract.Case:
    return next(case for case in case_set.cases if case.kind == kind)


def response(kind: str, **fields: Any) -> str:
    return json.dumps({"schema": contract.RESPONSE_SCHEMA, "status": "ok", "kind": kind, **fields})


def test_valid_responses_pass_for_every_kind(
    case_set: contract.CaseSet, labels: contract.LabelSet
) -> None:
    for case in case_set.cases:
        check = contract.validate_response(case, perfect_responses(case_set, labels)[case.case_id])
        assert check.valid and check.reason == "", case.case_id
    refusal = json.dumps(
        {"schema": contract.RESPONSE_SCHEMA, "status": "refused", "refusal_reason": "cannot"}
    )
    assert contract.validate_response(case_set.cases[0], refusal).status == "refused"


def test_invalid_responses_fail_closed_with_a_stable_reason(case_set: contract.CaseSet) -> None:
    adh = case_of(case_set, contract.KIND_ADHERENCE)
    defect = case_of(case_set, contract.KIND_DEFECT)
    ba = case_of(case_set, contract.KIND_BEFORE_AFTER)
    des = case_of(case_set, contract.KIND_DESCRIBE)
    ids = [key for key, _ in adh.elements]
    good_answers = [{"id": key, "value": True} for key in ids]
    cases: list[tuple[contract.Case, str, str]] = [
        (adh, "", "not_json"),
        (adh, "not json", "not_json"),
        (adh, "[]", "not_an_object"),
        (adh, "{}", "bad_schema"),
        (adh, json.dumps({"schema": "x"}), "bad_schema"),
        (adh, response(contract.KIND_DEFECT, findings=[]), "kind_mismatch"),
        (adh, json.dumps({"schema": contract.RESPONSE_SCHEMA, "status": "maybe"}), "kind_mismatch"),
        (adh, response(adh.kind), "missing_keys"),
        (adh, response(adh.kind, answers=good_answers, extra=1), "unknown_keys"),
        (adh, response(adh.kind, answers=good_answers[:-1]), "answers_do_not_match_elements"),
        (
            adh,
            response(adh.kind, answers=good_answers + [{"id": ids[0], "value": False}]),
            "duplicate_answer",
        ),
        (
            adh,
            response(adh.kind, answers=[{"id": ids[0], "value": "yes"}] + good_answers[1:]),
            "bad_answer",
        ),
        (adh, response(adh.kind, answers=[]), "bad_list"),
        (adh, "x" * (contract.MAX_RESPONSE_BYTES + 1), "response_too_large"),
        (adh, json.dumps({"schema": contract.RESPONSE_SCHEMA, "status": "refused"}), "bad_refusal"),
        (
            adh,
            json.dumps(
                {
                    "schema": contract.RESPONSE_SCHEMA,
                    "status": "refused",
                    "refusal_reason": "x" * 401,
                }
            ),
            "bad_refusal",
        ),
        (
            defect,
            response(
                defect.kind,
                findings=[{"region": "knee", "category": "extra_limb", "severity": "major"}],
            ),
            "bad_finding",
        ),
        (
            defect,
            response(defect.kind, findings=[{"region": "arms", "category": "extra_limb"}]),
            "missing_keys",
        ),
        (
            defect,
            response(
                defect.kind,
                findings=[{"region": "arms", "category": "extra_limb", "severity": "major"}] * 9,
            ),
            "bad_list",
        ),
        (ba, response(ba.kind, preferred="c", reason="more_complete"), "bad_preference"),
        (ba, response(ba.kind, preferred="a", reason="because"), "bad_preference"),
        (des, response(des.kind, objects=["x" * 41]), "bad_object_name"),
        (des, response(des.kind, objects=["a"] * 17), "bad_list"),
        (des, response(des.kind, objects=[3]), "bad_object_name"),
    ]
    for case, text, reason in cases:
        check = contract.validate_response(case, text)
        assert (check.status, check.reason) == ("invalid", reason), (text[:60], check)
    assert contract.validate_response(adh, None).status == "invalid"  # type: ignore[arg-type]


ALLOWED_SCHEMA_KEYWORDS = {
    "oneOf", "const", "enum", "required", "properties", "additionalProperties", "type", "items", "minItems", "maxItems", "maxLength",
}  # fmt: skip


def schema_ok(schema: dict[str, Any], value: Any) -> bool:
    """A minimal checker for exactly the keyword subset the schema is allowed to use."""

    assert set(schema) <= ALLOWED_SCHEMA_KEYWORDS, set(schema) - ALLOWED_SCHEMA_KEYWORDS
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
        return (
            isinstance(value, list)
            and schema["minItems"] <= len(value) <= schema["maxItems"]
            and all(schema_ok(schema["items"], item) for item in value)
        )
    assert kind == "object"
    if not isinstance(value, dict):
        return False
    if schema.get("additionalProperties") is False and set(value) - set(schema["properties"]):
        return False
    if set(schema["required"]) - set(value):
        return False
    return all(schema_ok(schema["properties"][key], item) for key, item in value.items())


def test_response_schema_is_closed_and_agrees_with_the_validator(
    case_set: contract.CaseSet, labels: contract.LabelSet
) -> None:
    perfect = perfect_responses(case_set, labels)
    for kind in contract.KINDS:
        schema = contract.build_response_schema(kind)
        assert list(schema) == ["oneOf"] and len(schema["oneOf"]) == 2
        case = case_of(case_set, kind)
        assert schema_ok(schema, json.loads(perfect[case.case_id]))
        assert schema_ok(
            schema,
            {"schema": contract.RESPONSE_SCHEMA, "status": "refused", "refusal_reason": "no"},
        )
        # The two-field document that stalled the text models matches neither branch.
        assert not schema_ok(schema, {"schema": contract.RESPONSE_SCHEMA, "status": "ok"})
        assert not schema_ok(schema, {**json.loads(perfect[case.case_id]), "extra": 1})
    with pytest.raises(ContractViolation):
        contract.build_response_schema("chat")


# --------------------------------------------------------------------------------------------------- scoring


def test_an_oracle_scores_perfectly_and_the_floors_do_not(
    case_set: contract.CaseSet, labels: contract.LabelSet
) -> None:
    report = scoring.score_run(case_set, labels, perfect_responses(case_set, labels))
    assert (
        report[contract.DIM_ADHERENCE]
        == report[contract.DIM_CONSISTENCY]
        == report[contract.DIM_BEFORE_AFTER]
        == 1.0
    )
    assert report[contract.DIM_DEFECT] == {
        "precision": 1.0,
        "recall": 1.0,
        "false_alarm_rate_on_clean_cases": 0.0,
    }
    assert report[contract.DIM_HALLUCINATION] == {
        "unsupported_mention_rate": 0.0,
        "object_recall": 1.0,
    }
    assert report[contract.DIM_STRUCTURED]["valid_rate"] == 1.0
    for mode in ("all_yes", "all_no", "seeded_random"):
        floor = scoring.score_run(case_set, labels, scoring.baseline_responses(case_set, mode))
        assert floor[contract.DIM_STRUCTURED]["valid_rate"] == 1.0
        assert floor[contract.DIM_ADHERENCE] < 1.0 and floor[contract.DIM_DEFECT]["recall"] < 1.0


def test_baselines_are_reproducible_and_seeded(case_set: contract.CaseSet) -> None:
    first = scoring.baseline_responses(case_set, "seeded_random", seed=7)
    assert first == scoring.baseline_responses(case_set, "seeded_random", seed=7)
    assert first != scoring.baseline_responses(case_set, "seeded_random", seed=8)
    with pytest.raises(ValueError):
        scoring.baseline_responses(case_set, "optimistic")


def test_hallucinations_missing_answers_and_garbage_are_scored_not_skipped(
    case_set: contract.CaseSet, labels: contract.LabelSet
) -> None:
    responses = perfect_responses(case_set, labels)
    des = case_of(case_set, contract.KIND_DESCRIBE)
    objects = json.loads(responses[des.case_id])["objects"]
    responses[des.case_id] = response(des.kind, objects=[*objects, "purple dragon", "RED-SQUARE"])
    other = [c for c in case_set.cases if c.kind == contract.KIND_DESCRIBE][1]
    responses[other.case_id] = "garbage"
    adh = case_of(case_set, contract.KIND_ADHERENCE)
    del responses[adh.case_id]
    report = scoring.score_run(case_set, labels, responses)
    assert report[contract.DIM_HALLUCINATION]["unsupported_mention_rate"] == pytest.approx(
        1 / 4, abs=1e-3
    )
    assert report[contract.DIM_HALLUCINATION]["object_recall"] == pytest.approx(2 / 3, abs=1e-3)
    assert report[contract.DIM_ADHERENCE] < 1.0
    structured = report[contract.DIM_STRUCTURED]
    assert structured["invalid_reasons"] == {"not_json": 2}
    assert structured["valid_rate"] == pytest.approx(11 / 13, abs=1e-3)


def test_refusals_count_as_wrong_answers_but_valid_structure(
    case_set: contract.CaseSet, labels: contract.LabelSet
) -> None:
    refusal = json.dumps(
        {"schema": contract.RESPONSE_SCHEMA, "status": "refused", "refusal_reason": "no"}
    )
    report = scoring.score_run(case_set, labels, {case.case_id: refusal for case in case_set.cases})
    assert (
        report[contract.DIM_STRUCTURED]["refused_rate"] == 1.0
        and report[contract.DIM_STRUCTURED]["valid_rate"] == 0.0
    )
    assert report[contract.DIM_ADHERENCE] == 0.0 and report[contract.DIM_BEFORE_AFTER] == 0.0


def test_resource_limits_flag_slow_large_or_non_cpu_runs(
    case_set: contract.CaseSet, labels: contract.LabelSet
) -> None:
    limits = ResourceLimits()
    ok = Measurement(10.0, 2 * 1024**3, 1024, True)
    slow = Measurement(limits.max_wall_seconds + 1, 1, 1, True)
    big = Measurement(1.0, limits.max_peak_working_set_bytes + 1, 1, True)
    gpu = Measurement(1.0, 1, limits.max_context_tokens + 1, False)
    assert contract.limit_violations(ok, limits) == ()
    assert contract.limit_violations(slow, limits) == ("wall_time",)
    assert contract.limit_violations(big, limits) == ("memory",)
    assert contract.limit_violations(gpu, limits) == ("context", "not_cpu_only")
    cases = [c.case_id for c in case_set.cases]
    measurements = {cases[0]: ok, cases[1]: slow, cases[2]: big, cases[3]: gpu}
    report = scoring.score_run(case_set, labels, {}, measurements)[contract.DIM_RESOURCES]
    assert report["measured_cases"] == 4 and report["unmeasured_cases"] == len(cases) - 4
    assert report["violations"] == {
        "context": 1,
        "memory": 1,
        "not_cpu_only": 1,
        "unmeasured": len(cases) - 4,
        "wall_time": 1,
    }
    assert scoring.score_run(case_set, labels, {})[contract.DIM_RESOURCES]["measured_cases"] == 0


# --------------------------------------------------------------------------- comparators, plan, specification


def test_comparator_eligibility_is_explicit_about_what_exists_today() -> None:
    table = {item["comparator_id"]: item for item in contract.comparator_table()}
    assert table["deterministic-floor"]["eligible"] is True
    assert table["florence2-caption"]["eligible"] is True and table["florence2-caption"][
        "dimensions"
    ] == [contract.DIM_HALLUCINATION]
    assert "no_structured_output" in table["florence2-caption"]["reasons"]
    for text_only in ("qwen3.5-text-gguf", "lfm3-1.7b-text-gguf", "sam2-segmentation"):
        assert table[text_only]["eligible"] is False and table[text_only]["dimensions"] == []
    assert "mmproj_flag_is_forbidden" in table["qwen3.5-text-gguf"]["reasons"]
    candidate = table["lfm3-vl-2b-q4_k_m-liquidai"]
    # The invocation is approved and implemented (PR-AI-VL-220 driver); the candidate stays ineligible until the owner's license
    # acknowledgement and an evaluation-root import exist.
    assert (
        candidate["eligible"] is False
        and "image_invocation_not_approved" not in candidate["reasons"]
    )
    assert set(candidate["reasons"]) == {
        "license_not_acknowledged",
        "not_imported_into_an_evaluation_root",
    }


def test_comparator_names_match_the_existing_smart_review_capabilities() -> None:
    from src.review.assist import contracts as review

    ids = {item.comparator_id for item in contract.comparators()}
    assert (
        f"{review.CAPABILITY_CAPTION}-caption" in ids
        and f"{review.CAPABILITY_SEGMENT}-segmentation" in ids
    )


def test_plan_is_deterministic_runs_nothing_and_records_the_approved_invocation() -> None:
    first = plan.build_plan()
    assert first == plan.build_plan() and len(first["plan_sha256"]) == 64
    assert first["executes_models"] is False
    assert first["image_invocation"]["approved"] is True and contract.INVOCATION_APPROVED is True
    assert (
        first["candidate"]["qualified"] is False
        and first["candidate"]["required_build_id"] == "b11960-cpu"
    )
    assert set(first["response_schema_digests"]) == set(contract.KINDS)
    assert first["dimensions"] == list(contract.DIMENSIONS)
    body = {key: value for key, value in first.items() if key != "plan_sha256"}
    assert contract.digest(body) == first["plan_sha256"]


def test_the_specification_documents_exist_and_carry_the_current_plan_digest() -> None:
    digest = plan.build_plan()["plan_sha256"]
    for relative in (plan.EVALUATION_DOCUMENT, plan.INVOCATION_DOCUMENT):
        text = (REPO / relative).read_text(encoding="utf-8")
        lowered = text.lower()
        assert (
            "not approved" in lowered
            or "pending owner approval" in lowered
            or "not yet implemented" in lowered
            or "no run is possible" in lowered
        )
    assert digest in (REPO / plan.EVALUATION_DOCUMENT).read_text(encoding="utf-8")


def test_dry_run_validates_and_scores_without_touching_disk(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.chdir(tmp_path)
    result = plan.dry_run()
    assert result["cases"] == 13 and set(result["baselines"]) == {
        "all_yes",
        "all_no",
        "seeded_random",
    }
    assert list(tmp_path.iterdir()) == []
