"""AI-VL-242: intervals, the paired test, floors, the Florence-2 comparator, escalation rules, gates, plan and report.

Synthetic fixtures only (``vl242_support``); no model, image or real label is used."""

from __future__ import annotations

import ast
import copy
import json
import re
import socket
import subprocess
from dataclasses import replace
from pathlib import Path
from typing import Any

import pytest

from tests.tools import vl242_support as sup
from tools.qualification.vl220 import eval2
from tools.qualification.vl220.contract import ContractViolation, digest
from tools.qualification.vl242 import analysis, gates, plan, report, stats

REPO = Path(__file__).resolve().parents[2]
PACKAGE = REPO / "tools" / "qualification" / "vl242"
CONTRACT_DOC = REPO / plan.CONTRACT_DOCUMENT


# ------------------------------------------------------------------------------------------------------ statistics


@pytest.mark.parametrize(
    ("k", "n", "low", "high"),
    [(5, 20, 0.1119, 0.4687), (0, 20, 0.0, 0.1611), (20, 20, 0.8389, 1.0), (15, 30, 0.3315, 0.6685),
     (59, 62, 0.8671, 0.9834)],
)  # fmt: skip
def test_wilson_matches_published_values(k: int, n: int, low: float, high: float) -> None:
    interval = stats.wilson(k, n)
    assert interval is not None
    assert interval[0] == pytest.approx(low, abs=1e-4) and interval[1] == pytest.approx(
        high, abs=1e-4
    )
    assert stats.wilson(0, 0) is None


@pytest.mark.parametrize(
    ("b", "c", "one", "two"),
    [
        (8, 1, 10 / 512, 20 / 512),
        (0, 0, 1.0, 1.0),
        (5, 0, 1 / 32, 2 / 32),
        (3, 3, 42 / 64, 1.0),
        (1, 6, 127 / 128, 16 / 128),
    ],
)
def test_exact_mcnemar(b: int, c: int, one: float, two: float) -> None:
    result = stats.mcnemar(b, c)
    assert result.p_one_sided == pytest.approx(one, abs=1e-9)
    assert result.p_two_sided == pytest.approx(two, abs=1e-9)


def test_mcnemar_needs_five_discordant_images_for_p_0_05() -> None:
    assert stats.mcnemar_minimum_discordant(0.05) == 5
    assert stats.mcnemar(4, 0).p_one_sided > 0.05 >= stats.mcnemar(5, 0).p_one_sided


def test_bootstrap_is_deterministic_and_keeps_strata() -> None:
    sizes: list[int] = []

    def mean(idx: Any) -> float:
        sizes.append(len(idx))
        return sum(1 for i in idx if i < 3) / len(idx)

    strata = [[0, 1, 2], [3, 4, 5, 6, 7]]
    first = stats.bootstrap(strata, mean, resamples=200, seed=7)
    second = stats.bootstrap(strata, mean, resamples=200, seed=7)
    assert first == second and set(sizes) == {8}
    assert (
        first.point == first.low == first.high == 0.375
    )  # stratum sizes fixed: the share never moves
    constant = stats.bootstrap([[0, 1]], lambda idx: None, resamples=10, seed=1)
    assert constant.defined == 0 and constant.low is None


# ----------------------------------------------------------------------------------------------------- fixtures


def _full(
    fast_policy: sup.Policy, deep_policy: sup.Policy, *, stage: str = "full", **plan_kwargs: Any
) -> Any:
    cases, labels_doc, case_set, labels = sup.documents(sup.standard_export())
    built = sup.planned(cases, labels_doc, stage=stage, **plan_kwargs)
    keys = {
        "plan_sha256": built["plan_sha256"],
        "case_set_sha256": built["case_set"]["case_set_sha256"],
    }
    fast = eval2.validate_evidence(
        sup.scripted(case_set, labels, fast_policy, tier="fast", **keys), case_set
    )
    deep = eval2.validate_evidence(
        sup.scripted(case_set, labels, deep_policy, tier="deep", **keys), case_set
    )
    return case_set, labels, fast, deep, built


