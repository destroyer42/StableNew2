"""LEARN-OUTCOME-870: closure is written only by the store, only as the closure block, and never touches jobs."""

from __future__ import annotations

import hashlib
import json
from datetime import UTC, datetime
from pathlib import Path

import pytest

from src.learning import experiment_outcome as eo
from src.learning.experiment_store import LearningExperimentStore
from src.learning.intelligence_sources import read_rating_log
from src.learning.library_status import library_outcomes
from src.learning.next_actions import rated_map
from tests.learning_v2.test_experiment_outcome_870 import image, payload

NOW = datetime(2026, 11, 15, 12, 0, tzinfo=UTC)


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def saved(tmp_path, study="prompt_slot", values=("A", "B", "C"), **kw):
    store = LearningExperimentStore(tmp_path / "experiments")
    data = payload(study, list(values), experiment_id="exp1", **kw)
    data["current_experiment"]["metadata"]["qualification_batch"] = {"batch_id": "b1"}
    data["review_drafts"] = {f"exp1:{image('exp1', 0, 0)}": {"overall_rating": 4, "notes": "draft"}}
    store.save_session(display_name="exp1", payload=data, experiment_id="exp1")
    return store, data


def records(tmp_path, rows):
    path = tmp_path / "learning_records.jsonl"
    path.write_text("".join(json.dumps(r) + "\n" for r in rows), encoding="utf-8")
    return path


def rating_row(ref, rating, *, kind="learning_experiment_rating", job="job-0"):
    return {
        "metadata": {
            "record_kind": kind,
            "experiment_id": "exp1",
            "job_id": job,
            "image_path": ref,
            "user_rating": rating,
            "user_rating_raw": rating,
        }
    }


def test_close_writes_only_the_closure_block_and_reopen_restores_the_bytes(tmp_path):
    store, data = saved(tmp_path)
    ratings_file = records(tmp_path, [rating_row(image("exp1", 0, 0), 4)])
    session = store.session_path_for("exp1")
    originals = {
        name: sha(path)
        for name, path in {
            "session": session,
            "meta": session.parent / "meta.json",
            "index": store.root / "index.json",
            "ratings": ratings_file,
        }.items()
    }
    before = json.loads(session.read_text("utf-8"))

    block = eo.close_experiment(store, "exp1", data, {image("exp1", 0, 0): 4}, note="done", now=NOW)

    after = json.loads(session.read_text("utf-8"))
    assert after.pop("closure") == block
    assert after == before  # job associations, drafts, snapshot: unchanged
    assert [v["job_id"] for v in after["plan"]] == ["job-0", "job-1", "job-2"]
    assert after["review_drafts"] == before["review_drafts"]
    assert sha(ratings_file) == originals["ratings"]  # the ratings file is byte-identical
    assert sha(session.parent / "meta.json") == originals["meta"]
    assert sha(store.root / "index.json") == originals["index"]
    assert block["closed_at"] == NOW.isoformat() and block["note"] == "done"
    assert not list(session.parent.glob("*.tmp"))

    assert eo.reopen_experiment(store, "exp1") is True
    assert "closure" not in json.loads(session.read_text("utf-8"))
    assert sha(session) == originals["session"]  # byte-identical to before the close
    assert eo.reopen_experiment(store, "exp1") is False  # nothing to remove


def test_closure_survives_a_restart_and_ordinary_saves(tmp_path):
    store, data = saved(tmp_path)
    block = eo.close_experiment(store, "exp1", data, {}, now=NOW)
    assert (
        eo.closure_of(LearningExperimentStore(tmp_path / "experiments").load_session("exp1"))
        == block
    )

    # The Learning tab saves a payload that has no closure key; the saved closure is carried forward unchanged.
    resaved = {k: v for k, v in data.items() if k != "closure"}
    resaved["plan"][0]["status"] = "completed"
    LearningExperimentStore(tmp_path / "experiments").save_session(
        display_name="exp1", payload=resaved, experiment_id="exp1"
    )
    reloaded = LearningExperimentStore(tmp_path / "experiments").load_session("exp1")
    assert eo.closure_of(reloaded) == block
    # An ordinary save cannot add or edit a closure either.
    forged = {**resaved, "closure": {"closed_at": "2000-01-01", "evidence_fingerprint": "x"}}
    store.save_session(display_name="exp1", payload=forged, experiment_id="exp1")
    assert eo.closure_of(store.load_session("exp1")) == block
    # ...and a reopened experiment stays open across ordinary saves.
    eo.reopen_experiment(store, "exp1")
    store.save_session(display_name="exp1", payload=resaved, experiment_id="exp1")
    assert eo.closure_of(store.load_session("exp1")) is None


def test_closure_does_not_disturb_batch_association_protection(tmp_path):
    store, data = saved(tmp_path)
    eo.close_experiment(store, "exp1", data, {}, now=NOW)
    changed = json.loads(json.dumps(data))
    changed["plan"][0]["job_id"] = "someone-else"
    with pytest.raises(ValueError, match="batch associations changed"):
        store.save_session(display_name="exp1", payload=changed, experiment_id="exp1")
    assert store.load_session("exp1")["plan"][0]["job_id"] == "job-0"


