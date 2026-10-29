"""AI-LEARN-830: evidence-driven, read-only Learning intelligence (acceptance tests 1-11, 13, 14)."""

from __future__ import annotations

import copy
import json
from dataclasses import replace

import pytest

from src.generation_profiles.evidence_catalog import EvidenceCatalog
from src.learning.ai_evidence_summary import (
    MAX_BYTES,
    UnsafeSummaryError,
    build_ai_summary,
    candidate_index,
    resolve_ai_candidate,
    validate_ai_summary,
)
from src.learning.evidence_intelligence import IntelligenceSources, assess, load_sources
from src.learning.experiment_store import LearningExperimentStore
from src.learning.intelligence_contracts import (
    ACTION_COMPLETE_RATINGS,
    ACTION_INVESTIGATE_EXECUTION,
    ACTION_NO_SAFE_EXPERIMENT,
    ACTION_REPEAT_EXPERIMENT,
    ACTION_RESEARCH_EVIDENCE,
    ACTION_RESOLVE_IDENTITY,
    ACTION_REVIEW_RECOMMENDATION,
    ACTION_RUN_EXPERIMENT,
    ELIGIBILITY_BLOCKED,
    ELIGIBILITY_OPERATOR,
    ELIGIBILITY_READY,
    SOURCE_CONTROLLED,
    SOURCE_PREFERENCE,
    STATUS_EXCLUDED,
    VERDICT_COMPETING,
    VERDICT_INSUFFICIENT,
    VERDICT_NO_CLEAR,
    VERDICT_OBSERVED,
    StaleActionError,
)
from src.learning.intelligence_sources import ExperimentLoad, RatingLog
from tests.learning_v2.intelligence_fixtures_830 import (
    BASELINE,
    NOTE,
    PRIVATE_PATH,
    PROMPT,
    RESOURCES,
    make_context,
    publication_service,
    rating_rows,
    run,
    save_experiment,
    steps_proposal,
    write_log,
)


def kinds(report):
    return [a.kind for a in report.actions.actions]


def test_conflicting_claim_yields_the_expected_eligible_experiment(tmp_path):
    report, _ = run(tmp_path)
    primary = report.actions.primary
    assert primary.kind == ACTION_RUN_EXPERIMENT and primary.executable
    assert primary.workflow == "proposed_experiments"
    assert primary.reason_codes[0] == "conflicting_claim"
    assert primary.workload_map()["images_to_generate"] == 12
    assert primary.workload_map()["seconds"] is None  # elapsed time is unknown, not estimated
    assert primary.confirmation and "explicitly Run" in primary.confirmation
    assert primary.context_fingerprint == report.fingerprint
    assert "No improvement is promised" in primary.note
    steps = next(f for f in report.findings if f.topic == "claim:steps")
    assert steps.status == "conflicting" and steps.source_class == "research_claim"
    assert primary.evidence_refs == (steps.finding_id,)
    # The runnable candidate is the planner's own proposal, never an invented one.
    assert primary.target_id == steps_proposal(make_context())["proposal_id"]


def test_unresolved_identity_gives_research_action_not_a_runnable_experiment(tmp_path):
    report, _ = run(tmp_path, context=make_context(sha=None))
    primary = report.actions.primary
    assert primary.kind == ACTION_RESOLVE_IDENTITY and primary.eligibility == ELIGIBILITY_OPERATOR
    assert not report.identity_verified
    assert ACTION_RUN_EXPERIMENT not in kinds(report) and ACTION_REPEAT_EXPERIMENT not in kinds(
        report
    )
    assert not any(a.executable for a in report.actions.actions)
    identity = next(f for f in report.findings if f.topic == "identity")
    assert identity.status == "unknown"


