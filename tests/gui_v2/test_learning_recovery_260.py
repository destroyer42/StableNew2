"""Real Tk restoration and immediate atomic persistence with a fake backend only."""

from __future__ import annotations

import copy
import json
import threading
from types import SimpleNamespace

import pytest

from src.controller.job_service import JobService
from src.gui.app_state_v2 import AppStateV2
from src.gui.views.learning_tab_frame_v2 import LearningTabFrame
from src.queue.job_model import JobStatus
from src.queue.job_queue import JobQueue
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
    assert root is not None, "PR-LEARN-RECOVERY-260 requires a real Tk restoration test"
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
    tabs = []

    def make_tab(service):
        tab = LearningTabFrame(
            root, app_state=AppStateV2(), pipeline_controller=SimpleNamespace(_job_service=service)
        )
        tabs.append(tab)
        return tab

    yield root, repo, ui_store, make_tab
    for tab in tabs:
        if tab.winfo_exists():
            tab.destroy()
    root.update_idletasks()
    repo.close()


def test_restore_to_visible_status_and_error_uses_real_tk(workspace, tmp_path):
    root, repo, store, make_tab = workspace
    controller, _ = planned(tmp_path, repo)
    controller.run_plan()
    payload = controller.export_resume_state()
    transition(repo, payload["plan"][0]["job_id"], JobStatus.COMPLETED, result_for(tmp_path))
    transition(
        repo, payload["plan"][1]["job_id"], JobStatus.FAILED, error="recorded backend failure"
    )
    service = RepositoryService(repo)
    tab = make_tab(service)
    assert tab._restore_from_store_payload(payload)
    tab._refresh_summary()
    root.update_idletasks()
    rows = [tab.plan_table.tree.item(item, "values") for item in tab.plan_table.tree.get_children()]
    assert rows[0][3] == "Completed"
    assert rows[0][4] == "2/2"
    assert rows[1][3] == "Failed"
    assert "recorded backend failure" in rows[1][6]
    assert "1 completed" in tab._summary_var.get()
    assert "1 failed" in tab._summary_var.get()
    assert "queued" in tab._summary_var.get()
    assert not service.calls
    assert store.load_state()["learning"]["session"]["plan"][0]["status"] == "completed"


@pytest.mark.parametrize("save_fails", [False, True])
def test_run_checkpoints_ids_immediately_and_surfaces_store_failure(
    workspace, tmp_path, monkeypatch, save_fails
):
    _root, repo, store, make_tab = workspace
    source, _ = planned(tmp_path, repo)
    service = RepositoryService(repo)
    tab = make_tab(service)
    tab.learning_controller.restore_resume_state(source.export_resume_state())
    if save_fails:
        monkeypatch.setattr(store, "save_state", lambda _state: False)
        with pytest.raises(RuntimeError, match="resume checkpoint failed"):
            tab.learning_controller.run_plan()
        tab._refresh_summary()
        assert "Resume save failed" in tab._summary_var.get()
        assert "do not retry" in tab._summary_var.get()
    else:
        tab.learning_controller.run_plan()
        saved = store.load_state()["learning"]
        path = tmp_path / "experiments" / saved["last_experiment_id"] / "session.json"
        persisted = json.loads(path.read_text(encoding="utf-8"))
        # The session envelope is owned by LearningExperimentStore.
        plan = persisted.get("payload", persisted).get("plan")
        assert [item["job_id"] for item in plan] == [r.job_id for r in service.calls[0]]
    before = copy.deepcopy(tab.learning_state.to_dict())
    tab.learning_controller.run_plan()
    assert tab.learning_state.to_dict() == before
    assert len(service.calls) == 1
    assert len(repo.list_job_models()) == len(tab.learning_state.plan)


