"""AI-VL-242: the ``eval/2`` contract, the Review-export converter, the scorer and the persistence rule. Synthetic data only."""

from __future__ import annotations

import copy
import json
from typing import Any

import pytest

from src.review.findings import Category
from tests.tools import vl242_support as sup
from tools.qualification.vl220 import contract, eval2, eval2_scoring, review_export, synthetic
from tools.qualification.vl220 import plan as vl220_plan
from tools.qualification.vl220.contract import ContractViolation, canonical_json
from tools.qualification.vl220.eval2 import CaseResult, HumanFinding, ImageReference

# ------------------------------------------------------------------------------------------- eval/1 stays byte-identical

EVAL1_SCHEMA_DIGESTS = {
    "adherence": "078f19472a9452eb5adf4c859e91ef27bdaaa002ea1ffc9a1332576c1fd1eebb",
    "defect_triage": "5d3f76df83e545e405ef6fad3ca887967bd2951884abbe2d20d04893d3e6a8ba",
    "consistency": "ca9359562aa26a4e716cb591808ed91f98f9f444fdd5a866c96730d172132b5a",
    "before_after": "2c7a6d38a03a5a2924249da0131075c861a2146e34daf03ee05e02922cf4c30e",
    "describe": "a75a0f6283a84dbf6a76d16fffa277c216a30a3687acaf5d566d5706d4a35f7c",
}
SYNTHETIC_DIGESTS = {
    "vl220-synthetic-1": (
        "9c11172fa6af8d080673cf2c89ca6b87a7404cbcc439425cc9e726e197e0ccd1",
        "6598abbfac6385c976cf886e84cd4767cc74408607757125dca47aeeb72716dc",
    ),
    "vl220-synthetic-512-1": (
        "33c0f6e164970c576ea5a58efa8dc6bd7239d5bf26aca7b7ada71ad41f7ca721",
        "f81cc805b380d9ca2b70c2d86ce21ff83d3d79ddc722c0e9338a3f47b0f8e08f",
    ),
    "vl220-synthetic-512-2": (
        "1306b33d2f17c57e0039880e3ed273380dbac9a85f43c85c849ea24dee1fc726",
        "277773917dc8dcfeaf3e76cfdef7729cede8e91c5b223356ce0d758fb55afd30",
    ),
}
EVAL1_PLAN = "15d7ab2ee6d5b5f21db3798dee3390ed6a8c4086dc973ce5593ee91a043db536"


def test_eval1_contract_schemas_sets_and_plan_are_unchanged() -> None:
    assert contract.CONTRACT_ID == "stablenew.vl220.eval/1"
    assert contract.RESPONSE_SCHEMA == "stablenew.vl220.response/1"
    assert {
        k: contract.digest(contract.build_response_schema(k)) for k in contract.KINDS
    } == EVAL1_SCHEMA_DIGESTS
    for set_id, (cases, labels) in SYNTHETIC_DIGESTS.items():
        _, case_doc, label_doc = synthetic.build_synthetic_set(set_id)
        assert (contract.digest(case_doc), contract.digest(label_doc)) == (cases, labels)
    assert set(synthetic.BUILTIN_SCALES) == set(SYNTHETIC_DIGESTS)
    assert vl220_plan.build_plan()["plan_sha256"] == EVAL1_PLAN


def test_eval2_has_its_own_identities() -> None:
    assert eval2.CONTRACT_ID == "stablenew.vl220.eval/2" != contract.CONTRACT_ID
    assert len({eval2.CASES_SCHEMA, eval2.LABELS_SCHEMA, eval2.RESPONSE_SCHEMA, eval2.EVIDENCE_SCHEMA,
                contract.CASES_SCHEMA, contract.LABELS_SCHEMA, contract.RESPONSE_SCHEMA}) == 7  # fmt: skip


# ------------------------------------------------------------------------------------------------------ taxonomy


