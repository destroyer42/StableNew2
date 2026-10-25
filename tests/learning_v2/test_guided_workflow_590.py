"""PR-LEARN-UX-590: the toolkit-neutral guide, Preview summary, estimate and recommendation reading.

Everything here derives from existing experiment, plan and rating state; no test queues, runs or publishes anything
beyond a fake JobService that records its calls.
"""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from src.gui.learning_state import LearningExperiment, LearningVariant
from src.learning.design_estimate import count_range_values, estimate_design
from src.learning.guided_workflow import (
    ACTION_BUILD_PREVIEW,
    ACTION_NONE,
    ACTION_RATE,
    ACTION_RECOMMENDATIONS,
    ACTION_REVIEW_RESULTS,
    ACTION_RUN,
    ACTION_SAVE_NEXT,
    ACTION_VIEW_PROGRESS,
    STATUS_ATTENTION,
    STATUS_AVAILABLE,
    STATUS_COMPLETED,
    STATUS_LOCKED,
    STATUS_WAITING,
    STEP_COMPARE,
    STEP_DESIGN,
    STEP_ORDER,
    STEP_PREVIEW,
    STEP_RATE,
    STEP_RUN,
    RatingProgress,
    build_rating_progress,
    build_workflow_facts,
    project_guided_workflow,
)
from src.learning.preview_summary import build_preview_summary
from src.learning.recommendation_engine import (
    EVIDENCE_TIER_EXPERIMENT_STRONG,
    EVIDENCE_TIER_NO_EVIDENCE,
    EVIDENCE_TIER_REVIEW_ONLY,
    EVIDENCE_TIER_SPARSE_PLUS_REVIEW,
    ParameterRecommendation,
    RecommendationSet,
)
from src.learning.recommendation_summary import apply_availability, build_recommendation_summary
from src.learning.review_workspace import build_review_projection
from tests.learning_v2.test_learning_recovery_260 import RepositoryService
from tests.learning_v2.test_model_comparison_140 import baseline, controller_for


def variant(status="pending", *, job_id="", refs=(), planned=2, value=6.0, **metadata):
    return LearningVariant(
        experiment_id="e1",
        variant_id=f"e1:{value}",
        param_value=value,
        status=status,
        planned_images=planned,
        completed_images=len(refs),
        image_refs=list(refs),
        job_id=job_id,
        execution_metadata=dict(metadata),
    )


def experiment(snapshot="{}"):
    return SimpleNamespace(name="CFG sweep", execution_snapshot_json=snapshot, metadata={})


def facts_for(plan, *, rating=None, exp=True, **kwargs):
    rating = rating or RatingProgress()
    return build_workflow_facts(experiment() if exp else None, plan, rating=rating, **kwargs)


def statuses(projection):
    return {view.step: view.status for view in projection.steps}


# --------------------------------------------------------------------------------------------- the five steps


def test_a_new_draft_starts_at_design_with_one_obvious_action():
    projection = project_guided_workflow(facts_for([], exp=False))

    assert [view.step for view in projection.steps] == list(STEP_ORDER)
    assert projection.recommended_step == projection.viewed_step == STEP_DESIGN
    assert projection.primary.action == ACTION_BUILD_PREVIEW and projection.primary.enabled
    assert statuses(projection) == {
        STEP_DESIGN: STATUS_AVAILABLE,
        STEP_PREVIEW: STATUS_LOCKED,
        STEP_RUN: STATUS_LOCKED,
        STEP_COMPARE: STATUS_LOCKED,
        STEP_RATE: STATUS_LOCKED,
    }
    assert projection.status_label == "Draft - not previewed"


def test_a_preview_is_ready_to_run_but_nothing_is_queued_or_completed_by_reaching_it():
    facts = facts_for([variant(), variant(value=7.0)])
    projection = project_guided_workflow(facts)

    assert projection.recommended_step == STEP_PREVIEW
    assert projection.primary.action == ACTION_RUN and projection.primary.enabled
    assert projection.status_label == "Preview ready - not queued"
    result = statuses(projection)
    assert result[STEP_DESIGN] == STATUS_COMPLETED
    assert result[STEP_PREVIEW] == STATUS_AVAILABLE and result[STEP_RUN] == STATUS_AVAILABLE
    # Viewing any step changes the page, never the facts: nothing becomes complete by being opened.
    for step in STEP_ORDER:
        assert statuses(project_guided_workflow(facts, step)) == result