def _noisy(false_alarms: int, misses: int, seconds: float) -> sup.Policy:
    """Truthful except for the first ``false_alarms`` clean images (flagged) and ``misses`` defective images (cleared)."""

    seen = {"clean": 0, "defective": 0}
    truthful = sup.truthful(seconds)

    def policy(case: eval2.Case, reference: Any) -> tuple[Any, float]:
        if case.kind == eval2.KIND_IMAGE:
            seen[reference.verdict] += 1
            if reference.verdict == "clean" and seen["clean"] <= false_alarms:
                return sup.image_answer("defective", [("Face", "center")]), seconds
            if reference.verdict == "defective" and seen["defective"] <= misses:
                return sup.image_answer(
                    "clean", subjects=str(reference.subject_count or 1)
                ), seconds
        return truthful(case, reference)

    return policy


# -------------------------------------------------------------------------------------------------------- floors


def test_floors_on_the_planned_set() -> None:
    case_set, labels, *_ = _full(sup.truthful(), sup.truthful())
    table = analysis.floors(case_set, labels)
    clean, defect, frequent = table["always_clean"], table["always_defect"], table["most_frequent"]
    assert (clean["image_detection"]["recall"], clean["image_detection"]["false_alarm_rate"]) == (
        0.0,
        0.0,
    )
    assert (defect["image_detection"]["recall"], defect["image_detection"]["false_alarm_rate"]) == (
        1.0,
        1.0,
    )
    assert (
        defect["image_detection"]["f1"] == 0.75
    )  # 2*30 / (2*30 + 20): why F1 is not the floor comparison
    for row in (clean, defect, frequent):
        assert row["image_detection"]["balanced_accuracy"] == 0.5
    assert defect["finding_triage"]["precision"] == 0.0  # a content-free alarm matches no region
    assert frequent["finding_triage"]["precision"] == round(
        4 / 30, 6
    )  # the modal (category, zone) on every image
    assert (
        frequent["multi_subject"]["agreement"] == 0.0
    )  # modal count 1 never matches a two-subject image
    assert table["always_worse"]["before_after"]["agreement"] == round(3 / 9, 6)
    assert "image_detection" not in table["always_worse"]


def test_floor_answers_are_valid_contract_answers() -> None:
    case_set, labels, *_ = _full(sup.truthful(), sup.truthful())
    case = next(c for c in case_set.cases if c.kind == eval2.KIND_IMAGE)
    for answer in analysis.floor_answers(case_set, labels).values():
        assert eval2.validate_response(case, sup.response_text(case, answer)).status == "valid"


# ---------------------------------------------------------------------------------------------------- comparator


def _florence(
    case_set: eval2.CaseSet, labels: eval2.LabelSet, built: dict[str, Any], right: int
) -> dict[str, Any]:
    rows, given = [], 0
    for case in case_set.cases:
        if case.kind != eval2.KIND_IMAGE:
            continue
        truth = labels.image(case.case_id).subject_count
        if truth is not None and truth >= 2:
            given += 1
            answer: str | None = str(truth) if given <= right else "1"
        else:
            answer = None
        rows.append({"case_id": case.case_id, "subject_count": answer})
    return {"schema": analysis.COMPARATOR_SCHEMA, "comparator_id": analysis.FLORENCE_ID,
            "case_set_sha256": built["case_set"]["case_set_sha256"], "cases": rows}  # fmt: skip


def test_florence_answers_only_subject_counts() -> None:
    case_set, labels, fast, deep, built = _full(
        sup.truthful(), sup.truthful(), florence_in_scope=True
    )
    result = analysis.analyze(
        case_set, labels, fast, deep, built, florence=_florence(case_set, labels, built, 7)
    )
    part = result["florence"]
    assert (
        part["multi_subject"]["agree"] == 7 and part["multi_subject"]["multi_subject_images"] == 10
    )
    assert set(part["not_addressable"]) == {
        "image_detection",
        "finding_triage",
        "before_after",
        "structured_validity",
    }
    assert set(part) == {"comparator_id", "dimensions", "not_addressable", "multi_subject"}