def test_completed_unrated_experiment_suggests_finishing_ratings_first(tmp_path):
    context = make_context()
    store = LearningExperimentStore(tmp_path / "experiments")
    save_experiment(store, "exp-unrated", proposal=steps_proposal(context))
    report, _ = run(tmp_path, context=context)
    primary = report.actions.primary
    assert primary.kind == ACTION_COMPLETE_RATINGS and primary.target_id == "exp-unrated"
    assert primary.workload_map() == {"images_to_generate": 0, "images_to_rate": 12}
    assert primary.workflow == "learning_review"
    # Completing existing work beats, and replaces, redundant generation of the same question.
    assert ACTION_RUN_EXPERIMENT not in kinds(report) or all(
        a.target_id != steps_proposal(context)["proposal_id"] for a in report.actions.actions
    )
    assert (
        "steps",
        "Not proposed again: an equivalent run is awaiting ratings.",
    ) in report.actions.suppressed


def rated_experiment(tmp_path, *, rating=None, prompt=None, experiment="exp-rated", proposal=True):
    context = make_context()
    store = LearningExperimentStore(tmp_path / "experiments")
    extra = {} if prompt is None else {"prompt": prompt}
    save_experiment(
        store, experiment, proposal=steps_proposal(context) if proposal else None, **extra
    )
    return context, rating_rows(experiment, rating=rating, **extra)


def test_controlled_rated_experiment_reports_supported_conclusion_and_limits(tmp_path):
    context, rows = rated_experiment(tmp_path)
    report, _ = run(tmp_path, context=context, rows=rows)
    [conclusion] = report.conclusions
    assert (
        conclusion.status == "supported" and "Follow-up investigation supported" in conclusion.text
    )
    assert "not statistical proof" in conclusion.limitation
    finding = next(f for f in report.findings if f.topic == "experiment:exp-rated")
    assert finding.source_class == SOURCE_CONTROLLED
    assert finding.freshness.startswith("records:") and finding.applicability.startswith("mdl-")
    assert "universal optimum" in finding.limitation


def test_inconclusive_equivalent_result_is_repeated_only_under_a_new_context(tmp_path):
    context, rows = rated_experiment(
        tmp_path, rating=lambda value, i: 4 if (value == 40 and i < 3) else 3
    )
    report, _ = run(tmp_path, context=context, rows=rows)
    [conclusion] = report.conclusions
    assert conclusion.status == "inconclusive"
    repeat = next(a for a in report.actions.actions if a.kind == ACTION_REPEAT_EXPERIMENT)
    assert repeat.executable and "different controlled prompt context" in " ".join(repeat.reasons)
    assert repeat.target_id == steps_proposal(context)["proposal_id"]


def test_completed_equivalent_experiment_is_not_proposed_again(tmp_path):
    context, rows = rated_experiment(tmp_path)
    report, _ = run(tmp_path, context=context, rows=rows)
    proposal_id = steps_proposal(context)["proposal_id"]
    assert all(a.target_id != proposal_id for a in report.actions.actions)
    assert any(
        var == "steps" and "complete (supported)" in why for var, why in report.actions.suppressed
    )
    assert report.actions.primary.kind != ACTION_RUN_EXPERIMENT


def test_equivalent_experiment_found_by_design_not_only_by_id(tmp_path):
    context = make_context()
    proposal = copy.deepcopy(steps_proposal(context))
    proposal["proposal_id"] = "evidence800-from-an-older-catalog-revision"
    store = LearningExperimentStore(tmp_path / "experiments")
    save_experiment(store, "exp-old-id", proposal=proposal)
    rows = rating_rows("exp-old-id")
    report, _ = run(tmp_path, context=context, rows=rows)
    assert any("complete (supported)" in why for _, why in report.actions.suppressed)


