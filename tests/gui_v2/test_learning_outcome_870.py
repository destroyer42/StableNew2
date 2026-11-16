"""LEARN-OUTCOME-870 in a real Tk Learning tab: the derived outcome, Close, Reopen and the Library Open/Closed filter.

Confirmation dialogs are injected (a live messagebox would hang the test); only a fake backend and temp roots are used.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from src.gui.app_state_v2 import AppStateV2
from src.gui.views.learning_tab_frame_v2 import LearningTabFrame
from src.learning import experiment_outcome as eo
from src.queue.job_model import JobStatus
from src.queue.job_repository import JobRepository
from src.services.ui_state_store import UIStateStore
from tests.gui_v2.tk_test_utils import get_shared_tk_root
from tests.learning_v2.test_learning_recovery_260 import (
    RepositoryService,
    planned,
    result_for,
    transition,
)


@pytest.fixture
def workspace(tmp_path, monkeypatch):
    root = get_shared_tk_root()
    assert root is not None, "LEARN-OUTCOME-870 requires a real Tk test"
    ui_store = UIStateStore(tmp_path / "ui_state.json")
    monkeypatch.setattr("src.gui.views.learning_tab_frame_v2.get_ui_state_store", lambda: ui_store)
    monkeypatch.setattr(
        "src.gui.views.learning_tab_frame_v2.get_learning_experiments_root",
        lambda: tmp_path / "experiments",
    )
    monkeypatch.setattr(
        "src.gui.views.learning_tab_frame_v2.get_learning_records_path",
        lambda: tmp_path / "ratings.jsonl",
    )
    repo = JobRepository(tmp_path / "jobs.sqlite3")
    tabs: list[LearningTabFrame] = []

    def make_tab(service):
        tab = LearningTabFrame(
            root, app_state=AppStateV2(), pipeline_controller=SimpleNamespace(_job_service=service)
        )
        tab.asked = []
        tab.told = []
        tab.answer = True

        def confirm(title, message):
            tab.asked.append((title, message))
            return tab.answer

        tab._confirm = confirm  # never a live dialog
        tab._notify = lambda title, message: tab.told.append((title, message))
        tabs.append(tab)
        return tab

    yield root, repo, make_tab
    for tab in tabs:
        if tab.winfo_exists():
            tab.destroy()
    root.update_idletasks()
    repo.close()


def finished_tab(workspace, tmp_path):
    """A saved ordinary sweep (eleven values x 2 images) whose three jobs completed, restored in a real tab."""
    root, repo, make_tab = workspace
    source, _ = planned(tmp_path, repo)
    source.run_plan()
    payload = source.export_resume_state()
    for index, item in enumerate(payload["plan"]):
        out = tmp_path / f"out{index}"
        out.mkdir()
        transition(repo, item["job_id"], JobStatus.COMPLETED, result_for(out))
    tab = make_tab(RepositoryService(repo))
    assert tab._restore_from_store_payload(payload)
    tab._persist_learning_session_state()  # the session the Library lists
    tab._refresh_summary()
    root.update_idletasks()
    return tab


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest() if path.exists() else ""


def images(tab):
    return [ref for variant in tab.learning_state.plan for ref in variant.image_refs]


def rate(tab, refs, rating=4):
    for ref in refs:
        tab.learning_controller.record_rating(
            ref, rating, "", {"context_flags": {}, "subscores": {}}
        )
    tab._refresh_summary()


def experiment_id(tab) -> str:
    return tab.learning_state.current_experiment.experiment_id


def test_outcome_line_follows_the_ratings_and_the_buttons_follow_the_outcome(workspace, tmp_path):
    root, _repo, _make = workspace
    tab = finished_tab(workspace, tmp_path)
    refs = images(tab)
    assert len(refs) == 22  # the recovery fixture plans eleven values of two images
    assert tab._last_outcome.code == eo.OUTCOME_AWAITING_RATINGS
    assert "Awaiting ratings (3 more needed)" in tab._outcome_var.get()
    assert str(tab.close_experiment_button.cget("state")) == "normal"
    assert str(tab.reopen_experiment_button.cget("state")) == "disabled"

    rate(tab, refs[:1])
    assert "Awaiting ratings (2 more needed)" in tab._outcome_var.get()
    rate(tab, [refs[2], refs[4]])
    assert tab._last_outcome.code == eo.OUTCOME_SUPPORTED
    assert "Finding supported" in tab._outcome_var.get()


def test_close_with_unrated_images_is_confirmed_recorded_and_reopened_without_touching_evidence(
    workspace, tmp_path
):
    root, repo, _make = workspace
    tab = finished_tab(workspace, tmp_path)
    refs = images(tab)
    rate(tab, refs[:1])
    session = tmp_path / "experiments" / experiment_id(tab) / "session.json"
    watched = {"ratings": tmp_path / "ratings.jsonl", "jobs": tmp_path / "jobs.sqlite3"}
    before = {name: sha(path) for name, path in watched.items()}
    plan_before = json.loads(session.read_text("utf-8"))["plan"]
    queued_before = len(repo.list_job_models())

    tab.answer = False
    tab.close_experiment_button.invoke()
    assert tab.asked and "still unrated" in tab.asked[-1][1]
    assert (
        eo.closure_of(json.loads(session.read_text("utf-8"))) is None
    )  # declined: nothing written

    tab.answer = True
    tab.close_experiment_button.invoke()
    root.update_idletasks()
    stored = json.loads(session.read_text("utf-8"))
    assert eo.closure_of(stored)["outcome_code"] == eo.OUTCOME_INSUFFICIENT_EVIDENCE
    assert stored["plan"] == plan_before  # job associations and variants untouched
    assert {
        name: sha(path) for name, path in watched.items()
    } == before  # ratings and jobs byte-identical
    assert len(repo.list_job_models()) == queued_before
    assert "Insufficient evidence, closed by operator" in tab._outcome_var.get()
    assert str(tab.close_experiment_button.cget("state")) == "disabled"
    assert str(tab.reopen_experiment_button.cget("state")) == "normal"

    # A later rating changes the evidence: the outcome is re-derived and says so.
    rate(tab, [refs[2], refs[4]])
    assert "changed since closure" in tab._outcome_var.get()
    assert "Finding supported" in tab._outcome_var.get()

    tab.reopen_experiment_button.invoke()
    assert "closure" not in json.loads(session.read_text("utf-8"))
    assert "closed by operator" not in tab._outcome_var.get()
    assert not tab.told


def test_close_is_refused_while_jobs_are_still_running_and_survives_a_restart(workspace, tmp_path):
    root, repo, make_tab = workspace
    tab = finished_tab(workspace, tmp_path)
    tab.close_experiment_button.invoke()
    saved = json.loads(
        (tmp_path / "experiments" / experiment_id(tab) / "session.json").read_text("utf-8")
    )
    assert eo.closure_of(saved) is not None

    # A fresh tab on the same store (an app restart) shows the closure for the restored experiment.
    again = make_tab(RepositoryService(repo))
    assert again._restore_from_store_payload(
        again.experiment_store.load_session(experiment_id(tab)), experiment_id=experiment_id(tab)
    )
    again._refresh_summary()
    assert "closed by operator" in again._outcome_var.get()
    assert str(again.reopen_experiment_button.cget("state")) == "normal"

    # Mid-run payloads cannot be closed: the reason is shown and nothing is written.
    running = json.loads(json.dumps(saved))
    running.pop("closure")
    running["plan"][0]["status"] = "running"
    assert not again.close_experiment_by_id(experiment_id(tab), running, {})
    assert again.told and "not finished" in again.told[-1][1]


def test_library_filters_open_and_closed_and_closes_and_reopens_the_selected_experiment(
    workspace, tmp_path
):
    root, repo, _make = workspace
    tab = finished_tab(workspace, tmp_path)
    rate(tab, images(tab))  # every image rated: the outcome is concluded
    target = experiment_id(tab)

    tab._on_open_experiment_library()
    root.update()
    tree = tab.library_tree
    assert tab.library_filter_var.get() == "Open"
    assert tree.exists(target)

    tree.selection_set(target)
    tab.library_close_button.invoke()
    root.update()
    assert "Close this experiment" in tab.asked[-1][1]  # nothing unrated: the plain prompt
    assert not tree.exists(target)  # hidden under Open once closed
    tab.library_filter_var.set("Closed")
    tab.library_filter_box.event_generate("<<ComboboxSelected>>")
    root.update()
    assert tree.exists(target)
    tree.selection_set(target)
    tab.library_reopen_button.invoke()
    root.update()
    assert not tree.exists(target)
    tab.library_filter_var.set("All")
    tab.library_filter_box.event_generate("<<ComboboxSelected>>")
    root.update()
    assert tree.exists(target)
    assert eo.closure_of(tab.experiment_store.load_session(target)) is None
    tab.library_window.destroy()


def test_library_outcome_column_is_derived_off_the_gui_thread(workspace, tmp_path):
    root, _repo, _make = workspace
    tab = finished_tab(workspace, tmp_path)
    tab._on_open_experiment_library()
    target = experiment_id(tab)
    for _ in range(100):
        root.update()
        if tab.library_tree.set(target, "outcome") != "Checking...":
            break
        root.after(20)
    assert tab.library_tree.set(target, "outcome").startswith("Awaiting ratings")
    tab.library_window.destroy()