def test_florence_input_is_closed_and_needs_the_plan() -> None:
    case_set, labels, fast, deep, built = _full(sup.truthful(), sup.truthful())
    document = _florence(case_set, labels, built, 3)
    with pytest.raises(analysis.AnalysisRefused, match="florence_not_in_plan"):
        analysis.analyze(case_set, labels, fast, deep, built, florence=document)
    leaky = copy.deepcopy(document)
    leaky["cases"][0]["caption"] = "a person"
    with pytest.raises(ContractViolation):
        analysis.validate_comparator(leaky, case_set)
    defect = copy.deepcopy(document)
    defect["cases"][0]["subject_count"] = "defective"
    with pytest.raises(ContractViolation):
        analysis.validate_comparator(defect, case_set)


# ------------------------------------------------------------------------------------------------------ paired


def test_paired_comparison_counts_discordant_images() -> None:
    case_set, labels, fast, deep, built = _full(_noisy(4, 6, 4.0), _noisy(1, 1, 60.0))
    result = analysis.analyze(case_set, labels, fast, deep, built)
    correctness = result["paired"]["correctness"]
    assert (correctness["deep_right_fast_wrong"], correctness["fast_right_deep_wrong"]) == (8, 0)
    assert correctness["p_one_sided_deep_better"] == pytest.approx(1 / 256)
    assert result["paired"]["defective_images"]["deep_right_fast_wrong"] == 5
    assert result["paired"]["clean_images"]["deep_right_fast_wrong"] == 3


# -------------------------------------------------------------------------------------------------- escalation


def _four_image_tiers(
    fast_answers: list[Any], deep_answers: list[Any]
) -> tuple[analysis.TierAnalysis, ...]:
    """Two defective images (Hands, top-left) then two clean ones; fast takes 2 s and deep 10 s per image."""

    document = sup.export(
        [sup.image(f"d{i}", clean=False, findings=[sup.finding()]) for i in range(2)]
        + [sup.image(f"c{i}") for i in range(2)]
    )
    cases, _, case_set, labels = sup.documents(document)
    order = {
        f"img.{sup.sha(name)[:20]}": index for index, name in enumerate(("d0", "d1", "c0", "c1"))
    }
    tiers = []
    for tier, answers, seconds in (("fast", fast_answers, 2.0), ("deep", deep_answers, 10.0)):

        def policy(
            case: eval2.Case, reference: Any, answers: list[Any] = answers, s: float = seconds
        ) -> Any:
            return answers[order[case.case_id]], s

        evidence = eval2.validate_evidence(
            sup.scripted(
                case_set,
                labels,
                policy,
                tier=tier,
                plan_sha256="b" * 64,
                case_set_sha256=digest(cases),
            ),
            case_set,
        )
        tiers.append(
            analysis.tier_analysis(
                case_set, labels, evidence, analysis.TierLimits(180.0, 8 * 1024**3, 30.0)
            )
        )
    # Case order is by image digest: present the rows in d0, d1, c0, c1 order for readability.
    return tuple(
        replace(t, images=tuple(sorted(t.images, key=lambda row: order[row.case_id])))
        for t in tiers
    )


FLAG = sup.image_answer("defective", [("Hands", "top_left")])
CLEAR = sup.image_answer("clean")


def test_every_escalation_rule_on_a_hand_computed_example() -> None:
    # d0: fast flags, deep flags. d1: fast clears (miss), deep flags. c0: fast flags (false alarm), deep clears. c1: both clear.
    fast, deep = _four_image_tiers([FLAG, CLEAR, FLAG, CLEAR], [FLAG, FLAG, CLEAR, CLEAR])
    rows = analysis.escalation(fast, deep, 0.5)
    expected = {
        "never": (0.5, 0.5, 0.0, 2.0),
        "always": (1.0, 0.0, 1.0, 12.0),
        "on_defect": (
            0.5,
            0.0,
            0.5,
            7.0,
        ),  # d0, c0 escalated: c0's alarm withdrawn, d1 still missed
        "on_clean": (1.0, 0.5, 0.5, 7.0),  # d1, c1 escalated: d1 caught, c0's alarm stays
        "deep_only": (1.0, 0.0, None, 10.0),
    }
    for rule, (recall, false_alarm, escalated, seconds) in expected.items():
        row = rows[rule]
        assert (row["recall"], row["false_alarm_rate"], row["escalation_rate"]) == (
            recall,
            false_alarm,
            escalated,
        ), rule
        assert row["mean_seconds_per_image"] == seconds == row["seconds_at_operator_share"], rule
    assert (
        rows["on_defect"]["time_vs_deep"] == 0.7
        and rows["never"]["recall_shortfall_vs_deep"] == 0.5
    )
    assert rows["operator_requested"]["same_as"] == ["never", "deep_only"]