def test_the_defect_vocabulary_is_reviews_own_taxonomy_minus_prompt_adherence() -> None:
    assert eval2.CATEGORIES == tuple(c.value for c in Category if c is not Category.PROMPT)
    assert eval2.EXCLUDED_CATEGORIES == (Category.PROMPT.value,)
    schema = eval2.build_response_schema(eval2.KIND_IMAGE)
    defective = schema["oneOf"][1]["properties"]["findings"]["items"]["properties"]
    assert defective["category"]["enum"] == list(eval2.CATEGORIES)
    assert defective["region"]["enum"] == list(eval2.REGIONS)


@pytest.mark.parametrize(
    ("box", "zones"),
    [
        ((0, 0, 10, 10), ("top_left",)),
        ((90, 90, 210, 210), ("center",)),  # neighbours hold under 10 % each
        ((0, 0, 300, 300), eval2.ZONES),
        ((0, 0, 200, 100), ("top_left", "top")),
        ((290, 290, 300, 300), ("bottom_right",)),
    ],
)
def test_zones_of_a_box(box: tuple[int, int, int, int], zones: tuple[str, ...]) -> None:
    assert eval2.zones_of_box(box, 300, 300) == zones


def test_region_compatibility() -> None:
    assert eval2.region_matches("top", None)
    assert eval2.region_matches(eval2.WHOLE_IMAGE, None)
    assert eval2.region_matches("top", ("top_left", "top"))
    assert not eval2.region_matches("bottom", ("top_left", "top"))
    assert not eval2.region_matches(eval2.WHOLE_IMAGE, ("top_left", "top"))
    assert eval2.region_matches(eval2.WHOLE_IMAGE, eval2.ZONES[:6])
    assert not eval2.region_matches(eval2.WHOLE_IMAGE, eval2.ZONES[:5])


# ----------------------------------------------------------------------------------------------------- converter


def test_the_converter_builds_the_planned_set() -> None:
    conversion = review_export.convert(sup.standard_export())
    summary = conversion.summary
    assert (summary["image_cases"], summary["clean"], summary["defective"]) == (50, 20, 30)
    assert (summary["multi_subject"], summary["pair_cases"]) == (10, 12)
    assert summary["excluded_unreviewed"] == 12  # the after images: no label of their own
    assert summary["judgments"] == {"helped": 3, "no_benefit": 3, "worse": 3, "inconclusive": 3}
    case_set = eval2.validate_case_set(conversion.cases)
    labels = eval2.validate_label_set(conversion.labels, case_set)
    assert len(case_set.cases) == 62 and labels.labeler == "human"
    assert all(case.case_id.startswith(("img.", "pair.")) for case in case_set.cases)


def test_the_converter_copies_no_export_text() -> None:
    document = sup.standard_export()
    document["images"][25]["findings"][0]["observation"] = "PRIVATE-OBSERVATION-TEXT"
    document["images"][25]["prompt"] = "PRIVATE-PROMPT-TEXT"
    document["provenance"]["note"] = "PRIVATE-NOTE"
    document["pairs"][0]["intervention"] = "PRIVATE-INTERVENTION"
    conversion = review_export.convert(document)
    text = canonical_json([conversion.cases, conversion.labels, conversion.summary])
    for secret in ("PRIVATE", "clean-", "defect-", "after-", "pair-", "synthetic-fixture"):
        assert secret not in text


def test_pairs_alternate_presentation_and_the_case_does_not_say_which_is_corrected() -> None:
    _, _, case_set, labels = sup.documents(sup.standard_export())
    pairs = [case for case in case_set.cases if case.kind == eval2.KIND_PAIR]
    after_first = [case.asset_ids[0] == labels.pair(case.case_id).after_asset_id for case in pairs]
    assert after_first.count(True) == after_first.count(False) == 6
    assert "after" not in canonical_json(
        [{"case_id": c.case_id, "assets": c.asset_ids} for c in pairs]
    )