def test_closing_needs_a_saved_session_and_a_finished_experiment(tmp_path):
    store = LearningExperimentStore(tmp_path / "experiments")
    data = payload("prompt_slot", ["A", "B"], experiment_id="ghost")
    with pytest.raises(eo.ClosureRefused, match="no saved session"):
        eo.close_experiment(store, "ghost", data, {})
    assert not (store.root / "ghost").exists()  # a refused close creates nothing
    with pytest.raises(eo.ClosureRefused, match="no saved session"):
        eo.reopen_experiment(store, "ghost")
    running_store, running = saved(tmp_path / "r", status="running")
    with pytest.raises(eo.ClosureRefused, match="not finished"):
        eo.close_experiment(running_store, "exp1", running, {})
    assert eo.closure_of(running_store.load_session("exp1")) is None


def test_later_rating_marks_changed_since_closure_through_the_stored_session(tmp_path):
    store, data = saved(tmp_path)
    eo.close_experiment(store, "exp1", data, {}, now=NOW)
    stored = store.load_session("exp1")
    unchanged = eo.derive_outcome(stored, {})
    assert unchanged.closed and not unchanged.changed_since_closure
    assert unchanged.text == "Insufficient evidence, closed by operator"
    later = eo.derive_outcome(stored, {image("exp1", 0, 0): 5})
    assert later.closed and later.changed_since_closure and "changed since closure" in later.text


def test_closing_never_calls_job_service_or_changes_the_repository(tmp_path, monkeypatch):
    from src.controller.job_service import JobService
    from src.queue.job_repository import JobRepository

    repository = JobRepository(tmp_path / "jobs.sqlite3")
    try:
        before = repository.count_jobs() if hasattr(repository, "count_jobs") else None
        for name in dir(JobService):
            if name.startswith("submit") or name in {"cancel_job", "retry_job", "run_next_now"}:
                monkeypatch.setattr(
                    JobService,
                    name,
                    lambda *a, _n=name, **k: (_ for _ in ()).throw(
                        AssertionError(f"JobService.{_n} called")
                    ),
                )
        for name in ("save_job", "update_status", "transition", "record_job", "delete_job"):
            if hasattr(JobRepository, name):
                monkeypatch.setattr(
                    JobRepository,
                    name,
                    lambda *a, _n=name, **k: (_ for _ in ()).throw(
                        AssertionError(f"repository.{_n} called")
                    ),
                )
        db_before = sha(tmp_path / "jobs.sqlite3")
        store, data = saved(tmp_path)
        eo.close_experiment(store, "exp1", data, {}, now=NOW)
        eo.reopen_experiment(store, "exp1")
        assert sha(tmp_path / "jobs.sqlite3") == db_before
        if before is not None:
            assert repository.count_jobs() == before
    finally:
        repository.close()


def test_library_outcomes_read_every_rating_kind_once_and_mark_closed_experiments(tmp_path):
    store, data = saved(tmp_path, study="model_comparison", values=("m-a", "m-b", "m-c"))
    refs = [ref for v in data["plan"] for ref in v["image_refs"]]
    log = records(
        tmp_path,
        [
            rating_row(refs[0], 4, kind="learning_model_comparison_rating", job="job-0"),
            rating_row(refs[2], 3, kind="learning_model_comparison_rating", job="job-1"),
            rating_row(refs[4], 5, kind="learning_model_comparison_rating", job="job-2"),
            rating_row(
                refs[0], 2, kind="learning_model_comparison_rating", job="job-0"
            ),  # replaced rating
            {"metadata": {"record_kind": "review_tab_feedback", "experiment_id": "exp1"}},
        ],
    )
    open_outcomes = library_outcomes({"exp1": store.load_session("exp1")}, log)
    assert open_outcomes["exp1"].code == eo.OUTCOME_SUPPORTED  # a rating for each model
    # closing it changes nothing about the derived outcome except to mark it closed
    eo.close_experiment(store, "exp1", store.load_session("exp1"), dict.fromkeys(refs, 3))
    closed = library_outcomes({"exp1": store.load_session("exp1")}, log)["exp1"]
    assert closed.closed and closed.code == eo.OUTCOME_SUPPORTED
    assert library_outcomes({"exp1": store.load_session("exp1")}, tmp_path / "missing.jsonl")[
        "exp1"
    ].code == (
        eo.OUTCOME_INSUFFICIENT_EVIDENCE  # closed with no readable ratings
    )


