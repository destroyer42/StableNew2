"""Learning outcome and evidence consistency (fix/learn-evidence-consistency).

Saved ratings stay append-only history, but the evidence read from them must count each sample once at its
current rating, rank the best-rated value first, accept whole-number Steps written as floats by older sweeps,
keep a saved rating saved when a display refresh fails, and apply one recommendation eligibility rule.
"""

from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from src.gui.controllers.learning_controller import LearningController
from src.gui.learning_state import LearningExperiment, LearningState, LearningVariant
from src.learning.learning_controller_services.controlled_studies import (
    LOCAL_ONLY_STUDIES,
    LOCAL_STUDY_RECOMMENDATION_NOTICE,
    reports_setting_recommendations,
)
from src.learning.learning_record import (
    LearningRecordWriter,
    current_rating_revisions,
    rating_revision_key,
)
from src.learning.recommendation_engine import (
    EVIDENCE_TIER_EXPERIMENT_STRONG,
    EVIDENCE_TIER_SPARSE_PLUS_REVIEW,
    RecommendationEngine,
)
from src.learning.variable_metadata import LEARNING_VARIABLES, whole_number_values
from tests.learning_v2.test_profile_publication_660 import make_publication, records


def _write(path: Path, rows: list[dict]) -> None:
    path.write_text("".join(json.dumps(row) + "\n" for row in rows), encoding="utf-8")


def _rating(image: str, cfg: float, rating, experiment: str = "exp-1") -> dict:
    config = {"txt2img": {"model": "test-model", "steps": 20, "cfg_scale": cfg}}
    return {
        "primary_sampler": "Euler a",
        "primary_scheduler": "normal",
        "primary_steps": 20,
        "primary_cfg_scale": cfg,
        "base_config": {"prompt": "portrait", "stage": "txt2img"},
        "metadata": {
            "record_kind": "learning_experiment_rating",
            "experiment_id": experiment,
            "image_path": image,
            "variable_under_test": "CFG Scale",
            "variant_value": cfg,
            "user_rating": rating,
            "stage": "txt2img",
            "frozen_experiment": {
                "snapshot": {"experiment_id": experiment},
                "executed_config": config,
            },
        },
    }


def _recommend(tmp_path: Path, rows: list[dict]):
    path = tmp_path / "learning_records.jsonl"
    _write(path, rows)
    return RecommendationEngine(path).recommend("portrait", "txt2img")


def _cfg(result):
    return next(rec for rec in result.recommendations if rec.parameter_name == "cfg_scale")


# -- Finding 2: a revised rating replaces the earlier one ----------------------------------------------------------


def test_a_replaced_rating_does_not_add_evidence_or_reach_the_strong_tier(tmp_path):
    rows = [_rating("a.png", 6.0, 5), _rating("a.png", 6.0, 1), _rating("b.png", 7.0, 4)]
    result = _recommend(tmp_path, rows)
    assert result.controlled_rating_count == 2  # not 3: the replaced 5 no longer counts
    assert result.evidence_tier == EVIDENCE_TIER_SPARSE_PLUS_REVIEW
    assert result.automation_eligible is False
    assert _cfg(result).recommended_value == 7.0  # A's current rating is 1, not the replaced 5


def test_repeating_the_same_rating_counts_once(tmp_path):
    rows = [_rating("a.png", 6.0, 4)] * 3 + [_rating("b.png", 7.0, 4)]
    result = _recommend(tmp_path, rows)
    assert result.controlled_rating_count == 2
    assert result.automation_eligible is False


@pytest.mark.parametrize("latest", [None, 0, 9, "bad"])
def test_an_unusable_latest_revision_removes_the_sample(tmp_path, latest):
    rows = [
        _rating("a.png", 6.0, 5),
        _rating("b.png", 7.0, 4),
        _rating("c.png", 7.0, 4),
        _rating("a.png", 6.0, latest),
    ]
    result = _recommend(tmp_path, rows)
    assert result.controlled_rating_count == 2  # a.png does not fall back to its replaced 5
    assert result.evidence_tier != EVIDENCE_TIER_EXPERIMENT_STRONG
    assert _cfg(result).recommended_value == 7.0


def test_distinct_samples_and_experiments_stay_separate_and_curation_events_are_not_collapsed():
    a1, a2 = _rating("a.png", 6.0, 4, "exp-1"), _rating("a.png", 6.0, 2, "exp-2")
    curation = {
        "metadata": {
            "record_kind": "staged_curation_event",
            "image_path": "a.png",
            "user_rating": 3,
        }
    }
    review = {
        "metadata": {"record_kind": "review_tab_feedback", "image_path": "a.png", "user_rating": 5}
    }
    unkeyed = {"metadata": {"user_rating": 4}}
    rows = [a1, a2, curation, dict(curation), review, unkeyed]
    assert current_rating_revisions(rows) == rows
    assert rating_revision_key(a1) != rating_revision_key(a2)
    assert rating_revision_key(curation) is None and rating_revision_key(unkeyed) is None
    revised = current_rating_revisions([a1, review, _rating("a.png", 6.0, 1, "exp-1")])
    assert [row["metadata"].get("user_rating") for row in revised] == [5, 1]