def test_regions_become_zones_and_missing_regions_stay_unknown() -> None:
    document = sup.export(
        [
            sup.image(
                "a",
                clean=False,
                findings=[sup.finding("Face", [0, 0, 200, 100]), {"category": "Hands"}],
            ),
            sup.image("b", clean=False, findings=[sup.finding("Anatomy", None) | {"region": None}]),
        ]
    )
    _, labels_doc, _, labels = sup.documents(document)
    found = {
        f.category: f.zones for case_id in labels.references for f in labels.image(case_id).findings
    }
    assert found == {"Face": ("top_left", "top"), "Hands": None, "Anatomy": None}
    assert labels_doc["labeler"] == "human"


def test_prompt_only_unreviewed_and_unconfirmed_findings_are_excluded_and_counted() -> None:
    document = sup.export(
        [
            sup.image("clean"),
            sup.image("prompt-only", clean=False, findings=[sup.finding("Prompt adherence")]),
            sup.image(
                "mixed",
                clean=False,
                findings=[sup.finding("Prompt adherence"), sup.finding("Hands")],
            ),
            sup.image("unreviewed", clean=False),
            sup.image(
                "tentative", clean=False, findings=[sup.finding("Face", confirmation="Uncertain")]
            ),
            sup.image(
                "confirmed", clean=False, findings=[sup.finding("Face", confirmation="Confirmed")]
            ),
        ]
    )
    summary = review_export.convert(document).summary
    assert summary["image_cases"] == 3  # clean, mixed, confirmed
    assert summary["excluded_prompt_only"] == 1
    assert summary["excluded_unreviewed"] == 2  # unreviewed, tentative
    assert summary["prompt_findings_dropped"] == 2
    assert summary["unconfirmed_findings_ignored"] == 1


def _mutations() -> list[tuple[str, Any]]:
    def labeler(d: dict[str, Any]) -> None:
        d["provenance"]["labeler"] = "model"

    def clean_with_findings(d: dict[str, Any]) -> None:
        d["images"][0]["findings"] = [sup.finding()]

    def bad_category(d: dict[str, Any]) -> None:
        d["images"][25]["findings"][0]["category"] = "hands"

    def bad_region(d: dict[str, Any]) -> None:
        d["images"][25]["findings"][0]["region"] = [0, 0, 400, 10]

    def duplicate_id(d: dict[str, Any]) -> None:
        d["images"][1]["image_id"] = d["images"][0]["image_id"]

    def duplicate_sha(d: dict[str, Any]) -> None:
        d["images"][1]["sha256"] = d["images"][0]["sha256"]

    def unknown_pair_image(d: dict[str, Any]) -> None:
        d["pairs"][0]["after_image_id"] = "missing"

    def identical_pair(d: dict[str, Any]) -> None:
        d["pairs"][0]["after_image_id"] = d["pairs"][0]["before_image_id"]

    def bad_judgment(d: dict[str, Any]) -> None:
        d["pairs"][0]["judgment"] = "no benefit"

    def bad_schema(d: dict[str, Any]) -> None:
        d["schema"] = "stablenew.vl240.review_export/2"

    def bad_count(d: dict[str, Any]) -> None:
        d["images"][0]["subject_count"] = -1

    return [
        ("labels_need_human_labeler", labeler), ("clean_image_has_findings", clean_with_findings),
        ("bad_category", bad_category), ("bad_region", bad_region), ("duplicate_image", duplicate_id),
        ("duplicate_image_digest", duplicate_sha), ("pair_image_not_exported", unknown_pair_image),
        ("pair_images_identical", identical_pair), ("bad_judgment", bad_judgment), ("bad_schema", bad_schema),
        ("bad_subject_count", bad_count),
    ]  # fmt: skip


@pytest.mark.parametrize(("code", "mutate"), _mutations(), ids=[code for code, _ in _mutations()])
def test_the_converter_refuses_malformed_exports(code: str, mutate: Any) -> None:
    document = sup.standard_export()
    mutate(document)
    with pytest.raises(ContractViolation) as caught:
        review_export.convert(document)
    assert caught.value.code == code