def test_escalation_time_is_weighted_by_the_operator_share() -> None:
    fast, deep = _four_image_tiers([FLAG, CLEAR, FLAG, CLEAR], [FLAG, FLAG, CLEAR, CLEAR])
    # on_defect: defective images cost 12 and 2 (mean 7), clean images 12 and 2 (mean 7). on_clean likewise.
    # never: 2 everywhere. Use an uneven case: fast flags both defective and neither clean.
    fast, deep = _four_image_tiers([FLAG, FLAG, CLEAR, CLEAR], [FLAG, FLAG, CLEAR, CLEAR])
    row = analysis.escalation(fast, deep, 0.25)["on_defect"]
    assert row["seconds_by_share"] == {
        "0.25": 4.5,
        "0.5": 7.0,
        "0.75": 9.5,
    }  # 12 on defective, 2 on clean
    assert row["seconds_at_operator_share"] == 4.5


def test_unanswered_fast_escalates_and_unanswered_deep_falls_back() -> None:
    fast, deep = _four_image_tiers([None, CLEAR, None, CLEAR], [FLAG, None, CLEAR, CLEAR])
    on_defect = analysis.simulate("on_defect", fast, deep)
    assert on_defect[2] == 2  # both unanswered fast images escalate
    assert [row.predicted for row in on_defect[0]] == ["defective", "clean", "clean", "clean"]
    on_clean = analysis.simulate("on_clean", fast, deep)
    assert on_clean[2] == 4
    assert on_clean[0][1].predicted == "clean"  # deep gave nothing for d1: the fast answer stands
    with pytest.raises(analysis.AnalysisRefused):
        analysis.simulate("sometimes", fast, deep)


# ------------------------------------------------------------------------------------------------------- gates


def _base() -> dict[str, Any]:
    case_set, labels, fast, deep, built = _full(_noisy(2, 3, 4.0), _noisy(1, 0, 30.0))
    return analysis.analyze(case_set, labels, fast, deep, built)


@pytest.fixture(scope="module")
def base() -> dict[str, Any]:
    return _base()


def _verdict(result: dict[str, Any], gate_id: str) -> str:
    return next(v.verdict for v in gates.evaluate(result) if v.gate_id == gate_id)


def test_a_good_paired_run_passes_every_tier_gate(base: dict[str, Any]) -> None:
    verdicts = {v.gate_id: v.verdict for v in gates.evaluate(base)}
    assert {k: v for k, v in verdicts.items() if k != "D4" and k != "T1"} == dict.fromkeys(
        ["F1", "F2", "F3", "F4", "F5", "D1", "D2", "D3", "D5", "D6"], "PASS"
    )
    assert verdicts["D4"] == "FAIL"  # deep F1 gain 0.07 is below 0.15 (by construction)
    assert verdicts["T1"] == "NOT_APPLICABLE"


def _set_interval(result: dict[str, Any], tier: str, metric: str, value: float) -> None:
    target = (
        result["tiers"][tier]["structured"]["interval"]
        if metric == "valid_rate"
        else (result["tiers"][tier]["intervals"][metric])
    )
    target.update(point=value, low=0.0, high=1.0, lower_95=0.0, upper_95=1.0)


@pytest.mark.parametrize(
    ("gate_id", "tier", "metric", "at", "inside", "outside"),
    [
        ("F1", "fast", "valid_rate", 0.95, 0.951, 0.949),
        ("F2", "fast", "false_alarm_rate", 0.25, 0.249, 0.251),
        ("F3", "fast", "recall", 0.50, 0.501, 0.499),
        ("D1", "deep", "valid_rate", 0.95, 0.951, 0.949),
        ("D2", "deep", "false_alarm_rate", 0.15, 0.149, 0.151),
        ("D3", "deep", "finding_precision", 0.60, 0.601, 0.599),
    ],
)
def test_point_gates_at_and_around_their_thresholds(
    base: dict[str, Any],
    gate_id: str,
    tier: str,
    metric: str,
    at: float,
    inside: float,
    outside: float,
) -> None:
    for value, verdict in ((at, "PASS"), (inside, "PASS"), (outside, "FAIL")):
        result = copy.deepcopy(base)
        _set_interval(result, tier, metric, value)
        assert _verdict(result, gate_id) == verdict, (gate_id, value)