def test_an_edit_after_preview_makes_it_stale_and_not_runnable_until_rebuilt():
    projection = project_guided_workflow(facts_for([variant()], preview_stale=True), STEP_PREVIEW)

    assert projection.status_label == "Preview out of date"
    assert projection.recommended_step == STEP_DESIGN
    assert statuses(projection)[STEP_PREVIEW] == STATUS_ATTENTION
    assert statuses(projection)[STEP_RUN] == STATUS_LOCKED
    assert projection.primary.action == ACTION_RUN and not projection.primary.enabled
    assert "build the Preview again" in projection.primary.reason


def test_a_stale_design_does_not_unadmit_jobs_that_already_exist():
    plan = [variant("queued", job_id="j1"), variant("queued", job_id="j2", value=7.0)]
    projection = project_guided_workflow(facts_for(plan, preview_stale=True))

    assert projection.status_label == "Queued"
    assert statuses(projection)[STEP_RUN] == STATUS_WAITING
    assert statuses(projection)[STEP_PREVIEW] == STATUS_COMPLETED


@pytest.mark.parametrize(
    "plan,label,run_status",
    [
        ([variant("queued", job_id="j1")], "Queued", STATUS_WAITING),
        ([variant("running", job_id="j1")], "Running", STATUS_WAITING),
        ([variant("failed", job_id="j1")], "Failed", STATUS_ATTENTION),
        ([variant("requires_attention", job_id="j1")], "Requires attention", STATUS_ATTENTION),
    ],
)
def test_existing_execution_states_are_mapped_honestly(plan, label, run_status):
    projection = project_guided_workflow(facts_for(plan))

    assert projection.status_label == label
    assert statuses(projection)[STEP_RUN] == run_status


def test_an_admission_that_needs_attention_says_so_and_is_never_retried_by_the_guide():
    plan = [variant("queued", job_id="j1", admission_error="response lost"), variant(value=7.0)]
    projection = project_guided_workflow(facts_for(plan), STEP_RUN)

    assert projection.status_label == "Requires attention"
    assert statuses(projection)[STEP_RUN] == STATUS_ATTENTION
    assert any("Nothing is retried automatically" in note for note in projection.notices)
    assert projection.primary.action != ACTION_RUN


def test_results_arriving_enable_review_without_forcing_a_step_change():
    plan = [
        variant("completed", job_id="j1", refs=["a.png"]),
        variant("running", job_id="j2", value=7.0),
    ]
    rating = RatingProgress(unrated=1, awaiting=2)
    projection = project_guided_workflow(facts_for(plan, rating=rating), STEP_RUN)

    assert projection.viewed_step == STEP_RUN
    assert projection.primary.action == ACTION_REVIEW_RESULTS and projection.primary.enabled
    assert statuses(projection)[STEP_COMPARE] == STATUS_AVAILABLE


def test_compare_is_optional_and_its_primary_action_rates():
    plan = [variant("completed", job_id="j1", refs=["a.png", "b.png"])]
    projection = project_guided_workflow(
        facts_for(plan, rating=RatingProgress(unrated=2)), STEP_COMPARE
    )

    assert projection.primary.action == ACTION_RATE and projection.primary.enabled
    assert statuses(projection)[STEP_COMPARE] == STATUS_AVAILABLE  # optional, not required to rate
    assert statuses(projection)[STEP_RATE] == STATUS_AVAILABLE


def test_rate_offers_save_and_next_until_done_then_recommendations():
    plan = [variant("completed", job_id="j1", refs=["a.png", "b.png"])]
    rating = RatingProgress(saved=1, unrated=1)
    todo = project_guided_workflow(
        facts_for(plan, rating=rating, evidence_message="Need 2 more ratings."), STEP_RATE
    )
    assert todo.primary.action == ACTION_SAVE_NEXT
    assert "Need 2 more ratings." in todo.headline

    done_rating = RatingProgress(saved=2)
    done = project_guided_workflow(facts_for(plan, rating=done_rating), STEP_RATE)
    assert statuses(done)[STEP_RATE] == STATUS_COMPLETED
    assert done.primary.action == ACTION_RECOMMENDATIONS