def test_label_and_case_documents_are_refused_when_altered() -> None:
    cases, labels, case_set, _ = sup.documents(sup.standard_export())
    bad = copy.deepcopy(labels)
    bad["labeler"] = "synthetic_by_construction"
    with pytest.raises(ContractViolation, match="labels_need_human_labeler"):
        eval2.validate_label_set(bad, case_set)
    bad = copy.deepcopy(labels)
    clean_row = next(row for row in bad["labels"] if row["reference"].get("verdict") == "clean")
    clean_row["reference"]["findings"] = [
        {"category": "Hands", "zones": None}
    ]  # a clean image with a finding
    with pytest.raises(ContractViolation, match="verdict_does_not_match_findings"):
        eval2.validate_label_set(bad, case_set)
    bad_cases = copy.deepcopy(cases)
    bad_cases["cases"][0]["prompt"] = "anything"
    with pytest.raises(ContractViolation, match="unknown_keys"):
        eval2.validate_case_set(bad_cases)
    bad = copy.deepcopy(labels)
    bad["labels"].pop()
    with pytest.raises(ContractViolation, match="labels_do_not_cover_cases"):
        eval2.validate_label_set(bad, case_set)


# ------------------------------------------------------------------------------------------------ schema closure


def _walk(node: Any, path: str = "$") -> list[tuple[str, dict[str, Any]]]:
    found: list[tuple[str, dict[str, Any]]] = []
    if isinstance(node, dict):
        found.append((path, node))
        for key, value in node.items():
            found += _walk(value, f"{path}.{key}")
    elif isinstance(node, list):
        for index, value in enumerate(node):
            found += _walk(value, f"{path}[{index}]")
    return found


@pytest.mark.parametrize("kind", eval2.KINDS)
def test_the_response_schema_is_closed(kind: str) -> None:
    schema = eval2.build_response_schema(kind)
    allowed = {"oneOf", "const", "enum", "type", "required", "properties", "additionalProperties", "items",
               "minItems", "maxItems"}  # fmt: skip
    for path, node in _walk(schema):
        if path.endswith(".properties"):
            continue
        assert set(node) <= allowed, path
        if node.get("type") == "object":
            assert node["additionalProperties"] is False, path
            assert sorted(node["required"]) == sorted(node["properties"]), path
        if node.get("type") == "array":
            assert "maxItems" in node and node["maxItems"] <= eval2.MAX_ANSWER_FINDINGS, path
        if "properties" in node:
            for name, leaf in node["properties"].items():
                assert "const" in leaf or "enum" in leaf or leaf.get("type") == "array", (
                    f"{path}.{name}"
                )
        assert node.get("type") != "string", f"free text at {path}"


def _accepts(schema: dict[str, Any], value: Any) -> bool:
    """A minimal JSON Schema check for exactly the keywords the response schema uses."""

    if "oneOf" in schema:
        return sum(1 for branch in schema["oneOf"] if _accepts(branch, value)) == 1
    if "const" in schema:
        return bool(value == schema["const"]) and type(value) is type(schema["const"])
    if "enum" in schema:
        return value in schema["enum"] and isinstance(value, str)
    if schema.get("type") == "object":
        if not isinstance(value, dict) or set(value) != set(schema["required"]):
            return False
        return all(_accepts(schema["properties"][k], v) for k, v in value.items())
    if schema.get("type") == "array":
        return (
            isinstance(value, list) and schema["minItems"] <= len(value) <= schema["maxItems"]
            and all(_accepts(schema["items"], item) for item in value)
        )  # fmt: skip
    raise AssertionError(schema)


def _image_case() -> eval2.Case:
    return eval2.Case("img.x", eval2.KIND_IMAGE, ("a.x",))


def _pair_case() -> eval2.Case:
    return eval2.Case("pair.x", eval2.KIND_PAIR, ("a.x", "a.y"))


def _doc(**fields: Any) -> dict[str, Any]:
    return {"schema": eval2.RESPONSE_SCHEMA, "status": "ok", "kind": eval2.KIND_IMAGE, **fields}


