"""LEARN-OUTCOME-870: one derived outcome in one vocabulary for every cataloged study (pure, table driven)."""

from __future__ import annotations

import json
from typing import Any

import pytest

from src.learning import experiment_outcome as eo
from src.learning.evidence_progress import evidence_progress
from src.learning.intelligence_findings import conclude
from src.learning.intelligence_sources import project_experiment
from src.learning.recommendation_engine import MIN_CONTROLLED_RATINGS, MIN_CONTROLLED_VARIANTS


def image(experiment_id: str, vi: int, i: int) -> str:
    return f"C:/out/{experiment_id}/v{vi}-{i}.png"


def payload(
    study: str,
    values: list[Any],
    per: int = 2,
    *,
    experiment_id: str = "exp",
    status: str = "completed",
    controlled: bool = True,
    seeds: bool = False,
    closure: dict[str, Any] | None = None,
) -> dict[str, Any]:
    snapshot = {"study_type": study, "variable_under_test": "Steps", "prompt_text": "a lighthouse"}
    plan = [
        {
            "experiment_id": experiment_id,
            "variant_id": f"v{vi}",
            "param_value": value,
            "status": status,
            "job_id": f"job-{vi}",
            "planned_images": per,
            "completed_images": per if status == "completed" else 0,
            "image_refs": [image(experiment_id, vi, i) for i in range(per)],
            "execution_metadata": {
                "controlled_evidence_valid": controlled,
                "variable_validation_reason": "valid" if controlled else "backend_restart_boundary",
                **({"actual_all_seeds": [100 + i for i in range(per)]} if seeds else {}),
            },
        }
        for vi, value in enumerate(values)
    ]
    result: dict[str, Any] = {
        "current_experiment": {
            "name": experiment_id,
            "experiment_id": experiment_id,
            "stage": "txt2img",
            "variable_under_test": "Steps",
            "values": list(values),
            "metadata": {},
            "execution_snapshot_json": json.dumps(snapshot),
        },
        "plan": plan,
    }
    if closure is not None:
        result["closure"] = closure
    return result


def rate(data: dict[str, Any], score) -> dict[str, int]:
    """Saved ratings by image for ``score(variant_index, image_index) -> rating | None``."""
    ratings = {}
    for vi, variant in enumerate(data["plan"]):
        for i, ref in enumerate(variant["image_refs"]):
            value = score(vi, i)
            if value is not None:
                ratings[ref] = value
    return ratings


def cell(prompt: str, model: str) -> dict[str, str]:
    return {"cell_id": prompt + model, "prompt_label": prompt, "model_label": model}


MATRIX = [cell("A", "Model 1"), cell("B", "Model 1"), cell("A", "Model 2"), cell("B", "Model 2")]

# study, values, outcome class
LOCAL = [
    ("prompt_slot", ["A", "B", "C"]),
    ("lora_composition", ["A", "B", "C"]),
    ("embedding_experiment", ["A", "B", "C"]),
]
ALL_STUDIES = [
    *LOCAL,
    ("model_comparison", ["model-a", "model-b", "model-c"]),
    ("two_axis_grid", [{"x": 1, "y": 1}, {"x": 1, "y": 2}, {"x": 2, "y": 1}]),
    ("prompt_model_matrix", MATRIX),
    ("compatibility_probe", ["recipe-1", "recipe-2", "recipe-3"]),
]


@pytest.mark.parametrize(("study", "values"), ALL_STUDIES, ids=[s for s, _ in ALL_STUDIES])
def test_unrated_completed_study_is_awaiting_ratings_with_the_exact_minimum(study, values):
    data = payload(study, values)
    outcome = eo.derive_outcome(data, {})
    assert outcome.code == eo.OUTCOME_AWAITING_RATINGS
    assert outcome.ratings_needed == len(values)  # one saved rating per tested value
    assert outcome.unrated == 2 * len(values)
    assert outcome.label == f"Awaiting ratings ({len(values)} more needed)"
    # rating one value's image removes exactly one from the minimum
    partial = eo.derive_outcome(data, rate(data, lambda vi, i: 4 if (vi, i) == (0, 0) else None))
    assert partial.code == eo.OUTCOME_AWAITING_RATINGS
    assert partial.ratings_needed == len(values) - 1


