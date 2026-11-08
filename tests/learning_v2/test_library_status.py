"""The Experiment Library reads saved open jobs by exact ID; it never saves, tracks, replays or retries."""

from __future__ import annotations

import copy
import json
import time
from types import SimpleNamespace

import pytest

from src.learning.library_status import LibraryStatus, has_open_jobs, library_status
from src.queue.job_model import JobStatus
from src.queue.job_repository import JobRepository
from tests.learning_v2.test_learning_recovery_260 import planned, result_for, transition


@pytest.fixture
def repo(tmp_path):
    repository = JobRepository(tmp_path / "jobs.sqlite3")
    yield repository
    repository.close()


def saved_queued(tmp_path, repository):
    """A session saved right after Run, while every variant was still queued."""
    controller, service = planned(tmp_path, repository)
    controller.run_plan()
    payload = json.loads(json.dumps(controller.export_resume_state()))
    assert {item["status"] for item in payload["plan"]} == {"queued"}
    return payload, [item["job_id"] for item in payload["plan"]], service


def test_a_session_saved_while_queued_shows_its_finished_jobs(tmp_path, repo):
    payload, ids, service = saved_queued(tmp_path, repo)
    for job_id in ids[:-1]:
        transition(repo, job_id, JobStatus.COMPLETED, result_for(tmp_path))
    transition(repo, ids[-1], JobStatus.FAILED, error="backend interrupted")
    before = copy.deepcopy(payload)
    submitted = len(service.calls)

    status = library_status(payload, repo)

    assert status.lifecycle == "Review Needed"  # no longer "Queued"
    assert f"{len(ids) - 1} completed" in status.note and "1 failed" in status.note
    assert "Saved as Queued" in status.note
    assert payload == before  # the saved session is never changed
    assert len(service.calls) == submitted  # nothing is resubmitted
    assert [repo.get_job_model(job_id).status for job_id in ids] == [JobStatus.COMPLETED] * (
        len(ids) - 1
    ) + [JobStatus.FAILED]


def test_all_failed_jobs_show_failed_and_still_running_jobs_stay_open(tmp_path, repo):
    payload, ids, _service = saved_queued(tmp_path, repo)
    for job_id in ids:
        transition(repo, job_id, JobStatus.FAILED, error="backend interrupted")
    assert library_status(payload, repo).lifecycle == "Failed"

    other, other_ids, _ = saved_queued(tmp_path / "second", repo)
    repo.transition_job(repo.get_job_model(other_ids[0]), JobStatus.RUNNING)
    assert library_status(other, repo).lifecycle == "Running"


def test_an_unavailable_repository_keeps_the_saved_status_and_says_so(tmp_path, repo):
    payload, _ids, _service = saved_queued(tmp_path, repo)
    for repository in (None, SimpleNamespace()):
        status = library_status(payload, repository)
        assert status.lifecycle == "Queued"
        assert "unavailable" in status.note


def test_a_conflicting_or_missing_identity_requires_attention_and_stays_visible(tmp_path, repo):
    payload, ids, _service = saved_queued(tmp_path, repo)
    transition(repo, ids[0], JobStatus.COMPLETED, result_for(tmp_path))
    conflicting = copy.deepcopy(payload)
    conflicting["plan"][0]["param_value"] = (
        99.0  # the saved plan no longer matches the immutable NJR
    )
    status = library_status(conflicting, repo)
    assert status.lifecycle == "Requires Attention"
    assert "could not be matched" in status.note

    missing = copy.deepcopy(payload)
    missing["plan"][1]["job_id"] = "job-that-was-never-recorded"
    assert library_status(missing, repo).lifecycle == "Requires Attention"


def test_a_failing_lookup_requires_attention_instead_of_raising(tmp_path, repo):
    payload, _ids, _service = saved_queued(tmp_path, repo)

    def broken(_job_id):
        raise OSError("database locked")

    status = library_status(payload, SimpleNamespace(get_job_model=broken))
    assert status.lifecycle == "Requires Attention"


def test_sessions_without_open_jobs_are_not_looked_up():
    finished = {"plan": [{"job_id": "j1", "status": "completed", "completed_images": 2}]}
    draft = {"plan": [{"job_id": "", "status": "pending"}]}
    assert not has_open_jobs(finished) and not has_open_jobs(draft)

    def never(_job_id):
        raise AssertionError("no lookup for a session with nothing open")

    repository = SimpleNamespace(get_job_model=never)
    assert library_status(finished, repository, saved_rating_count=2) == LibraryStatus("Complete")
    assert library_status(draft, repository) == LibraryStatus("Draft/Legacy Draft")


def test_the_library_window_updates_status_off_the_gui_thread(tmp_path, repo):
    from tkinter import ttk

    from src.gui.views.learning_tab_frame_v2 import LearningTabFrame
    from tests.gui_v2.tk_test_utils import get_shared_tk_root

    root = get_shared_tk_root()
    if root is None:
        pytest.skip("No display available for Tkinter tests")
    payload, ids, _service = saved_queued(tmp_path, repo)
    for job_id in ids:
        transition(repo, job_id, JobStatus.COMPLETED, result_for(tmp_path))
    tree = ttk.Treeview(root, columns=("status", "history"))
    tree.insert("", "end", iid="recovery", values=("Queued", "Checking job history..."))
    owner = SimpleNamespace(
        learning_controller=SimpleNamespace(execution_controller=SimpleNamespace(repository=repo))
    )
    try:
        LearningTabFrame._refresh_library_status(owner, tree, [("recovery", payload, 0)])  # type: ignore[arg-type]
        deadline = time.monotonic() + 10
        while tree.set("recovery", "status") == "Queued" and time.monotonic() < deadline:
            root.update()
            time.sleep(0.01)
        assert tree.set("recovery", "status") == "Review Needed"
        assert f"{len(ids)} completed" in tree.set("recovery", "history")
    finally:
        tree.destroy()