GOOD_IMAGE = [
    _doc(verdict="clean", findings=[], subject_count="1"),
    _doc(verdict="defective", findings=[{"category": "Hands", "region": "top_left"}], subject_count="2"),
    _doc(verdict="defective", findings=[{"category": "Rendering artifact", "region": "whole_image"}] * 1,
         subject_count="5_or_more"),
    {"schema": eval2.RESPONSE_SCHEMA, "status": "refused", "refusal": "image_unreadable"},
]  # fmt: skip
BAD_IMAGE = [
    ("clean_with_findings", _doc(verdict="clean", findings=[{"category": "Hands", "region": "top"}], subject_count="1")),
    ("defective_without_findings", _doc(verdict="defective", findings=[], subject_count="1")),
    ("seven_findings", _doc(verdict="defective", subject_count="1",
                            findings=[{"category": "Hands", "region": z} for z in eval2.ZONES[:7]])),
    ("prompt_category", _doc(verdict="defective", findings=[{"category": "Prompt adherence", "region": "top"}],
                             subject_count="1")),
    ("lower_case_category", _doc(verdict="defective", findings=[{"category": "hands", "region": "top"}],
                                 subject_count="1")),
    ("unknown_region", _doc(verdict="defective", findings=[{"category": "Hands", "region": "middle"}],
                            subject_count="1")),
    ("missing_subject_count", _doc(verdict="clean", findings=[])),
    ("integer_subject_count", _doc(verdict="clean", findings=[], subject_count=1)),
    ("extra_field", _doc(verdict="clean", findings=[], subject_count="1", description="a person")),
    ("finding_note", _doc(verdict="defective", subject_count="1",
                          findings=[{"category": "Hands", "region": "top", "note": "six fingers"}])),
    ("free_text_refusal", {"schema": eval2.RESPONSE_SCHEMA, "status": "refused", "refusal": "I cannot"}),
    ("refusal_reason", {"schema": eval2.RESPONSE_SCHEMA, "status": "refused", "refusal": "declined",
                        "refusal_reason": "text"}),
    ("bare_status", {"schema": eval2.RESPONSE_SCHEMA, "status": "ok"}),
    ("wrong_schema", _doc(schema="stablenew.vl220.response/1", verdict="clean", findings=[], subject_count="1")),
    ("wrong_kind", _doc(kind=eval2.KIND_PAIR, verdict="clean", findings=[], subject_count="1")),
]  # fmt: skip


@pytest.mark.parametrize("document", GOOD_IMAGE)
def test_schema_and_validator_accept_the_same_good_answers(document: dict[str, Any]) -> None:
    schema = eval2.build_response_schema(eval2.KIND_IMAGE)
    assert _accepts(schema, document)
    assert eval2.validate_response(_image_case(), json.dumps(document)).status in (
        "valid",
        "model_refused",
    )


@pytest.mark.parametrize(("name", "document"), BAD_IMAGE, ids=[name for name, _ in BAD_IMAGE])
def test_schema_and_validator_refuse_the_same_near_misses(
    name: str, document: dict[str, Any]
) -> None:
    schema = eval2.build_response_schema(eval2.KIND_IMAGE)
    assert not _accepts(schema, document), name
    check = eval2.validate_response(_image_case(), json.dumps(document))
    assert check.status == eval2.STATUS_INVALID and check.answer is None, name


@pytest.mark.parametrize(
    ("text", "reason"),
    [
        ("not json", "not_json"),
        ('{"schema": "stablenew.vl220.response/2", "schema": "x"}', "not_json"),
        ('{"a": NaN}', "not_json"),
        ("[1]", "not_an_object"),
        ("{" + " " * (eval2.MAX_RESPONSE_BYTES + 1) + "}", "response_too_large"),
    ],
)
def test_malformed_text_is_invalid(text: str, reason: str) -> None:
    assert eval2.validate_response(_image_case(), text) == eval2.ResponseCheck(
        "invalid", reason, None
    )