@pytest.mark.parametrize("study", ["model_comparison", "two_axis_grid"])
def test_descriptive_studies_never_offer_recommendations(study):
    plan = [variant("completed", job_id="j1", refs=["a.png"])]
    projection = project_guided_workflow(
        facts_for(plan, rating=RatingProgress(saved=1), study_type=study), STEP_RATE
    )

    assert projection.primary.action == ACTION_NONE and not projection.primary.enabled
    assert "never become recommendations" in projection.headline


def test_uncontrolled_and_missing_results_are_never_reported_as_plain_complete():
    plan = [variant("completed", job_id="j1", refs=["a.png"])]
    rating = RatingProgress(saved=1, uncontrolled=1, missing=1)
    projection = project_guided_workflow(facts_for(plan, rating=rating))

    assert projection.status_label != "Complete"
    assert "Uncontrolled evidence" in projection.flags and "Missing artifact" in projection.flags
    assert statuses(projection)[STEP_RATE] == STATUS_ATTENTION


def test_view_progress_after_admission_from_preview():
    plan = [variant("queued", job_id="j1")]
    projection = project_guided_workflow(facts_for(plan), STEP_PREVIEW)

    assert projection.primary.action == ACTION_VIEW_PROGRESS


# ------------------------------------------------------------------------------------------- rating progress


def test_rating_progress_keeps_saved_drafts_unrated_missing_and_pending_apart():
    plan = [
        variant("completed", job_id="j1", refs=["saved.png", "draft.png", "new.png", "gone.png"]),
        variant("uncontrolled", job_id="j2", refs=["u.png"], value=7.0),
        variant("running", job_id="j3", value=8.0),
    ]
    progress = build_rating_progress(
        plan,
        is_saved=lambda ref: ref == "saved.png",
        has_draft=lambda ref: ref == "draft.png",
        exists=lambda ref: ref != "gone.png",
    )

    assert progress == RatingProgress(
        saved=1, drafts=1, unrated=1, missing=1, awaiting=2, uncontrolled=1
    )
    assert progress.reviewable == 3 and progress.to_rate == 2
    assert not progress.review_complete  # an unsaved draft is not evidence
    assert "1 unavailable" in progress.describe() and "2 still generating" in progress.describe()


def test_a_saved_rating_stays_saved_even_if_its_file_has_gone_missing():
    plan = [variant("completed", job_id="j1", refs=["a.png"])]
    progress = build_rating_progress(
        plan, is_saved=lambda _r: True, has_draft=lambda _r: False, exists=lambda _r: False
    )

    assert (progress.saved, progress.missing) == (1, 0)


# ------------------------------------------------------------------------------ next unrated and the averages


def test_next_unrated_follows_stable_identity_wraps_and_skips_unreviewable_results():
    plan = [
        variant("completed", refs=["a1", "a2"], value=6.0),
        variant("completed", refs=["b1", "b2"], value=7.0),
    ]
    saved = {"a1", "b2"}
    projection = build_review_projection(plan, lambda ref: 5 if ref in saved else None)

    after_a1 = projection.next_unrated_after("e1:6.0", "a1")
    assert after_a1.image_ref == "a2"
    assert projection.next_unrated_after("e1:6.0", "a2").image_ref == "b1"
    # b1 is the last open one; from b1 the search wraps to a2.
    assert projection.next_unrated_after("e1:7.0", "b1").image_ref == "a2"
    # A file that cannot be reviewed is skipped, never counted as rated.
    skipped = projection.next_unrated_after(
        "e1:6.0", "a1", reviewable=lambda s: s.image_ref != "a2"
    )
    assert skipped.image_ref == "b1"
    # An unknown position starts from the beginning.
    assert projection.next_unrated_after("nope", "nope").image_ref == "a2"
    assert build_review_projection(plan, lambda _r: 4).next_unrated_after("e1:6.0", "a1") is None