@pytest.mark.parametrize(
    "controlled,reason",
    [(False, "backend_restart_boundary"), (None, ""), (True, "tested_setting_readback_unverified")],
)
def test_uncontrolled_experiment_is_neither_technical_nor_preference_evidence(
    tmp_path, controlled, reason
):
    context = make_context()
    store = LearningExperimentStore(tmp_path / "experiments")
    save_experiment(
        store, "exp-bad", proposal=steps_proposal(context), controlled=controlled, reason=reason
    )
    rows = rating_rows("exp-bad", controlled=False)
    report, _ = run(tmp_path, context=context, rows=rows)
    assert report.conclusions == () and report.preference.groups == ()
    assert dict(report.preference.excluded) == {"uncontrolled": 12}
    primary = report.actions.primary
    assert primary.kind == ACTION_INVESTIGATE_EXECUTION and primary.target_id == "exp-bad"
    excluded = next(f for f in report.findings if f.topic == "experiment:exp-bad")
    assert excluded.status == STATUS_EXCLUDED
    assert ACTION_COMPLETE_RATINGS not in kinds(
        report
    )  # unrated work on invalid evidence is pointless
    assert any("invalid execution evidence" in why for _, why in report.actions.suppressed)


def test_failed_execution_is_investigated_not_rated(tmp_path):
    context = make_context()
    store = LearningExperimentStore(tmp_path / "experiments")
    save_experiment(
        store, "exp-failed", proposal=steps_proposal(context), status="failed", controlled=None
    )
    report, _ = run(tmp_path, context=context)
    assert report.actions.primary.kind == ACTION_INVESTIGATE_EXECUTION


def test_underrepresented_category_is_insufficient_not_a_learned_preference(tmp_path):
    people = rating_rows("exp-people", per_value=2, flags={"people": True})
    general = rating_rows("exp-general", per_value=6)
    context = make_context()
    store = LearningExperimentStore(tmp_path / "experiments")
    save_experiment(store, "exp-people", per_value=2)
    save_experiment(store, "exp-general")
    report, _ = run(tmp_path, context=context, rows=people + general)
    by_category = {g.category: g for g in report.preference.groups}
    assert by_category["people"].verdict == VERDICT_INSUFFICIENT
    assert "Insufficient evidence" in by_category["people"].statement
    assert "no preference is inferred" in by_category["people"].statement
    assert by_category["general"].verdict == VERDICT_OBSERVED
    assert by_category["general"].leading_value == 40
    assert "learned" not in " ".join(g.statement for g in report.preference.groups).lower()
    finding = next(
        f
        for f in report.findings
        if f.source_class == SOURCE_PREFERENCE and "people" in f.applicability
    )
    assert finding.status == "insufficient"


def test_incompatible_models_and_unmatched_prompts_are_never_pooled(tmp_path):
    context = make_context()
    ours_a = rating_rows("exp-a", per_value=2, prompt="prompt context A")
    ours_b = rating_rows("exp-b", per_value=2, prompt="prompt context B")
    theirs = rating_rows("exp-other", per_value=6, model_sha="b" * 64)
    report, _ = run(tmp_path, context=context, rows=ours_a + ours_b + theirs)
    groups = report.preference.groups
    assert len(groups) == 2 and len({g.prompt_context for g in groups}) == 2
    assert all(g.verdict == VERDICT_INSUFFICIENT and g.ratings == 4 for g in groups)
    assert dict(report.preference.excluded) == {"other_model": 12}
    # Four ratings per value would pass if the two prompts were pooled; they must not be.
    assert all(g.verdict != VERDICT_OBSERVED for g in groups)


def test_unpaired_and_unattributed_ratings_stay_out(tmp_path):
    lonely = rating_rows("exp-lonely", values=(30,), per_value=6)
    blank_prompt = rating_rows("exp-blank", prompt="")
    report, _ = run(tmp_path, rows=lonely + blank_prompt)
    assert report.preference.groups == ()
    assert dict(report.preference.excluded) == {"unattributed_prompt": 12, "unpaired": 6}


def test_competing_experiments_are_reported_as_competing(tmp_path):
    first = rating_rows("exp-first", rating=lambda v, i: 5 if v == 40 else 2)
    second = rating_rows("exp-second", rating=lambda v, i: 5 if v == 30 else 2)
    report, _ = run(tmp_path, rows=first + second)
    [group] = report.preference.groups
    assert group.verdict == VERDICT_COMPETING and group.leading_value is None
    assert group.experiments == 2 and group.ratings == 24


