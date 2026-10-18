"""Rated drafts become ratings on navigation, Save All and the stored-session pass, never over a saved rating."""

from __future__ import annotations

import json
from pathlib import Path

from src.gui.controllers.learning_controller import LearningController
from src.gui.controllers.learning_stored_drafts import commit_stored_drafts
from src.gui.learning_state import LearningState, LearningVariant
from src.learning.experiment_store import LearningExperimentStore
from src.learning.learning_record import LearningRecordWriter


def _design(name: str) -> dict[str, object]:
    return {
        "name": name,
        "description": "controlled sweep",
        "prompt_source": "custom",
        "custom_prompt": "portrait",
        "stage": "txt2img",
        "variable_under_test": "CFG Scale",
        "start_value": 6.0,
        "end_value": 7.0,
        "step_value": 1.0,
        "images_per_value": 2,
    }


def _controller(
    tmp_path: Path, name: str = "Flow"
) -> tuple[LearningController, LearningRecordWriter, LearningState]:
    state = LearningState()
    writer = LearningRecordWriter(tmp_path / "learning_records.jsonl")
    controller = LearningController(state, learning_record_writer=writer)
    controller.update_experiment_design(_design(name))
    experiment = state.current_experiment
    assert experiment is not None
    state.plan = [
        LearningVariant(
            experiment_id=experiment.experiment_id,
            param_value=6.0,
            status="completed",
            image_refs=["a.png", "b.png"],
            job_id="j1",
        ),
        LearningVariant(
            experiment_id=experiment.experiment_id,
            param_value=7.0,
            status="completed",
            image_refs=["c.png", "d.png"],
            job_id="j2",
        ),
    ]
    return controller, writer, state


def _records(tmp_path: Path) -> list[dict]:
    path = tmp_path / "learning_records.jsonl"
    if not path.exists():
        return []
    return [
        json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()
    ]


def _draft(rating: int = 4) -> dict[str, object]:
    return {
        "overall_rating": rating,
        "notes": "n",
        "context_flags": {"people": True},
        "subscores": {"composition": 5},
    }


def test_commit_review_draft_saves_one_rating_and_clears_its_draft(tmp_path: Path) -> None:
    controller, _writer, _state = _controller(tmp_path)
    controller.save_review_draft("a.png", _draft(4))

    assert controller.commit_review_draft("a.png") is True

    assert controller.get_review_draft("a.png") is None
    assert controller.is_image_rated("a.png")
    (record,) = _records(tmp_path)
    assert record["metadata"]["image_path"] == "a.png"
    assert record["metadata"]["user_rating_raw"] == 4
    assert record["metadata"]["user_notes"] == "n"
    assert record["metadata"]["rating_details"] == {"composition": 5}


def test_a_saved_rating_is_never_overridden_by_a_draft(tmp_path: Path) -> None:
    controller, _writer, _state = _controller(tmp_path)
    controller.record_rating("a.png", 2, "first", {"context_flags": {}, "subscores": {}})
    controller.save_review_draft("a.png", _draft(5))

    assert controller.commit_review_draft("a.png") is False

    assert len(_records(tmp_path)) == 1
    assert controller.get_rating_for_image("a.png") == 2
    assert controller.get_review_draft("a.png") is not None


def test_save_all_commits_every_rated_draft_and_keeps_the_rest(tmp_path: Path) -> None:
    controller, _writer, _state = _controller(tmp_path)
    controller.save_review_draft("a.png", _draft(3))
    controller.save_review_draft("b.png", {"overall_rating": 0, "notes": "only a note"})
    controller.save_review_draft("c.png", _draft(5))

    summary = controller.commit_review_drafts()

    assert (summary.committed, summary.unrated) == (2, 1)
    assert {r["metadata"]["image_path"] for r in _records(tmp_path)} == {"a.png", "c.png"}
    assert controller.get_review_draft("b.png") is not None
    assert controller.get_evidence_progress().message() == "Need 1 more rating for recommendations."


def test_without_a_record_writer_nothing_is_committed_and_the_draft_stays(tmp_path: Path) -> None:
    state = LearningState()
    controller = LearningController(state)
    controller.update_experiment_design(_design("No writer"))
    experiment = state.current_experiment
    assert experiment is not None
    state.plan = [
        LearningVariant(
            experiment_id=experiment.experiment_id, status="completed", image_refs=["a.png"]
        )
    ]
    controller.save_review_draft("a.png", _draft(4))

    assert controller.commit_review_draft("a.png") is False
    assert controller.get_review_draft("a.png") is not None