def test_average_rating_is_the_mean_of_saved_ratings_only():
    plan = [variant("completed", refs=["a", "b", "c"])]
    summary = build_review_projection(plan, lambda ref: {"a": 2, "b": 4}.get(ref)).variants[0]

    assert summary.average_rating == 3.0
    assert build_review_projection(plan, lambda _r: None).variants[0].average_rating is None


def test_the_plan_table_average_uses_the_opaque_experiment_id_not_the_display_name(tmp_path):
    from unittest.mock import Mock

    from src.gui.controllers.learning_controller import LearningController
    from src.gui.learning_state import LearningState
    from src.learning.learning_record import LearningRecordWriter

    state = LearningState()
    table = Mock()
    controller = LearningController(
        state,
        learning_record_writer=LearningRecordWriter(tmp_path / "records.jsonl"),
        plan_table=table,
    )
    state.current_experiment = LearningExperiment(
        name="Renamed Display Name",
        experiment_id="opaque-id-1",
        variable_under_test="CFG Scale",
        stage="txt2img",
    )
    first = variant("completed", job_id="j1", refs=[str(tmp_path / "a.png")], value=6.0)
    first.experiment_id = "opaque-id-1"
    state.plan = [first]
    controller.record_rating(str(tmp_path / "a.png"), 4, "", None)

    table.update_row_rating.assert_called_with(0, 4.0)


# --------------------------------------------------------------------------------- Preview summary and estimate


def planned_controller(tmp_path):
    exp = LearningExperiment(
        name="cfg sweep",
        experiment_id="exp-590",
        prompt_text="portrait",
        variable_under_test="CFG Scale",
        images_per_value=2,
        metadata={"start_value": 6.0, "end_value": 8.0, "step_value": 1.0},
    )
    controller = controller_for(exp, baseline())
    service = RepositoryService(None)
    controller.pipeline_controller = SimpleNamespace(_job_service=service)
    return controller, service


def test_preview_summary_reads_the_frozen_snapshot_and_queues_nothing(tmp_path):
    controller, service = planned_controller(tmp_path)
    experiment = controller.learning_state.current_experiment

    summary = build_preview_summary(experiment, controller.learning_state.plan)

    assert summary is not None
    rows = dict(summary.rows)
    assert rows["Experiment"] == "cfg sweep" and rows["Study type"] == "Controlled Variable"
    assert rows["Setting tested"] == "CFG Scale" and rows["Values"] == "6.0, 7.0, 8.0"
    assert (rows["Variants"], rows["Images per variant"], rows["Total expected images"]) == (
        "3",
        "2",
        "6",
    )
    assert "3 jobs in one all-or-none submission" in rows["Queue submission"]
    assert "requested seed 42" in rows["Seed"]
    assert summary.headline == "3 variants x 2 images = 6 expected images"
    assert service.calls == []  # Build Preview and its summary never touch the queue


def test_preview_summary_is_absent_without_a_snapshot_and_flags_a_disagreeing_plan(tmp_path):
    assert build_preview_summary(None, []) is None
    controller, _ = planned_controller(tmp_path)
    experiment = controller.learning_state.current_experiment
    short_plan = controller.learning_state.plan[:2]

    summary = build_preview_summary(experiment, short_plan)

    assert any("disagree" in warning for warning in summary.warnings)


def test_estimates_count_the_work_before_a_preview_exists():
    assert count_range_values(6, 8, 1) == 3
    assert count_range_values(8, 6, 1) is None and count_range_values(1, 2, 0) is None
    ordinary = estimate_design(
        study_type="controlled_variable",
        value_type="numeric",
        images_per_value=2,
        start=6,
        end=8,
        step=1,
    )
    assert ordinary.variants == 3 and ordinary.total_images == 6
    assert (
        "3 variants x 2 images = 6 images" in ordinary.text()
        and "nothing is queued" in ordinary.text()
    )
    assert (
        estimate_design(
            study_type="controlled_variable",
            value_type="numeric",
            images_per_value=1,
            start=3,
            end=1,
            step=1,
        ).variants
        is None
    )
    assert (
        estimate_design(
            study_type="model_comparison", value_type="", images_per_value=1, selected_models=["a"]
        ).variants
        is None
    )
    assert (
        estimate_design(
            study_type="model_comparison",
            value_type="",
            images_per_value=2,
            selected_models=["a", "b"],
        ).total_images
        == 4
    )
    assert (
        estimate_design(
            study_type="two_axis_grid", value_type="", images_per_value=2, grid_cells=9
        ).total_images
        == 18
    )
    assert (
        estimate_design(
            study_type="controlled_variable",
            value_type="resource",
            images_per_value=1,
            selected_items=["x", "y"],
        ).variants
        == 2
    )