def test_small_difference_is_no_clear_preference(tmp_path):
    rows = rating_rows("exp-flat", rating=lambda v, i: 4 if (v == 40 and i == 0) else 3)
    report, _ = run(tmp_path, rows=rows)
    [group] = report.preference.groups
    assert group.verdict == VERDICT_NO_CLEAR and group.margin < 0.5


def test_subscores_are_summarised_separately_from_overall(tmp_path):
    rows = rating_rows("exp-sub")
    for row in rows:
        row["metadata"]["rating_details"] = {
            "composition": 5 if row["metadata"]["variant_value"] == 40 else 2
        }
    report, _ = run(tmp_path, rows=rows)
    [group] = report.preference.groups
    best = next(v for v in group.values if v.value == 40)
    assert dict(best.subscore_means) == {"composition": 5.0} and best.mean == 4.0


def test_recommendation_review_is_offered_when_publication_rule_passes(tmp_path):
    context = make_context()
    rows = rating_rows("exp-pub")
    save_experiment(
        LearningExperimentStore(tmp_path / "experiments"),
        "exp-pub",
        proposal=steps_proposal(context),
    )
    report, _ = run(tmp_path, context=context, rows=rows, publication=True)
    review = next(a for a in report.actions.actions if a.kind == ACTION_REVIEW_RECOMMENDATION)
    assert review.workflow == "recommendation_apply" and review.executable
    assert "starting point, not an optimum" in " ".join(review.reasons)
    assert report.actions.primary.kind == ACTION_REVIEW_RECOMMENDATION  # nothing else ready to do


def test_no_safe_experiment_when_nothing_is_eligible(tmp_path):
    report, _ = run(tmp_path, context=make_context(EvidenceCatalog()))
    kinds_seen = kinds(report)
    assert ACTION_RUN_EXPERIMENT not in kinds_seen
    assert ACTION_RESEARCH_EVIDENCE in kinds_seen
    last = report.actions.actions[-1]
    assert last.kind == ACTION_NO_SAFE_EXPERIMENT and last.eligibility == ELIGIBILITY_BLOCKED
    assert not last.executable and last.confirmation == ""


@pytest.mark.parametrize(
    "change", ["catalog", "resources", "baseline", "identity", "ratings", "experiments"]
)
def test_changed_evidence_invalidates_dependent_action_identifiers(tmp_path, change):
    context = make_context()
    store = LearningExperimentStore(tmp_path / "experiments")
    before, sources = run(tmp_path, context=context)
    old = before.actions.primary
    assert before.actions.revalidate(old.action_id) is old
    if change == "catalog":
        new_sources = replace(sources, context=replace(context, catalog=EvidenceCatalog()))
    elif change == "resources":
        resources = {**RESOURCES, "samplers": ["Euler"]}
        new_sources = replace(sources, context=replace(context, resources=resources))
    elif change == "baseline":
        baseline = copy.deepcopy(BASELINE)
        baseline["txt2img"]["cfg_scale"] = 6.0
        new_sources = replace(sources, context=replace(context, baseline=baseline))
    elif change == "identity":
        new_sources = replace(sources, context=make_context(sha="c" * 64))
    elif change == "ratings":
        write_log(tmp_path / "learning_records.jsonl", rating_rows("exp-late"))
        new_sources = load_sources(
            context, records_path=tmp_path / "learning_records.jsonl", store=store
        )
    else:
        save_experiment(
            store,
            "exp-new",
            proposal=steps_proposal(context),
            per_value=2,
            status="pending",
            frozen=False,
        )
        new_sources = load_sources(
            context, records_path=tmp_path / "learning_records.jsonl", store=store
        )
    after = assess(new_sources)
    assert after.fingerprint != before.fingerprint
    with pytest.raises(StaleActionError, match="out of date"):
        after.actions.revalidate(old.action_id)


