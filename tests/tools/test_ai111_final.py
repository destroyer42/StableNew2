"""Final corpus and decisive judgment contract, pure and offline."""

import copy
from dataclasses import replace

import pytest

from tests.tools.test_ai111_qualification import _good_summary
from tools.qualification.ai111.corpus import corpus_digest
from tools.qualification.ai111.final_plan import (
    MINIMUMS,
    coverage,
    final_corpus,
    final_plan,
    validate_oracles,
)
from tools.qualification.ai111.plan import digest, frozen_plan
from tools.qualification.ai111.scoring import evaluate_gates


def test_historical_screening_digest_unchanged():
    assert (
        digest(frozen_plan()) == "17814e4050049323dc4f5206417bac67f94307d7791ce580af2948e2310df338"
    )


def test_final_corpus_is_deterministic_versioned_and_meets_every_minimum():
    cases = final_corpus()
    plan = final_plan()
    assert corpus_digest(cases) == corpus_digest(final_corpus()) == plan["corpus_sha256"]
    assert len(cases) == 460
    for key, count in coverage(cases).items():
        assert count >= MINIMUMS[key]
    assert all(value == "NOT TESTED" for value in plan["model_status"].values())
    changed = copy.deepcopy(plan)
    changed["counts"]["target_advice"] += 1
    assert digest(plan) != digest(changed)


def test_oracles_are_checked_against_policy_and_approved_catalog():
    cases = final_corpus()
    validate_oracles(cases)
    target = next(c for c in cases if c.kind == "target_fit_advice")
    workflow = next(c for c in cases if c.kind == "workflow_choice")
    with pytest.raises(ValueError):
        validate_oracles([replace(target, allowed_targets=("unapproved",), oracle="unapproved")])
    with pytest.raises(ValueError):
        validate_oracles(
            [replace(workflow, allowed_workflows=("video_workflow",), oracle="video_workflow")]
        )
    with pytest.raises(ValueError):
        coverage([target, target])


def test_100_total_ratings_with_ties_cannot_satisfy_decisive_minimum():
    result = evaluate_gates(
        _good_summary(),
        frozen_plan()["thresholds"],
        teardown_verified=True,
        preference={"judged_pairs": 120, "decided": 90, "win_rate_lower95": 0.9},
    )
    assert result["verdict"] == "INCONCLUSIVE"
    assert "preference_judged_pairs" in result["unmet"]


def test_real_physical_runtime_is_refused_before_import_or_execution(tmp_path):
    from tools.qualification.ai111.physical import SessionPaths, run_session

    result = run_session(
        plan={},
        paths=SessionPaths(tmp_path, tmp_path / "absent.zip", {}),
        stage="A",
        arms=[],
        cases=[],
        authorization_text="not binary authorization",
    )
    assert result["verdict"] == "NOT TESTED"
    assert all(line.startswith("monitoring not ready:") for line in result["refused"])
    assert any("lifetime_complete" in line for line in result["refused"])
    assert not list(tmp_path.iterdir())


def test_screening_or_empty_records_cannot_receive_final_go():
    from tools.qualification.ai111.corpus import build_corpus
    from tools.qualification.ai111.final_plan import evaluate_final_gates

    cases = final_corpus()
    assert evaluate_final_gates(cases, [], teardown_verified=True)["verdict"] == "NOT TESTED"
    screening = build_corpus(111, frozen_plan()["corpus"]["counts"])
    result = evaluate_final_gates(
        screening,
        [{"case_id": screening[0].case_id, "outcome": "suggestion"}],
        teardown_verified=True,
    )
    assert result["verdict"] == "INCONCLUSIVE"
    assert "frozen_final_corpus" in result["unmet"]


def test_partial_final_corpus_cannot_receive_go_despite_good_preference():
    from tools.qualification.ai111.final_plan import evaluate_final_gates

    cases = final_corpus()
    row = {
        "case_id": cases[0].case_id,
        "outcome": "suggestion",
        "elapsed_ms": 1,
        "positive": cases[0].positive,
        "negative": cases[0].negative,
        "details": {"child_observed": True, "priority_verified": True},
    }
    result = evaluate_final_gates(
        cases,
        [row],
        teardown_verified=True,
        preference={"judged_pairs": 100, "decided": 100, "win_rate_lower95": 0.9},
    )
    assert result["verdict"] != "GO"
    assert {"prompt_rewrite", "target_workflow", "adversarial", "allowed_sensitive"} <= set(
        result["unmet"]
    )