def test_resuming_a_session_keeps_its_drafts(tmp_path: Path) -> None:
    controller, _writer, state = _controller(tmp_path)
    controller.save_review_draft("a.png", _draft(4))
    payload = state.to_dict()
    payload["workflow_state"] = "review"

    fresh = LearningController(
        LearningState(),
        learning_record_writer=LearningRecordWriter(tmp_path / "learning_records.jsonl"),
    )

    assert fresh.restore_resume_state(payload) is True
    assert fresh.get_review_draft("a.png")["overall_rating"] == 4  # type: ignore[index]


def test_evidence_progress_counts_saved_ratings_per_tested_value(tmp_path: Path) -> None:
    controller, _writer, _state = _controller(tmp_path)
    assert (
        controller.get_evidence_progress().message()
        == "Need 3 more ratings across at least 2 more tested values for recommendations."
    )

    controller.record_rating("a.png", 4, "", {"context_flags": {}, "subscores": {}})
    controller.record_rating("b.png", 4, "", {"context_flags": {}, "subscores": {}})
    assert (
        controller.get_evidence_progress().message()
        == "Need 1 more rating across at least 1 more tested value for recommendations."
    )

    controller.record_rating("c.png", 3, "", {"context_flags": {}, "subscores": {}})
    assert controller.get_evidence_progress().ready is True


def _save_session(
    store: LearningExperimentStore, controller: LearningController, state: LearningState
) -> str:
    experiment = state.current_experiment
    assert experiment is not None
    store.save_session(
        display_name=experiment.name,
        payload=state.to_dict(),
        experiment_id=experiment.experiment_id,
    )
    return experiment.experiment_id


def test_stored_session_drafts_are_previewed_then_committed_once(tmp_path: Path) -> None:
    store = LearningExperimentStore(tmp_path / "experiments")
    controller, writer, state = _controller(tmp_path, "Stored A")
    controller.save_review_draft("a.png", _draft(4))
    controller.save_review_draft("b.png", {"overall_rating": 0, "notes": "note"})
    experiment_id = _save_session(store, controller, state)
    store.set_last_experiment_id("someone-else")
    before = store.session_path_for(experiment_id).read_text(encoding="utf-8")

    kwargs = {
        "store": store,
        "writer": writer,
        "build_record": controller.build_rating_record,
        "open_experiment_ids": (),
    }
    preview = commit_stored_drafts(apply=False, **kwargs)

    assert (preview.summary.committed, preview.summary.unrated, preview.applied) == (1, 1, False)
    assert _records(tmp_path) == []
    assert store.session_path_for(experiment_id).read_text(encoding="utf-8") == before

    done = commit_stored_drafts(apply=True, **kwargs)

    assert done.summary.committed == 1
    (record,) = _records(tmp_path)
    assert record["metadata"]["image_path"] == "a.png"
    assert record["metadata"]["experiment_id"] == experiment_id
    remaining = store.load_session(experiment_id)["review_drafts"]  # type: ignore[index]
    assert list(remaining) == [f"{experiment_id}:b.png"]
    assert store.get_last_experiment_id() == "someone-else"

    again = commit_stored_drafts(apply=True, **kwargs)

    assert again.summary.committed == 0
    assert len(_records(tmp_path)) == 1


def test_the_open_experiment_and_unreadable_sessions_are_left_alone(tmp_path: Path) -> None:
    store = LearningExperimentStore(tmp_path / "experiments")
    controller, writer, state = _controller(tmp_path, "Open one")
    controller.save_review_draft("a.png", _draft(4))
    experiment_id = _save_session(store, controller, state)
    store.save_session(
        display_name="Broken",
        payload={"review_drafts": {"x:y": {"overall_rating": 3}}},
        experiment_id="broken",
    )

    report = commit_stored_drafts(
        store=store,
        writer=writer,
        build_record=controller.build_rating_record,
        open_experiment_ids={experiment_id},
        apply=True,
    )

    assert report.skipped_open_experiments == 1
    assert report.unreadable_sessions == 1
    assert report.summary.committed == 0
    assert _records(tmp_path) == []
    assert "open experiment is skipped" in report.describe()