@pytest.mark.parametrize(("study", "values"), ALL_STUDIES, ids=[s for s, _ in ALL_STUDIES])
def test_a_study_with_an_invalid_variant_needs_execution_review(study, values):
    data = payload(study, values)
    data["plan"][1]["execution_metadata"] = {
        "controlled_evidence_valid": False,
        "variable_validation_reason": "backend_restart_boundary",
    }
    outcome = eo.derive_outcome(data, rate(data, lambda vi, i: 4))
    assert outcome.code == eo.OUTCOME_NEEDS_EXECUTION_REVIEW
    assert "backend_restart_boundary" in outcome.detail
    failed = payload(study, values, status="failed", controlled=False)
    assert eo.derive_outcome(failed, {}).code == eo.OUTCOME_NEEDS_EXECUTION_REVIEW
    uncontrolled = payload(study, values, status="uncontrolled")
    assert eo.derive_outcome(uncontrolled, {}).code == eo.OUTCOME_NEEDS_EXECUTION_REVIEW


@pytest.mark.parametrize(("study", "values"), LOCAL, ids=[s for s, _ in LOCAL])
def test_controlled_local_studies_support_a_unique_highest_rated_candidate_and_tie_is_inconclusive(
    study, values
):
    data = payload(study, values)
    supported = eo.derive_outcome(data, rate(data, lambda vi, i: 5 - vi))
    assert supported.code == eo.OUTCOME_SUPPORTED
    assert supported.winner == "A"
    assert "experiment_local" in supported.claim
    tie = eo.derive_outcome(data, rate(data, lambda vi, i: 4))
    assert tie.code == eo.OUTCOME_INCONCLUSIVE
    assert tie.winner is None and tie.next_test


def test_model_comparison_is_supported_under_its_envelope_and_names_no_winner():
    data = payload("model_comparison", ["m-a", "m-b", "m-c"])
    outcome = eo.derive_outcome(data, rate(data, lambda vi, i: 5 - vi))
    assert outcome.code == eo.OUTCOME_SUPPORTED
    assert outcome.winner is None
    assert outcome.claim == "target_envelope_preference"


def test_grid_and_probe_are_descriptive_and_end_inconclusive_with_a_next_test():
    for study, values in (
        ("two_axis_grid", [{"x": 1}, {"x": 2}, {"x": 3}]),
        ("compatibility_probe", ["r1", "r2", "r3"]),
    ):
        data = payload(study, values)
        outcome = eo.derive_outcome(data, rate(data, lambda vi, i: 5 - vi))
        assert outcome.code == eo.OUTCOME_INCONCLUSIVE, study
        assert outcome.winner is None
        assert outcome.next_test and "winner" in outcome.detail
    assert eo.derive_outcome(payload("two_axis_grid", [{"x": 1}, {"x": 2}]), {}).claim == (
        "exploratory_two_variable_observation"
    )


def test_matrix_supports_a_per_model_preference_but_never_a_global_winner_and_all_ties_are_inconclusive():
    data = payload("prompt_model_matrix", MATRIX)
    supported = eo.derive_outcome(data, rate(data, lambda vi, i: 5 if vi % 2 == 0 else 3))
    assert supported.code == eo.OUTCOME_SUPPORTED
    assert supported.winner is None
    assert "no global winner" in supported.detail
    tied = eo.derive_outcome(data, rate(data, lambda vi, i: 4))
    assert tied.code == eo.OUTCOME_INCONCLUSIVE
    assert tied.next_test


def test_a_study_with_fewer_than_two_values_cannot_be_concluded():
    data = payload("prompt_slot", ["only"])
    outcome = eo.derive_outcome(data, {})
    assert outcome.code == eo.OUTCOME_INCONCLUSIVE
    assert outcome.next_test


# ---- ordinary sweeps use the recommendation engine's own thresholds -----------------------------------------------


def test_ordinary_outcome_uses_the_engine_threshold_constants_without_drift():
    values = [20, 30, 40]
    data = payload("controlled_variable", values, per=2)
    none = eo.derive_outcome(data, {})
    assert none.code == eo.OUTCOME_AWAITING_RATINGS
    assert none.ratings_needed == max(MIN_CONTROLLED_RATINGS, MIN_CONTROLLED_VARIANTS)
    # Walk every combination of saved ratings; the outcome must equal the engine's own progress verdict.
    refs = [ref for v in data["plan"] for ref in v["image_refs"]]
    for mask in range(1 << len(refs)):
        ratings = {ref: 4 for bit, ref in enumerate(refs) if mask >> bit & 1}
        per_value = [sum(r in ratings for r in v["image_refs"]) for v in data["plan"]]
        progress = evidence_progress(per_value)
        outcome = eo.derive_outcome(data, ratings)
        if progress.ready:
            assert outcome.code == eo.OUTCOME_SUPPORTED, mask
        else:
            assert outcome.code == eo.OUTCOME_AWAITING_RATINGS, mask
            assert outcome.ratings_needed == max(progress.ratings_needed, progress.values_needed)