@pytest.mark.parametrize(("gate_id", "tier"), [("F4", "fast"), ("D5", "deep")])
def test_floor_gates_need_the_lower_bound_strictly_above_the_best_floor(
    base: dict[str, Any], gate_id: str, tier: str
) -> None:
    for lower, verdict in ((0.5, "FAIL"), (0.501, "PASS"), (0.499, "FAIL")):
        result = copy.deepcopy(base)
        result["tiers"][tier]["intervals"]["balanced_accuracy"].update(lower_95=lower, upper_95=0.9)
        assert _verdict(result, gate_id) == verdict, lower


def test_finding_precision_must_also_beat_the_best_floor(base: dict[str, Any]) -> None:
    result = copy.deepcopy(base)
    _set_interval(result, "deep", "finding_precision", 0.7)
    result["best_floor_finding_precision"] = 0.7
    assert _verdict(result, "D3") == "FAIL"
    result["best_floor_finding_precision"] = 0.69
    assert _verdict(result, "D3") == "PASS"


@pytest.mark.parametrize(
    ("gain", "b", "c", "p", "verdict"),
    [
        (0.15, 9, 1, 0.05, "PASS"), (0.151, 9, 1, 0.01, "PASS"), (0.149, 9, 1, 0.01, "FAIL"),
        (0.2, 9, 1, 0.051, "FAIL"), (0.2, 3, 3, 0.01, "FAIL"),
    ],
)  # fmt: skip
def test_the_deep_over_fast_gate_needs_gain_and_the_paired_test(
    base: dict[str, Any], gain: float, b: int, c: int, p: float, verdict: str
) -> None:
    result = copy.deepcopy(base)
    result["paired"]["f1_gain"].update(point=gain, low=0.0, high=0.5)
    result["paired"]["correctness"].update(
        deep_right_fast_wrong=b, fast_right_deep_wrong=c, p_one_sided_deep_better=p
    )
    assert _verdict(result, "D4") == verdict


@pytest.mark.parametrize(("violations", "verdict"), [(0, "PASS"), (1, "FAIL")])
def test_resource_gates(base: dict[str, Any], violations: int, verdict: str) -> None:
    result = copy.deepcopy(base)
    result["tiers"]["deep"]["resources"]["resource_violations"] = violations
    assert _verdict(result, "D6") == verdict


def _two_tier_ready(base: dict[str, Any]) -> dict[str, Any]:
    result = copy.deepcopy(base)
    result["paired"]["f1_gain"].update(point=0.2, low=0.1, high=0.3)
    result["paired"]["correctness"].update(
        deep_right_fast_wrong=9, fast_right_deep_wrong=1, p_one_sided_deep_better=0.01
    )
    rows = result["escalation"]
    rows["deep_only"].update(seconds_at_operator_share=100.0, recall=0.9)
    rows["on_clean"].update(
        recall=0.0,
        recall_shortfall_vs_deep=0.9,
        false_alarm_rate=0.0,
        seconds_at_operator_share=10.0,
    )
    rows["on_defect"].update(recall=0.85, recall_shortfall_vs_deep=0.05, false_alarm_rate=0.15,
                             seconds_at_operator_share=50.0)  # fmt: skip
    return result


@pytest.mark.parametrize(
    ("change", "verdict"),
    [
        ({}, "PASS"),
        ({"recall_shortfall_vs_deep": 0.051}, "FAIL"),
        ({"recall_shortfall_vs_deep": 0.049}, "PASS"),
        ({"false_alarm_rate": 0.151}, "FAIL"),
        ({"seconds_at_operator_share": 50.1}, "FAIL"),
        ({"seconds_at_operator_share": 49.9}, "PASS"),
    ],
)
def test_the_two_tier_gate(base: dict[str, Any], change: dict[str, float], verdict: str) -> None:
    result = _two_tier_ready(base)
    assert all(_verdict(result, g) == "PASS" for g in ("D1", "D2", "D3", "D4", "D5", "D6"))
    result["escalation"]["on_defect"].update(change)
    assert _verdict(result, "T1") == verdict