def test_identical_evidence_gives_identical_ranking_and_summaries(tmp_path):
    context = make_context()
    store = LearningExperimentStore(tmp_path / "experiments")
    save_experiment(store, "exp-1", proposal=steps_proposal(context), controlled=False, reason="x")
    save_experiment(store, "exp-2", values=(30, 40), per_value=6)
    rows = rating_rows("exp-2")
    first, _ = run(tmp_path, context=context, rows=rows, publication=True)
    second, _ = run(tmp_path, context=context, rows=rows, publication=True)
    assert [a.to_dict() for a in first.actions.actions] == [
        a.to_dict() for a in second.actions.actions
    ]
    assert first.fingerprint == second.fingerprint
    assert json.dumps(build_ai_summary(first)) == json.dumps(build_ai_summary(second))
    assert [f.finding_id for f in first.findings] == [f.finding_id for f in second.findings]


def test_priority_rule_orders_ratings_before_investigation_before_new_generation(tmp_path):
    context = make_context()
    store = LearningExperimentStore(tmp_path / "experiments")
    save_experiment(store, "exp-a-unrated", per_value=3)
    save_experiment(store, "exp-b-failed", status="failed", controlled=None)
    report, _ = run(tmp_path, context=context)
    order = kinds(report)
    assert order.index(ACTION_COMPLETE_RATINGS) < order.index(ACTION_INVESTIGATE_EXECUTION)
    assert order.index(ACTION_INVESTIGATE_EXECUTION) < order.index(ACTION_RUN_EXPERIMENT)
    assert order.index(ACTION_RUN_EXPERIMENT) < order.index(ACTION_RESEARCH_EVIDENCE)
    ranks = [(a.eligibility, a.kind) for a in report.actions.actions]
    ready = [i for i, (e, _) in enumerate(ranks) if e == ELIGIBILITY_READY]
    operator = [i for i, (e, _) in enumerate(ranks) if e == ELIGIBILITY_OPERATOR]
    assert max(ready) < min(operator)
    assert len(report.actions.alternatives) == 3


def test_over_budget_experiment_is_blocked_not_executable(tmp_path):
    from src.learning import next_actions

    original = next_actions.MAX_IMAGE_COST
    next_actions.MAX_IMAGE_COST = 4
    try:
        report, _ = run(tmp_path)
    finally:
        next_actions.MAX_IMAGE_COST = original
    run_action = next(a for a in report.actions.actions if a.kind == ACTION_RUN_EXPERIMENT)
    assert (
        run_action.eligibility == ELIGIBILITY_BLOCKED and "bounded cost" in run_action.blockers[0]
    )


def test_ai_summary_is_bounded_opaque_and_leaks_nothing(tmp_path):
    context = make_context()
    store = LearningExperimentStore(tmp_path / "experiments")
    save_experiment(store, "exp-priv", proposal=steps_proposal(context))
    rows = rating_rows("exp-priv", flags={"people": True})
    report, _ = run(tmp_path, context=context, rows=rows, publication=True)
    summary = build_ai_summary(report)
    text = json.dumps(summary)
    for secret in (
        PROMPT,
        "PRIVATE-PROMPT-CANARY",
        NOTE,
        PRIVATE_PATH,
        "C:/",
        "\\",
        ".png",
        "test.safetensors",
        "exp-priv",
    ):
        assert secret not in text, secret
    assert len(text) <= MAX_BYTES and summary["schema"] == "stablenew.learning-evidence-summary.v1"
    assert summary["model"]["ref"].startswith("mdl-")
    assert all(c["id"].startswith("cand-") for c in summary["candidates"])
    assert "no_confidence_probabilities" in summary["limits"]
    validate_ai_summary(summary)


@pytest.mark.parametrize(
    "bad",
    [
        PROMPT,
        "C:\\Users\\rob\\out.png",
        "/home/rob/out.png",
        "a prompt with spaces",
        float("nan"),
        object(),
        "x" * 80,
    ],
)
def test_ai_summary_validator_rejects_anything_but_opaque_tokens(bad):
    with pytest.raises(UnsafeSummaryError):
        validate_ai_summary({"candidates": [{"note": bad}]})