def test_pair_answers_are_closed() -> None:
    schema = eval2.build_response_schema(eval2.KIND_PAIR)
    for answer in eval2.PAIR_ANSWERS:
        document = {
            "schema": eval2.RESPONSE_SCHEMA,
            "status": "ok",
            "kind": eval2.KIND_PAIR,
            "answer": answer,
        }
        assert _accepts(schema, document)
        assert eval2.validate_response(_pair_case(), json.dumps(document)).answer == {
            "answer": answer
        }
    bad = {
        "schema": eval2.RESPONSE_SCHEMA,
        "status": "ok",
        "kind": eval2.KIND_PAIR,
        "answer": "first",
    }
    assert not _accepts(schema, bad)
    assert eval2.validate_response(_pair_case(), json.dumps(bad)).status == "invalid"


def test_duplicate_findings_collapse_in_order() -> None:
    document = _doc(verdict="defective", subject_count="1", findings=[
        {"category": "Hands", "region": "top"}, {"category": "Face", "region": "top"},
        {"category": "Hands", "region": "top"},
    ])  # fmt: skip
    check = eval2.validate_response(_image_case(), json.dumps(document))
    assert check.answer is not None
    assert check.answer["findings"] == [
        {"category": "Hands", "region": "top"},
        {"category": "Face", "region": "top"},
    ]


def test_the_questions_carry_no_private_or_flag_text() -> None:
    for kind in eval2.KINDS:
        text = eval2.prompt_for(kind)
        assert "--" not in text and len(text) < 2000
    for category in eval2.CATEGORIES:
        assert category in eval2.IMAGE_PROMPT
    for zone in eval2.REGIONS:
        assert zone in eval2.IMAGE_PROMPT
    assert Category.PROMPT.value not in eval2.IMAGE_PROMPT


# ----------------------------------------------------------------------------------------------------- scoring


def _ref(
    verdict: str, *findings: tuple[str, tuple[str, ...] | None], subjects: int | None = None
) -> ImageReference:
    return ImageReference(verdict, tuple(HumanFinding(c, z) for c, z in findings), subjects)


def _result(answer: dict[str, Any] | None, status: str = "valid") -> CaseResult:
    return CaseResult("img.x", status if answer is not None else "invalid", "", 1.0, 10, answer)


def test_scoring_by_construction_and_near_misses() -> None:
    hands = _ref("defective", ("Hands", ("top_left",)), subjects=2)
    exact = eval2_scoring.image_outcome(
        hands, _result(sup.image_answer("defective", [("Hands", "top_left")], "2"))
    )
    assert (exact.tp, exact.fp, exact.fn, exact.category_tp) == (1, 0, 0, 1) and exact.correct
    zone_miss = eval2_scoring.image_outcome(
        hands, _result(sup.image_answer("defective", [("Hands", "bottom")]))
    )
    assert (zone_miss.tp, zone_miss.fp, zone_miss.fn) == (0, 1, 1)
    assert (zone_miss.category_tp, zone_miss.category_fp) == (1, 0) and zone_miss.correct
    category_miss = eval2_scoring.image_outcome(
        hands, _result(sup.image_answer("defective", [("Face", "top_left")]))
    )
    assert (category_miss.tp, category_miss.category_tp) == (0, 0)
    whole = eval2_scoring.image_outcome(
        hands, _result(sup.image_answer("defective", [("Hands", "whole_image")]))
    )
    assert whole.tp == 0
    missed = eval2_scoring.image_outcome(hands, _result(sup.image_answer("clean")))
    assert (missed.flagged, missed.fn, missed.correct) == (False, 1, False)
    no_region = eval2_scoring.image_outcome(
        _ref("defective", ("Anatomy", None)),
        _result(sup.image_answer("defective", [("Anatomy", "right")])),
    )
    assert no_region.tp == 1
    unanswered = eval2_scoring.image_outcome(hands, _result(None))
    assert (unanswered.predicted, unanswered.fn, unanswered.correct) == (None, 1, False)


def test_unanswered_clean_images_count_as_not_cleared() -> None:
    clean = _ref("clean", subjects=1)
    rows = [
        eval2_scoring.image_outcome(clean, _result(sup.image_answer("clean"))),
        eval2_scoring.image_outcome(clean, _result(None)),
        eval2_scoring.image_outcome(
            clean, _result(sup.image_answer("defective", [("Face", "center")]))
        ),
    ]
    detection = eval2_scoring.image_metrics(rows)["image_detection"]
    assert (detection["tn"], detection["not_cleared"], detection["unanswered_clean"]) == (1, 2, 1)
    assert detection["false_alarm_rate"] == round(2 / 3, 6)
    assert eval2_scoring.image_metrics(rows)["hallucination"]["findings_on_clean_images"] == 1