def test_ordinary_sweep_that_can_never_reach_the_threshold_is_inconclusive_with_a_next_test():
    data = payload("controlled_variable", [20, 30], per=1)  # two images can never be three ratings
    outcome = eo.derive_outcome(data, rate(data, lambda vi, i: 4))
    assert outcome.code == eo.OUTCOME_INCONCLUSIVE
    assert outcome.next_test
    assert outcome.winner is None  # an ordinary sweep names no winner here; the engine recommends


def test_ordinary_needs_a_second_value_even_with_many_ratings():
    data = payload("controlled_variable", [20, 30], per=3)
    outcome = eo.derive_outcome(data, rate(data, lambda vi, i: 4 if vi == 0 else None))
    assert outcome.code == eo.OUTCOME_AWAITING_RATINGS
    assert outcome.ratings_needed == 1  # one image of the second value


# ---- 2 x 6 pilots equal intelligence_findings.conclude -----------------------------------------------------------


def pilot() -> dict[str, Any]:
    return payload("controlled_variable", [30, 40], per=6, seeds=True)


@pytest.mark.parametrize(
    ("score", "expected_status", "code"),
    [
        (lambda vi, i: 3 + vi, "supported", eo.OUTCOME_SUPPORTED),
        (lambda vi, i: 4, "inconclusive", eo.OUTCOME_INCONCLUSIVE),
        (lambda vi, i: 4 if i < 3 else None, "insufficient", eo.OUTCOME_AWAITING_RATINGS),
    ],
    ids=["supported", "inconclusive", "insufficient"],
)
def test_two_by_six_pilots_equal_the_screening_conclusion(score, expected_status, code):
    data = pilot()
    ratings = rate(data, score)
    view = project_experiment("exp", data)
    expected = conclude(view, {path: float(value) for path, value in ratings.items()})
    assert expected is not None and expected.status == expected_status
    outcome = eo.derive_outcome(data, ratings)
    assert outcome.code == code
    assert outcome.detail == expected.text
    if expected_status == "insufficient":
        assert outcome.ratings_needed == 6  # three pairs, both sides, are still unrated
    if expected_status == "inconclusive":
        assert "different controlled prompt context" in outcome.next_test


# ---- phases before and around ratings -----------------------------------------------------------------------------


def test_unfinished_and_unadmitted_experiments_are_not_concluded():
    assert eo.derive_outcome(payload("prompt_slot", ["A", "B"], status="running"), {}).code == (
        eo.OUTCOME_AWAITING_EXECUTION
    )
    draft = payload("prompt_slot", ["A", "B"])
    for item in draft["plan"]:
        item["job_id"] = ""
    assert eo.derive_outcome(draft, {}).code == eo.OUTCOME_AWAITING_EXECUTION
    attention = payload("prompt_slot", ["A", "B"], status="requires_attention")
    assert eo.derive_outcome(attention, {}).code == eo.OUTCOME_NEEDS_EXECUTION_REVIEW
    assert eo.derive_outcome({}, {}).code == eo.OUTCOME_NEEDS_EXECUTION_REVIEW  # nothing readable


def test_an_unrecognised_or_unreadable_experiment_never_crashes_or_claims_support():
    assert (
        eo.derive_outcome(payload("future_study", ["A", "B"]), {}).code == eo.OUTCOME_INCONCLUSIVE
    )
    broken = payload("prompt_slot", ["A", "B"])
    broken["current_experiment"]["execution_snapshot_json"] = "{not json"
    assert eo.derive_outcome(broken, {}).code == eo.OUTCOME_NEEDS_EXECUTION_REVIEW


def test_derivation_is_pure_and_deterministic():
    data = payload("prompt_slot", ["A", "B", "C"])
    ratings = rate(data, lambda vi, i: 5 - vi)
    before = json.dumps(data, sort_keys=True), dict(ratings)
    first, second = eo.derive_outcome(data, ratings), eo.derive_outcome(data, ratings)
    assert first == second
    assert (json.dumps(data, sort_keys=True), ratings) == before