def test_statistics_count_current_ratings_only(tmp_path):
    path = tmp_path / "learning_records.jsonl"
    _write(path, [_rating("a.png", 6.0, 5), _rating("a.png", 6.0, 1)])
    stats = RecommendationEngine(path).get_statistics()
    assert stats["total_records"] == 2  # history is still all there
    assert stats["rated_records"] == 1


# -- Finding 3: quality first ---------------------------------------------------------------------------------------


def test_the_best_rated_value_wins_over_a_more_numerous_poorly_rated_one(tmp_path):
    rows = [_rating(f"low-{i}.png", 6.0, 1) for i in range(6)]
    rows += [_rating(f"high-{i}.png", 7.0, 5) for i in range(3)]
    result = _recommend(tmp_path, rows)
    assert result.evidence_tier == EVIDENCE_TIER_EXPERIMENT_STRONG
    rec = _cfg(result)
    assert rec.recommended_value == 7.0
    assert rec.mean_rating == 5.0 and rec.sample_count == 3


def test_equal_means_are_broken_by_confidence(tmp_path):
    rows = [_rating(f"few-{i}.png", 6.0, 4) for i in range(1)]
    rows += [_rating(f"many-{i}.png", 7.0, 4) for i in range(4)]
    assert _cfg(_recommend(tmp_path, rows)).recommended_value == 7.0


def test_publication_ranks_the_best_rated_value_first(tmp_path):
    publication = make_publication(tmp_path)
    rows = records(publication, values=(20, 20, 20, 20, 20, 30))  # 20 rates 3 (x5), 30 rates 5 (x1)
    proposal = publication.evaluate(rows, "test.safetensors", experiment_id="experiment-1")
    assert proposal.settings == {"steps": 30}


# -- Finding 4: Steps are whole numbers ------------------------------------------------------------------------------


def test_older_whole_number_steps_saved_as_floats_publish_as_integers(tmp_path):
    publication = make_publication(tmp_path)
    rows = records(publication, values=(20.0, 30.0, 40.0))
    proposal = publication.evaluate(rows, "test.safetensors", experiment_id="experiment-1")
    assert proposal.settings == {"steps": 30}
    assert type(proposal.settings["steps"]) is int
    saved = publication.publish(proposal, rows, "test.safetensors", name="Findings", confirmed=True)
    assert saved.settings == {"steps": 30} and type(saved.settings["steps"]) is int
    assert rows[1]["metadata"]["variant_value"] == 30.0  # saved history is not rewritten


def test_fractional_steps_are_still_refused(tmp_path):
    publication = make_publication(tmp_path)
    rows = records(publication, values=(20.0, 30.5, 40.0, 50.0))
    proposal = publication.evaluate(rows, "test.safetensors", experiment_id="experiment-1")
    assert 30.5 not in proposal.settings.values()
    assert (
        proposal.sample_count == 3
    )  # the 30.5 sample is refused; the whole-number ones still count


def test_whole_number_rule_applies_only_to_integer_variables():
    steps, cfg = LEARNING_VARIABLES["steps"], LEARNING_VARIABLES["cfg_scale"]
    assert whole_number_values(steps, [20.0, 25.0, 30]) == [20, 25, 30]
    assert all(type(value) is int for value in whole_number_values(steps, [20.0, 25.0]))
    with pytest.raises(ValueError, match="whole numbers"):
        whole_number_values(steps, [20.0, 22.5])
    assert whole_number_values(cfg, [6.5, 7.0]) == [6.5, 7.0]


def _steps_controller(start, end, step) -> tuple[LearningController, LearningExperiment]:
    state = LearningState()
    controller = LearningController(state)
    controller.update_experiment_design(
        {
            "name": "Steps",
            "prompt_source": "custom",
            "custom_prompt": "portrait",
            "stage": "txt2img",
            "variable_under_test": "Steps",
            "start_value": start,
            "end_value": end,
            "step_value": step,
            "images_per_value": 1,
        }
    )
    assert state.current_experiment is not None
    return controller, state.current_experiment


def test_the_steps_designer_produces_integer_values():
    controller, experiment = _steps_controller("20", "30", "5")
    values = controller._generate_variant_values(experiment)  # noqa: SLF001
    assert values == [20, 25, 30]
    assert all(type(value) is int for value in values)


def test_the_steps_designer_refuses_a_fractional_step():
    controller, experiment = _steps_controller(20, 25, 2.5)
    with pytest.raises(ValueError, match="whole numbers"):
        controller._generate_variant_values(experiment)  # noqa: SLF001


# -- Finding 5: a saved rating stays saved -------------------------------------------------------------------------