def test_maximum_matching_beats_greedy() -> None:
    # Answer 0 fits human 0 and 1; answer 1 fits human 0 only: greedy taking (0, 0) would find one, the optimum two.
    fits = {(0, 0), (0, 1), (1, 0)}
    assert eval2_scoring.max_matching(2, 2, lambda i, j: (i, j) in fits) == 2
    human = (HumanFinding("Hands", ("top", "top_left")), HumanFinding("Hands", ("top",)))
    answer = [{"category": "Hands", "region": "top"}, {"category": "Hands", "region": "top_left"}]
    assert eval2_scoring.match_findings(answer, human) == (2, 0, 0)


@pytest.mark.parametrize(
    ("answer", "after_first", "judgment"),
    [
        ("first_better", True, "helped"), ("first_better", False, "worse"),
        ("second_better", True, "worse"), ("second_better", False, "helped"),
        ("no_clear_difference", True, "no_benefit"), ("no_clear_difference", False, "no_benefit"),
    ],
)  # fmt: skip
def test_pair_answers_map_to_judgments(answer: str, after_first: bool, judgment: str) -> None:
    assert eval2_scoring.pair_judgment(answer, after_first) == judgment


def test_pair_metrics_exclude_inconclusive_and_match_no_benefit() -> None:
    rows = [
        eval2_scoring.PairOutcome("p1", "helped", "helped", 1.0, "valid"),
        eval2_scoring.PairOutcome("p2", "no_benefit", "no_benefit", 1.0, "valid"),
        eval2_scoring.PairOutcome("p3", "worse", "no_benefit", 1.0, "valid"),
        eval2_scoring.PairOutcome("p4", "inconclusive", "helped", 1.0, "valid"),
        eval2_scoring.PairOutcome("p5", "helped", None, 1.0, "invalid"),
    ]
    metrics = eval2_scoring.pair_metrics(rows)
    assert (
        metrics["scored"],
        metrics["agree"],
        metrics["inconclusive_excluded"],
        metrics["unanswered"],
    ) == (4, 2, 1, 1)
    assert (
        metrics["helped_binary_agree"] == 3
    )  # p1, p2, p3 agree on helped vs not; p5 has no answer
    only_inconclusive = eval2_scoring.pair_metrics(rows[3:4])
    assert only_inconclusive == {
        "evaluated": False,
        "reason": "no_conclusive_pair_judgment",
        "pairs": 1,
    }


def test_subject_counts() -> None:
    assert eval2_scoring.subject_count_agrees("5_or_more", 7)
    assert not eval2_scoring.subject_count_agrees("5_or_more", 4)
    assert eval2_scoring.subject_count_agrees("2", 2) and not eval2_scoring.subject_count_agrees(
        "3", 2
    )
    rows = [
        eval2_scoring.image_outcome(_ref("clean", subjects=1), _result(sup.image_answer("clean")))
    ]
    assert eval2_scoring.image_metrics(rows)["multi_subject"]["evaluated"] is False


# ------------------------------------------------------------------------------------------------- persistence

SECRET = "PRIVATE-ANSWER-TEXT"