def test_invalid_ratings_are_not_counted():
    data = payload("prompt_slot", ["A", "B"])
    junk = {
        image("exp", 0, 0): 0,
        image("exp", 0, 1): 9,
        image("exp", 1, 0): "x",
        image("exp", 1, 1): True,
    }
    assert eo.derive_outcome(data, junk).code == eo.OUTCOME_AWAITING_RATINGS


# ---- closure is an operator act; the outcome stays derived --------------------------------------------------------


def closure_for(data, ratings, **kw):
    return eo.build_closure(data, ratings, **kw)


def test_closing_with_unrated_images_reads_as_insufficient_evidence_closed_by_operator():
    data = payload("prompt_slot", ["A", "B", "C"])
    block = closure_for(data, {}, note="enough for now")
    assert block["schema"] == eo.CLOSURE_SCHEMA and block["note"] == "enough for now"
    assert block["outcome_code"] == eo.OUTCOME_INSUFFICIENT_EVIDENCE
    closed = eo.derive_outcome(data, {}, closure=block)
    assert closed.code == eo.OUTCOME_INSUFFICIENT_EVIDENCE
    assert closed.closed and not closed.changed_since_closure
    assert closed.text == "Insufficient evidence, closed by operator"
    assert (
        eo.derive_outcome(data, {}).code == eo.OUTCOME_AWAITING_RATINGS
    )  # never stored as a conclusion


def test_a_later_rating_shows_changed_since_closure_and_the_outcome_is_rederived():
    data = payload("prompt_slot", ["A", "B", "C"])
    block = closure_for(data, {})
    after = rate(data, lambda vi, i: 5 - vi)
    outcome = eo.derive_outcome(data, after, closure=block)
    assert outcome.closed and outcome.changed_since_closure
    assert (
        outcome.code == eo.OUTCOME_SUPPORTED
    )  # re-derived from the ratings, not frozen at closure
    assert outcome.text == "Finding supported - closed by operator - changed since closure"
    assert (
        "changed since closure"
        in eo.derive_outcome(data, {image("exp", 0, 0): 5}, closure=block).text
    )


def test_closing_a_concluded_experiment_keeps_its_outcome_and_the_payload_closure_is_read():
    data = payload("prompt_slot", ["A", "B", "C"])
    ratings = rate(data, lambda vi, i: 5 - vi)
    block = closure_for(data, ratings)
    assert block["outcome_code"] == eo.OUTCOME_SUPPORTED
    data["closure"] = block
    outcome = eo.derive_outcome(data, ratings)
    assert (
        outcome.code == eo.OUTCOME_SUPPORTED
        and outcome.closed
        and not outcome.changed_since_closure
    )
    assert eo.derive_outcome(data, ratings, closure=None).closed is False


def test_malformed_closure_blocks_are_not_closures():
    data = payload("prompt_slot", ["A", "B"])
    for bad in ({}, {"closed_at": ""}, {"closed_at": 5}, {"closed_at": "x"}, "closed", []):
        data["closure"] = bad
        assert eo.derive_outcome(data, {}).closed is False


def test_closing_is_refused_until_generation_has_finished():
    running = payload("prompt_slot", ["A", "B"], status="running")
    assert "not finished" in eo.closure_blocker(running)
    with pytest.raises(eo.ClosureRefused):
        eo.build_closure(running, {})
    draft = payload("prompt_slot", ["A", "B"])
    for item in draft["plan"]:
        item["job_id"] = ""
    assert "Run the experiment" in eo.closure_blocker(draft)
    assert (
        eo.closure_blocker(payload("prompt_slot", ["A", "B"], status="failed", controlled=False))
        == ""
    )
    assert eo.closure_blocker(payload("prompt_slot", ["A", "B"])) == ""


def test_fingerprint_follows_evidence_not_drafts_or_unrelated_images():
    data = payload("prompt_slot", ["A", "B"])
    one = eo.derive_outcome(data, {image("exp", 0, 0): 4}).fingerprint
    assert (
        eo.derive_outcome(data, {image("exp", 0, 0): 4, "C:/elsewhere.png": 5}).fingerprint == one
    )
    assert eo.derive_outcome(data, {image("exp", 0, 0): 5}).fingerprint != one
    assert eo.derive_outcome(data, {image("exp", 0, 0): 4}).fingerprint == one