def test_the_two_tier_gate_is_not_applicable_when_the_deep_tier_fails(base: dict[str, Any]) -> None:
    result = _two_tier_ready(base)
    _set_interval(result, "deep", "false_alarm_rate", 0.3)
    assert _verdict(result, "T1") == "NOT_APPLICABLE"


def test_a_pilot_can_stop_a_failing_tier_but_never_pass_one(base: dict[str, Any]) -> None:
    result = copy.deepcopy(base)
    result["stage"] = "pilot"
    verdicts = {v.gate_id: v.verdict for v in gates.evaluate(result)}
    assert "PASS" not in verdicts.values()
    assert verdicts["F2"] == "NOT_DECIDED"
    result["tiers"]["fast"]["intervals"]["false_alarm_rate"].update(point=0.6, low=0.3, high=0.8)
    assert _verdict(result, "F2") == "FAIL"  # the whole interval is above 0.25
    result["tiers"]["fast"]["intervals"]["recall"].update(point=0.2, low=0.1, high=0.45)
    assert _verdict(result, "F3") == "FAIL"
    result["tiers"]["fast"]["resources"]["resource_violations"] = 1
    assert _verdict(result, "F5") == "FAIL"


def test_a_full_run_below_the_planned_sample_cannot_pass() -> None:
    document = sup.standard_export(clean=12, defective=18, multi=5, pairs=4)
    cases, labels_doc, case_set, labels = sup.documents(document)
    built = sup.planned(cases, labels_doc, stage="full")
    keys = {
        "plan_sha256": built["plan_sha256"],
        "case_set_sha256": built["case_set"]["case_set_sha256"],
    }
    fast = eval2.validate_evidence(
        sup.scripted(case_set, labels, sup.truthful(4.0), tier="fast", **keys), case_set
    )
    deep = eval2.validate_evidence(
        sup.scripted(case_set, labels, sup.truthful(30.0), tier="deep", **keys), case_set
    )
    verdicts = {
        v.gate_id: v.verdict
        for v in gates.evaluate(analysis.analyze(case_set, labels, fast, deep, built))
    }
    assert "PASS" not in verdicts.values()
    assert verdicts["F2"] == "INSUFFICIENT_SAMPLE"


# -------------------------------------------------------------------------------------------------------- plan


def test_the_plan_binds_every_input_and_no_case_content() -> None:
    cases, labels_doc, *_ = sup.documents(sup.standard_export())
    built = sup.planned(cases, labels_doc)
    assert built == sup.planned(cases, labels_doc)
    assert built["plan_sha256"] == digest({k: v for k, v in built.items() if k != "plan_sha256"})
    assert built["executes_models"] is False and built["qualified"] is False
    assert built["contract"]["gate_set"]["status"] == "proposed_pending_owner_approval"
    assert {t["candidate_id"] for t in built["tiers"].values()} == {sup.FAST_ID, sup.DEEP_ID}
    text = json.dumps(built)
    assert (
        "img." not in text
        and "pair." not in text
        and "a." + cases["assets"][0]["sha256"][:20] not in text
    )
    variants = [
        sup.planned(cases, labels_doc, stage="pilot"),
        sup.planned(cases, labels_doc, florence_in_scope=True),
        sup.planned(cases, labels_doc, operator_defect_share=0.4),
        sup.planned(cases, labels_doc, fast_limits=analysis.TierLimits(120.0, 4 * 1024**3, 15.0)),
    ]
    other_cases, other_labels, *_ = sup.documents(sup.standard_export(clean=21))
    variants.append(sup.planned(other_cases, other_labels))
    digests = {built["plan_sha256"], *(v["plan_sha256"] for v in variants)}
    assert len(digests) == 6


def test_changing_a_gate_value_changes_the_plan(monkeypatch: pytest.MonkeyPatch) -> None:
    cases, labels_doc, *_ = sup.documents(sup.standard_export())
    before = sup.planned(cases, labels_doc)["plan_sha256"]
    changed = tuple(replace(g, threshold=0.2) if g.gate_id == "F2" else g for g in eval2.GATES)
    monkeypatch.setattr(eval2, "GATES", changed)
    assert sup.planned(cases, labels_doc)["plan_sha256"] != before