def _rating_controller(tmp_path: Path) -> tuple[LearningController, Path]:
    path = tmp_path / "learning_records.jsonl"
    state = LearningState()
    controller = LearningController(state, learning_record_writer=LearningRecordWriter(path))
    controller.update_experiment_design(
        {
            "name": "Save",
            "prompt_source": "custom",
            "custom_prompt": "portrait",
            "stage": "txt2img",
            "variable_under_test": "CFG Scale",
            "start_value": 6.0,
            "end_value": 7.0,
            "step_value": 1.0,
            "images_per_value": 1,
        }
    )
    experiment = state.current_experiment
    assert experiment is not None
    state.plan = [
        LearningVariant(
            experiment_id=experiment.experiment_id,
            param_value=6.0,
            status="completed",
            image_refs=["a.png"],
            job_id="j1",
        )
    ]
    return controller, path


def test_a_refresh_failure_after_the_append_is_a_warning_not_a_failed_save(tmp_path):
    controller, path = _rating_controller(tmp_path)

    def broken() -> None:
        raise RuntimeError("recommendation display broke")

    controller.refresh_recommendations = broken  # type: ignore[method-assign]
    notified: list[bool] = []
    controller._notify_resume_state_changed = lambda: notified.append(True)  # type: ignore[method-assign]  # noqa: SLF001

    warning = controller.record_rating("a.png", 4, "kept")

    assert "recommendation display broke" in warning
    assert len(path.read_text(encoding="utf-8").splitlines()) == 1
    assert controller.get_rating_for_image("a.png") == 4
    assert notified  # later refreshes still ran after the failing one


def test_a_clean_save_returns_no_warning_and_a_failed_append_still_raises(tmp_path):
    controller, _path = _rating_controller(tmp_path)
    assert controller.record_rating("a.png", 4) == ""
    controller._learning_record_writer.append_record = lambda _record: False  # type: ignore[method-assign]  # noqa: SLF001
    with pytest.raises(OSError):
        controller.record_rating("a.png", 5)
    assert controller.get_rating_for_image("a.png") == 4


def test_qualification_review_reports_a_saved_rating_with_a_refresh_warning():
    from src.gui_v2.qualification_review_session import QualificationReviewSession

    experiment = object()
    controller = SimpleNamespace(
        learning_state=SimpleNamespace(current_experiment=experiment),
        get_rating_details_for_image=lambda _ref: None,
        save_review_draft=lambda *_args: None,
        record_rating=lambda *_args: "grid could not refresh",
    )
    session = QualificationReviewSession(controller)
    saved, message = session.save("a.png", {"overall_rating": 4}, confirm=lambda _ref: True)
    assert saved is True
    assert message.startswith("Saved") and "grid could not refresh" in message


# -- Finding 6: one recommendation eligibility rule ----------------------------------------------------------------


@pytest.mark.parametrize("study", sorted(LOCAL_ONLY_STUDIES))
def test_local_studies_get_a_notice_from_refresh_and_none_from_the_getter(tmp_path, study):
    state = LearningState()
    controller = LearningController(state)
    controller.update_experiment_design(
        {
            "name": "Local",
            "prompt_source": "custom",
            "custom_prompt": "portrait",
            "stage": "txt2img",
            "variable_under_test": "CFG Scale",
            "start_value": 6.0,
            "end_value": 7.0,
            "step_value": 1.0,
            "images_per_value": 1,
        }
    )
    experiment = state.current_experiment
    assert experiment is not None
    experiment.metadata["study_type"] = study
    calls: list[str] = []
    controller._recommendation_engine = SimpleNamespace(  # noqa: SLF001
        recommend=lambda *a, **k: calls.append("recommend") or "would be shown",
        _cache_timestamp=1.0,
    )
    shown: list[tuple[str, object]] = []
    controller._review_panel = SimpleNamespace(  # noqa: SLF001
        update_recommendations=lambda recs: shown.append(("recs", recs)),
        show_recommendation_notice=lambda text: shown.append(("notice", text)),
    )

    assert reports_setting_recommendations(experiment) is False
    assert controller.get_recommendations_for_current_prompt() is None
    controller.refresh_recommendations()

    assert shown == [("notice", LOCAL_STUDY_RECOMMENDATION_NOTICE)]
    assert calls == []


def test_ordinary_sweeps_refresh_through_the_same_getter(tmp_path):
    state = LearningState()
    controller = LearningController(state)
    controller.update_experiment_design(
        {
            "name": "Ordinary",
            "prompt_source": "custom",
            "custom_prompt": "portrait",
            "stage": "txt2img",
            "variable_under_test": "CFG Scale",
            "start_value": 6.0,
            "end_value": 7.0,
            "step_value": 1.0,
            "images_per_value": 1,
        }
    )
    controller._recommendation_engine = SimpleNamespace(  # noqa: SLF001
        recommend=lambda *a, **k: "recommendations", _cache_timestamp=1.0
    )
    shown: list[object] = []
    controller._review_panel = SimpleNamespace(update_recommendations=shown.append)  # noqa: SLF001
    assert reports_setting_recommendations(state.current_experiment) is True
    assert reports_setting_recommendations(None) is True
    controller.refresh_recommendations()
    assert shown == ["recommendations"] == [controller.get_recommendations_for_current_prompt()]