# --------------------------------------------------------------------------------------- recommendation reading


def rec_set(tier, *, eligible=False, recs=None, context=None):
    return RecommendationSet(
        prompt_text="portrait",
        stage="txt2img",
        timestamp=0.0,
        recommendations=recs
        if recs is not None
        else [
            ParameterRecommendation(
                parameter_name="CFG Scale",
                recommended_value=7.5,
                confidence_score=0.62,
                sample_count=6,
                mean_rating=4.2,
                rating_stddev=0.4,
                confidence_rationale="highest average across tested values",
            )
        ],
        evidence_tier=tier,
        automation_eligible=eligible,
        model_policy_context=context or {"selected_model": "sdxl.safetensors", "family": "sdxl"},
    )


def test_a_strong_controlled_recommendation_states_setting_scope_evidence_and_confidence():
    summary = build_recommendation_summary(
        rec_set(EVIDENCE_TIER_EXPERIMENT_STRONG, eligible=True),
        mode="apply_with_confirm",
        evidence_message="Enough ratings for recommendations.",
        changes=[("CFG Scale", 7.0, 7.5)],
    )

    assert summary.headline == "Suggested: CFG Scale: 7.5"
    assert summary.tier == EVIDENCE_TIER_EXPERIMENT_STRONG
    assert summary.tier_label == "Controlled experiment evidence"
    assert "sdxl.safetensors" in summary.applies_to and "txt2img stage" in summary.applies_to
    details = " ".join(summary.items[0].details)
    assert (
        "4.2 of 5 from 6 ratings" in details
        and "62%" in details
        and "not a statistical guarantee" in details
    )
    assert "highest average" in details
    assert summary.changes == ("Would change CFG Scale: 7.0 -> 7.5",)
    assert summary.apply_enabled and "asks first" in summary.apply_note


@pytest.mark.parametrize(
    "tier,label",
    [
        (EVIDENCE_TIER_SPARSE_PLUS_REVIEW, "manual only"),
        (EVIDENCE_TIER_REVIEW_ONLY, "manual only"),
    ],
)
def test_manual_only_tiers_are_labelled_and_cannot_drive_auto_micro_experiments(tier, label):
    recs = rec_set(tier, eligible=False)
    manual = build_recommendation_summary(recs, mode="apply_with_confirm")
    auto = build_recommendation_summary(recs, mode="auto_micro_experiment")

    assert label in manual.tier_label and manual.apply_enabled
    assert not auto.apply_enabled and "controlled experiment evidence" in auto.apply_note


def test_insufficient_evidence_explains_progress_and_invents_nothing():
    summary = build_recommendation_summary(
        rec_set(EVIDENCE_TIER_NO_EVIDENCE, recs=[]),
        mode="apply_with_confirm",
        evidence_message="Need 3 more ratings across at least 2 more tested values for recommendations.",
    )

    assert not summary.has_recommendations and summary.items == ()
    assert (
        summary.headline.startswith("No recommendation yet.")
        and "Need 3 more ratings" in summary.headline
    )
    assert not summary.apply_enabled and summary.applies_to == ""
    assert build_recommendation_summary(None, mode="apply_with_confirm").items == ()


def test_suggest_only_shows_recommendations_but_never_offers_apply():
    enabled, note = apply_availability(
        "suggest_only", has_recommendations=True, automation_eligible=True
    )

    assert not enabled and "never applied" in note
    summary = build_recommendation_summary(
        rec_set(EVIDENCE_TIER_EXPERIMENT_STRONG, eligible=True), mode="suggest_only"
    )
    assert summary.has_recommendations and not summary.apply_enabled


def test_auto_micro_experiment_says_it_also_queues_one_preview_job():
    enabled, note = apply_availability(
        "auto_micro_experiment", has_recommendations=True, automation_eligible=True
    )

    assert enabled and "queues one preview job" in note