def test_ai_answer_must_be_an_issued_current_executable_candidate(tmp_path):
    report, sources = run(tmp_path)
    issued = candidate_index(report.actions)
    primary_candidate = next(iter(issued))
    assert resolve_ai_candidate(primary_candidate, issued, report.actions) is report.actions.primary
    with pytest.raises(StaleActionError, match="not offered"):
        resolve_ai_candidate("cand-0000000000000000", issued, report.actions)
    changed = replace(sources, context=replace(sources.context, catalog=EvidenceCatalog()))
    with pytest.raises(StaleActionError):
        resolve_ai_candidate(primary_candidate, issued, assess(changed).actions)
    blocked = next(
        c for c, a in zip(issued, report.actions.actions, strict=True) if not a.executable
    )
    with pytest.raises(StaleActionError, match="not currently eligible"):
        resolve_ai_candidate(blocked, issued, report.actions)


def test_ai_summary_drops_lowest_ranked_candidates_to_fit_and_fails_closed(tmp_path, monkeypatch):
    report, _ = run(tmp_path)
    full = build_ai_summary(report)
    size = len(json.dumps(full, separators=(",", ":")))
    monkeypatch.setattr("src.learning.ai_evidence_summary.MAX_BYTES", size - 40)
    trimmed = build_ai_summary(report)
    assert trimmed["truncated"] and not full["truncated"]
    assert len(trimmed["candidates"]) < len(full["candidates"])
    assert trimmed["candidates"] == full["candidates"][: len(trimmed["candidates"])]  # best stay
    monkeypatch.setattr("src.learning.ai_evidence_summary.MAX_BYTES", 200)
    with pytest.raises(UnsafeSummaryError, match="size bound"):
        build_ai_summary(report)


def test_corrupt_evidence_degrades_visibly_without_failing(tmp_path):
    store = LearningExperimentStore(tmp_path / "experiments")
    save_experiment(store, "exp-ok", per_value=2)
    (tmp_path / "experiments" / "exp-broken").mkdir()
    (tmp_path / "experiments" / "exp-broken" / "session.json").write_text("{not json")
    store.save_session(
        display_name="x", experiment_id="exp-nosnap", payload={"current_experiment": []}
    )
    report, _ = run(
        tmp_path,
        rows=rating_rows("exp-ok", per_value=2),
        log_extra='{broken\n[1,2]\n{"metadata": {"record_kind": "learning_experiment_rating"}}\n',
    )
    joined = " ".join(report.problems)
    assert "damaged rating log line" in joined and "lack a durable image identity" in joined
    assert "unreadable" in joined
    assert report.actions.problems == report.problems and report.actions.primary is not None
    assert build_ai_summary(report)["degraded"] is True


def test_empty_and_missing_inputs_are_safe(tmp_path):
    report, _ = run(tmp_path)
    assert report.problems == () and report.preference.groups == ()
    bare = assess(IntelligenceSources(make_context(), RatingLog(), ExperimentLoad()))
    assert bare.actions.primary is not None


def test_planning_failure_is_reported_not_raised(tmp_path, monkeypatch):
    def boom(self, _context):
        raise ValueError("Absolute resource paths cannot enter a proposal plan")

    monkeypatch.setattr("src.learning.evidence_intelligence.EvidenceProposalPlanner.plan", boom)
    report, _ = run(tmp_path)
    assert any("planning is unavailable" in p for p in report.problems)
    assert report.actions.primary.kind == ACTION_NO_SAFE_EXPERIMENT


def test_assessment_is_read_only(tmp_path):
    context = make_context()
    save_experiment(
        LearningExperimentStore(tmp_path / "experiments"),
        "exp-ro",
        proposal=steps_proposal(context),
    )
    rows = rating_rows("exp-ro")
    run(tmp_path, context=context, rows=rows, publication=True)

    def snapshot():
        return {p: p.read_bytes() for p in sorted(tmp_path.rglob("*")) if p.is_file()}

    before = snapshot()
    run(tmp_path, context=context, rows=rows, publication=True)
    assert snapshot() == before
    assert not (tmp_path / "profiles").exists()
    assert publication_service(tmp_path).store.root == tmp_path / "profiles"