def test_an_evidence_record_never_carries_answer_text() -> None:
    case = _image_case()
    leaky = json.dumps(_doc(verdict="clean", findings=[], subject_count="1", description=SECRET))
    check = eval2.validate_response(case, leaky)
    record = eval2.evidence_record(case, check, wall_seconds=1.0, peak_working_set_bytes=1)
    assert (
        record["answer"] is None
        and record["status"] == "invalid"
        and SECRET not in canonical_json(record)
    )
    good = eval2.validate_response(case, json.dumps(GOOD_IMAGE[1]))
    record = eval2.evidence_record(case, good, wall_seconds=2.5, peak_working_set_bytes=7)
    assert set(record) == {
        "case_id",
        "status",
        "reason",
        "wall_seconds",
        "peak_working_set_bytes",
        "answer",
    }
    refused = eval2.validate_response(case, json.dumps(GOOD_IMAGE[3]))
    assert (
        eval2.evidence_record(case, refused, wall_seconds=1, peak_working_set_bytes=1)["reason"]
        == "image_unreadable"
    )
    with pytest.raises(ContractViolation):
        eval2.evidence_record(
            case,
            None,
            wall_seconds=1,
            peak_working_set_bytes=1,
            run_status="timeout",
            reason="took long",
        )


def _evidence() -> tuple[dict[str, Any], eval2.CaseSet]:
    cases, labels_doc, case_set, labels = sup.documents(
        sup.standard_export(clean=3, defective=3, multi=1, pairs=2)
    )
    document = sup.scripted(
        case_set,
        labels,
        sup.truthful(),
        tier="fast",
        plan_sha256="a" * 64,
        case_set_sha256=contract.digest(cases),
    )
    return document, case_set


def _strings(value: Any) -> list[str]:
    if isinstance(value, str):
        return [value]
    if isinstance(value, dict):
        return [s for k, v in value.items() for s in [k, *_strings(v)]]
    if isinstance(value, list):
        return [s for item in value for s in _strings(item)]
    return []


def test_every_persisted_string_is_a_closed_token_an_id_or_a_digest() -> None:
    document, case_set = _evidence()
    eval2.validate_evidence(document, case_set)
    closed = (
        set(eval2.CATEGORIES) | set(eval2.REGIONS) | set(eval2.VERDICTS) | set(eval2.SUBJECT_COUNTS)
    )
    closed |= (
        set(eval2.PAIR_ANSWERS)
        | set(eval2.REFUSALS)
        | set(eval2.RUN_STATUSES)
        | set(eval2.TIERS)
        | {""}
    )
    closed |= {eval2.EVIDENCE_SCHEMA, eval2.CONTRACT_ID, sup.FAST_ID}
    closed |= {"schema", "contract_id", "plan_sha256", "case_set_sha256", "candidate_id", "tier", "complete", "cases",
               "case_id", "status", "reason", "wall_seconds", "peak_working_set_bytes", "answer", "verdict", "findings",
               "subject_count", "category", "region"}  # fmt: skip
    for text in _strings(document):
        assert text in closed or text.startswith(("img.", "pair.")) or len(text) == 64, text


def _break(document: dict[str, Any], how: str) -> None:
    rows = document["cases"]
    image_row = next(
        r for r in rows if r["case_id"].startswith("img.") and r["answer"]["verdict"] == "defective"
    )
    if how == "answer_note":
        image_row["answer"]["note"] = SECRET
    elif how == "finding_text":
        image_row["answer"]["findings"][0]["category"] = SECRET
    elif how == "reason_text":
        image_row["reason"] = "the model said: " + SECRET
    elif how == "record_text":
        image_row["text"] = SECRET
    elif how == "top_level_text":
        document["notes"] = SECRET
    elif how == "answer_on_invalid":
        image_row["status"] = "invalid"
    elif how == "missing_case":
        rows.pop()
    elif how == "unknown_status":
        image_row["status"] = "ok"
    elif how == "free_refusal":
        image_row.update(status="model_refused", answer=None, reason="declined_because_private")
    elif how == "unnormalized":
        image_row["answer"]["findings"] = image_row["answer"]["findings"] * 2


@pytest.mark.parametrize(
    "how",
    ["answer_note", "finding_text", "reason_text", "record_text", "top_level_text", "answer_on_invalid", "missing_case",
     "unknown_status", "free_refusal", "unnormalized"],
)  # fmt: skip
def test_evidence_with_anything_but_closed_values_is_refused(how: str) -> None:
    document, case_set = _evidence()
    _break(document, how)
    with pytest.raises(ContractViolation):
        eval2.validate_evidence(document, case_set)