def test_worker_completion_dispatches_to_tk_thread_and_destroyed_tab_is_inert(workspace, tmp_path):
    root, repo, _store, make_tab = workspace
    controller, _ = planned(tmp_path, repo)
    controller.run_plan()
    service = JobService(JobQueue(repository=repo))
    pending = []
    service.set_event_dispatcher(pending.append)
    tab = make_tab(service)
    tab.learning_controller.restore_resume_state(controller.export_resume_state())
    original_update = tab.plan_table.update_row_status
    seen_threads = []

    def update_status(*args):
        seen_threads.append(threading.get_ident())
        assert threading.current_thread() is threading.main_thread()
        original_update(*args)

    tab.plan_table.update_row_status = update_status
    job = transition(
        repo, tab.learning_state.plan[0].job_id, JobStatus.COMPLETED, result_for(tmp_path)
    )
    # Exercise the actual JobService dispatcher with a fake completed backend job.
    worker = threading.Thread(target=lambda: service._emit(JobService.EVENT_JOB_FINISHED, job))
    worker.start()
    worker.join(5)
    assert not worker.is_alive()
    assert not seen_threads
    pending.pop()()
    root.update_idletasks()
    assert seen_threads == [threading.get_ident()]
    assert tab.learning_state.plan[0].status == "completed"
    execution = tab.learning_controller.execution_controller
    tab.destroy()
    snapshot = copy.deepcopy(tab.learning_state.to_dict())
    service._emit(JobService.EVENT_JOB_FINISHED, job)
    pending.pop()()
    assert execution._closed is True
    assert tab.learning_state.to_dict() == snapshot
    assert len(seen_threads) == 1


def test_rejected_completion_repaints_and_checkpoints_safe_evidence_after_partial_ui_update(
    workspace, tmp_path
):
    root, repo, store, make_tab = workspace
    source, _ = planned(tmp_path, repo)
    source.run_plan()
    service = RepositoryService(repo)
    tab = make_tab(service)
    tab.learning_controller.restore_resume_state(source.export_resume_state())
    variant = tab.learning_state.plan[0]
    experiment = tab.learning_state.current_experiment

    def reject(partial, _result):
        tab.plan_table.update_row_status(0, "completed")
        partial.execution_metadata.update(controlled_evidence_valid=True, actual_all_seeds=[999])
        experiment.metadata["observed_seed_vector"] = [999]
        raise RuntimeError("evidence rejected after provisional update")

    tab.learning_controller.execution_controller.set_completion_callback(reject)
    job = transition(repo, variant.job_id, JobStatus.COMPLETED, result_for(tmp_path))
    service.finish(job)
    root.update_idletasks()
    values = tab.plan_table.tree.item(tab.plan_table.tree.get_children()[0], "values")
    assert values[3] == "Uncontrolled"
    assert "evidence rejected" in values[6]
    saved = store.load_state()["learning"]["session"]
    assert saved["plan"][0]["status"] == "uncontrolled"
    assert saved["plan"][0]["execution_metadata"]["controlled_evidence_valid"] is False
    assert saved["plan"][0]["execution_metadata"]["actual_all_seeds"] == []
    assert not saved["current_experiment"]["metadata"].get("observed_seed_vector")
    assert len(saved["plan"][0]["image_refs"]) == 2
    before = copy.deepcopy(tab.learning_state.to_dict())
    service.finish(job)
    assert tab.learning_state.to_dict() == before


def test_completion_save_warning_does_not_reclassify_valid_execution_evidence(
    workspace, tmp_path, monkeypatch
):
    _root, repo, store, make_tab = workspace
    source, _ = planned(tmp_path, repo)
    source.run_plan()
    service = RepositoryService(repo)
    tab = make_tab(service)
    tab.learning_controller.restore_resume_state(source.export_resume_state())
    monkeypatch.setattr(store, "save_state", lambda _payload: False)
    variant = tab.learning_state.plan[0]
    service.finish(transition(repo, variant.job_id, JobStatus.COMPLETED, result_for(tmp_path)))
    assert variant.status == "completed"
    assert variant.execution_metadata["controlled_evidence_valid"] is True
    assert variant.execution_metadata["actual_all_seeds"] == [42, 43]
    assert not variant.execution_metadata.get("reconciliation_error")
    assert tab.learning_state.current_experiment.metadata["resume_persistence_error"]
    tab._refresh_summary()
    assert "Resume save failed" in tab._summary_var.get()