def test_default_limits_are_marked_as_proposed() -> None:
    cases, labels_doc, *_ = sup.documents(sup.standard_export())
    built = sup.planned(cases, labels_doc)
    assert {t["limits_source"] for t in built["tiers"].values()} == {plan.LIMITS_PROPOSED}
    assert built["tiers"]["deep"]["limits"]["max_peak_working_set_bytes"] == 12 * 1024**3
    owner = sup.planned(
        cases, labels_doc, deep_limits=analysis.TierLimits(600.0, 12 * 1024**3, 240.0)
    )
    assert owner["tiers"]["deep"]["limits_source"] == plan.LIMITS_OWNER


@pytest.mark.parametrize("problem", ["plan", "tier", "candidate", "case_set"])
def test_analysis_refuses_evidence_from_another_plan(problem: str) -> None:
    case_set, labels, fast, deep, built = _full(sup.truthful(), sup.truthful())
    if problem == "plan":
        fast = replace(fast, plan_sha256="c" * 64)
    elif problem == "tier":
        fast = replace(fast, tier="deep")
    elif problem == "candidate":
        deep = replace(deep, candidate_id=sup.FAST_ID)
    else:
        deep = replace(deep, case_set_sha256="d" * 64)
    with pytest.raises(analysis.AnalysisRefused):
        analysis.analyze(case_set, labels, fast, deep, built)


# ------------------------------------------------------------------------------------------------------ report


def test_the_report_has_one_table_per_question_and_one_verdict_per_gate(
    base: dict[str, Any],
) -> None:
    text = report.render(base, gates.evaluate(base))
    for title in ("Structured validity", "Image-level defect detection", "Finding-level triage", "Clean-image false",
                  "Paired comparison", "Before/after usefulness", "Multi-subject consistency", "Not evaluated",
                  "Resources", "Escalation simulation", "Gate verdicts"):  # fmt: skip
        assert f"## {title}" in text
    assert len(re.findall(r"^- \*\*[FDT]\d ", text, flags=re.M)) == len(eval2.GATES)
    assert "img." not in text and "pair." not in text and "qualified: false" in text
    assert "not a promotion, not a qualified label and not a production entry point" in text


# ------------------------------------------------------------------------------------------------- the contract


def test_the_contract_document_states_every_gate_value_and_its_status() -> None:
    text = CONTRACT_DOC.read_text(encoding="utf-8")
    assert "proposed, pending owner approval" in text and eval2.GATE_SET_ID in text
    for gate in eval2.GATES:
        row = re.search(rf"^\| {gate.gate_id} \|(.+)$", text, flags=re.M)
        assert row is not None, gate.gate_id
        assert f"{gate.op} {gate.threshold:g}" in row.group(1).replace("≥", ">=").replace(
            "≤", "<="
        ), gate.gate_id


# -------------------------------------------------------------------------------------- no network, no process


def test_the_package_cannot_open_sockets_or_spawn_a_child() -> None:
    forbidden = {
        "socket", "ssl", "http", "urllib", "requests", "httpx", "subprocess", "multiprocessing", "asyncio", "threading",
        "concurrent", "torch", "transformers", "llama_cpp", "onnxruntime", "huggingface_hub",
    }  # fmt: skip
    files = [*sorted(PACKAGE.glob("*.py")), *(REPO / "tools" / "qualification" / "vl220" / name
             for name in ("eval2.py", "eval2_scoring.py", "review_export.py"))]  # fmt: skip
    for path in files:
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            names = (
                [a.name for a in node.names]
                if isinstance(node, ast.Import)
                else ([node.module] if isinstance(node, ast.ImportFrom) and node.module else [])
            )
            for name in names:
                assert name.split(".")[0] not in forbidden, f"{path.name} imports {name}"
        assert "Popen" not in path.read_text(encoding="utf-8")