def test_rating_log_collects_other_study_kinds_without_changing_publication_rows(tmp_path):
    log = records(
        tmp_path,
        [
            rating_row("a.png", 4, kind="learning_experiment_rating"),
            rating_row("b.png", 5, kind="learning_grid_rating"),
            rating_row("c.png", 3, kind="learning_prompt_model_matrix_rating"),
            rating_row("d.png", 2, kind="learning_unknown_rating"),
        ],
    )
    parsed = read_rating_log(log)
    assert [r["metadata"]["image_path"] for r in parsed.rows] == ["a.png"]
    assert sorted(r["metadata"]["image_path"] for r in parsed.study_rows) == ["b.png", "c.png"]
    rated = rated_map((), parsed.study_rows)
    assert rated == {("exp1", "b.png"): 5.0, ("exp1", "c.png"): 3.0}
    assert read_rating_log(records(tmp_path, [rating_row("a.png", 4)])).revision != parsed.revision


# ---- What Should I Test Next? covers every cataloged study -------------------------------------------------------


def _saved_study(store, experiment_id, study, *, values=("A", "B"), status="completed"):
    """A finished, controlled experiment of ``study`` frozen on the fixtures' checkpoint."""
    from tests.learning_v2 import intelligence_fixtures_830 as fx

    target = fx.resolver().resolve(fx.MODEL)
    data = payload(study, list(values), experiment_id=experiment_id, status=status)
    snapshot = json.loads(data["current_experiment"]["execution_snapshot_json"])
    if study == "model_comparison":
        snapshot["model_comparison"] = {
            "arms": [
                {
                    "checkpoint_evidence": {"sha256": fx.SHA},
                    "model_policy_context": {"family": target.identity.family},
                }
            ]
        }
    else:
        snapshot["model_identity"] = target.identity.to_dict()
    data["current_experiment"]["execution_snapshot_json"] = json.dumps(snapshot)
    store.save_session(display_name=experiment_id, payload=data, experiment_id=experiment_id)
    return data


@pytest.mark.parametrize(
    ("study", "kind"),
    [
        ("lora_composition", "learning_experiment_rating"),
        ("model_comparison", "learning_model_comparison_rating"),
        ("prompt_slot", "learning_experiment_rating"),
    ],
)
def test_unrated_study_gets_a_complete_ratings_action_and_a_closed_one_is_listed_not_offered(
    tmp_path, study, kind
):
    from src.learning.intelligence_contracts import ACTION_COMPLETE_RATINGS
    from tests.learning_v2 import intelligence_fixtures_830 as fx

    store = LearningExperimentStore(tmp_path / "experiments")
    data = _saved_study(store, "exp-study", study)
    report, sources = fx.run(tmp_path)
    actions = [a for a in report.actions.actions if a.kind == ACTION_COMPLETE_RATINGS]
    assert [a.target_id for a in actions] == ["exp-study"], study
    assert actions[0].workload_map()["images_to_rate"] == 4
    assert actions[0].workload_map()["images_to_generate"] == 0

    # Rate one image under the study's own record kind: it counts as rated, three remain.
    ref = data["plan"][0]["image_refs"][0]
    row = rating_row(ref, 4, kind=kind)
    row["metadata"]["experiment_id"] = "exp-study"
    rows = [row]
    partial, _ = fx.run(tmp_path, rows=rows)
    again = [a for a in partial.actions.actions if a.kind == ACTION_COMPLETE_RATINGS]
    assert again and again[0].workload_map()["images_to_rate"] == 3

    # Closing suppresses the action and the reason is listed (and the fingerprint changes with the closure).
    eo.close_experiment(store, "exp-study", store.load_session("exp-study"), {}, now=NOW)
    closed, _ = fx.run(tmp_path, rows=rows)
    assert not [a for a in closed.actions.actions if a.kind == ACTION_COMPLETE_RATINGS]
    reasons = [why for _name, why in closed.actions.suppressed]
    assert any("closed by the operator" in why for why in reasons), reasons
    assert closed.fingerprint != partial.fingerprint
    eo.reopen_experiment(store, "exp-study")
    reopened, _ = fx.run(tmp_path, rows=rows)
    assert [a for a in reopened.actions.actions if a.kind == ACTION_COMPLETE_RATINGS]
    assert reopened.fingerprint == partial.fingerprint


def test_an_invalid_study_run_yields_an_investigate_action_for_every_study(tmp_path):
    from src.learning.intelligence_contracts import ACTION_INVESTIGATE_EXECUTION
    from tests.learning_v2 import intelligence_fixtures_830 as fx

    store = LearningExperimentStore(tmp_path / "experiments")
    for study in (
        "lora_composition",
        "embedding_experiment",
        "two_axis_grid",
        "compatibility_probe",
    ):
        data = _saved_study(store, f"bad-{study}", study)
        for variant in data["plan"]:
            variant["execution_metadata"] = {
                "controlled_evidence_valid": False,
                "variable_validation_reason": "backend_restart_boundary",
            }
        store.save_session(display_name=study, payload=data, experiment_id=f"bad-{study}")
    report, _ = fx.run(tmp_path)
    found = sorted(
        a.target_id for a in report.actions.actions if a.kind == ACTION_INVESTIGATE_EXECUTION
    )
    assert found == sorted(
        f"bad-{s}"
        for s in (
            "lora_composition",
            "embedding_experiment",
            "two_axis_grid",
            "compatibility_probe",
        )
    )