def test_the_cli_writes_only_outside_the_repository(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    from tools.qualification.vl242 import __main__ as cli

    def boom(*args: Any, **kwargs: Any) -> Any:
        raise AssertionError("network or process use is not allowed")

    monkeypatch.setattr(socket, "socket", boom)
    monkeypatch.setattr(socket, "create_connection", boom)
    monkeypatch.setattr(subprocess, "Popen", boom)
    export = tmp_path / "export.json"
    export.write_text(json.dumps(sup.standard_export()), encoding="utf-8")
    assert (
        cli.main(["convert", "--export", str(export), "--out", str(REPO / "output" / "vl242-test")])
        == 2
    )
    assert not (REPO / "output" / "vl242-test").exists()
    out = tmp_path / "real"
    assert cli.main(["convert", "--export", str(export), "--out", str(out)]) == 0
    summary = json.loads(capsys.readouterr().out)
    assert summary["image_cases"] == 50
    args = [
        "--cases",
        str(out / "cases.json"),
        "--labels",
        str(out / "labels.json"),
        "--stage",
        "full",
    ]
    assert cli.main(["plan", *args]) == 0
    built = json.loads(capsys.readouterr().out)
    case_doc = json.loads((out / "cases.json").read_text(encoding="utf-8"))
    label_doc = json.loads((out / "labels.json").read_text(encoding="utf-8"))
    case_set = eval2.validate_case_set(case_doc)
    labels = eval2.validate_label_set(label_doc, case_set)
    keys = {
        "plan_sha256": built["plan_sha256"],
        "case_set_sha256": built["case_set"]["case_set_sha256"],
    }
    for tier in ("fast", "deep"):
        evidence = sup.scripted(case_set, labels, sup.truthful(), tier=tier, **keys)
        (tmp_path / f"{tier}.json").write_text(json.dumps(evidence), encoding="utf-8")
    report_args = [
        *args,
        "--fast",
        str(tmp_path / "fast.json"),
        "--deep",
        str(tmp_path / "deep.json"),
    ]
    assert cli.main(["report", *report_args, "--out", str(REPO / "report.md")]) == 2
    assert not (REPO / "report.md").exists()
    assert cli.main(["report", *report_args, "--out", str(tmp_path / "report.md")]) == 0
    assert "## Gate verdicts" in (tmp_path / "report.md").read_text(encoding="utf-8")
    assert (
        cli.main(["report", *report_args, "--stage", "pilot"]) == 2
    )  # a pilot plan has another digest


def test_an_undefined_value_on_the_full_sample_fails_closed(base: dict[str, Any]) -> None:
    result = copy.deepcopy(base)
    result["tiers"]["deep"]["intervals"]["finding_precision"].update(
        point=None, low=None, high=None
    )
    assert _verdict(result, "D3") == "FAIL"
    result["stage"] = "pilot"
    assert _verdict(result, "D3") == "NOT_DECIDED"


def test_an_export_like_todays_review_has_no_clean_reference_and_cannot_pass() -> None:
    """AI-VL-240: Review cannot yet record clean confirmations or subject counts, so a real export has neither."""

    document = sup.export(
        [sup.image(f"d{i}", clean=False, findings=[sup.finding()]) for i in range(30)]
        + [sup.image(f"u{i}", clean=False) for i in range(20)]
    )
    cases, labels_doc, case_set, labels = sup.documents(document)
    built = sup.planned(cases, labels_doc, stage="full")
    keys = {
        "plan_sha256": built["plan_sha256"],
        "case_set_sha256": built["case_set"]["case_set_sha256"],
    }
    fast = eval2.validate_evidence(
        sup.scripted(case_set, labels, sup.truthful(4.0), tier="fast", **keys), case_set
    )
    deep = eval2.validate_evidence(
        sup.scripted(case_set, labels, sup.truthful(30.0), tier="deep", **keys), case_set
    )
    result = analysis.analyze(case_set, labels, fast, deep, built)
    assert result["counts"]["clean"] == 0
    assert result["tiers"]["fast"]["multi_subject"]["evaluated"] is False
    verdicts = {v.gate_id: v.verdict for v in gates.evaluate(result)}
    for gate_id in ("F2", "F4", "D2", "D5"):
        assert verdicts[gate_id] == "INSUFFICIENT_SAMPLE", gate_id
    # Identical tiers: the whole F1-gain interval is below 0.15, a clear failure at any sample size.
    assert (verdicts["D4"], verdicts["T1"]) == ("FAIL", "NOT_APPLICABLE")
    assert "PASS" in verdicts.values()  # F3 and others still read the defective images
    assert "## Gate verdicts" in report.render(result, gates.evaluate(result))
