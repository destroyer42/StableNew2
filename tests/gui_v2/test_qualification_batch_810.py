"""Real Tk qualification selection, explicit confirmation and canonical synthetic admission."""

from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from src.controller.job_service import JobService
from src.gui.controllers.model_evidence_proposals import compile_qualification_state
from src.learning.execution_controller import LearningExecutionController
from src.learning.qualification_batch import QualificationBatchService
from src.queue.job_queue import JobQueue
from src.queue.job_repository import JobRepository
from tests.controller.test_job_service_unit import FakeRunner
from tests.gui_v2.test_evidence_autopilot_800 import pump
from tests.gui_v2.test_evidence_autopilot_800 import ui as original_ui


@pytest.fixture
def ui(tk_root, tmp_path, monkeypatch):
    yield from original_ui.__wrapped__(tk_root, tmp_path, monkeypatch)


def connect(ui, tmp_path):
    repo = JobRepository(tmp_path / "jobs.sqlite3")
    service = JobService(
        JobQueue(repository=repo), runner=FakeRunner(), require_normalized_records=True
    )
    execution = LearningExecutionController(ui.owner.learning_controller.learning_state, service)
    ui.owner.qualification_batch = QualificationBatchService(
        ui.owner.experiment_store, execution, compile_qualification_state
    )
    return SimpleNamespace(repo=repo, service=service, execution=execution)


def test_select_all_keyboard_busy_and_stale_never_select_blocked(ui):
    window = ui.window
    window._plan()
    pump(ui.root, window)
    dialog = window._proposal_dialog
    expected = {p.proposal_id for p in dialog.plan.proposals if p.runnable}
    dialog.checked.clear()
    dialog.select_all_button.invoke()
    assert set(dialog.selection_ids()) == expected
    dialog.tree.selection_set(next(iter(expected)))
    dialog.tree.focus_force()
    ui.root.update()
    dialog.tree.event_generate("<space>")
    ui.root.update()
    assert len(dialog.selection_ids()) == len(expected) - 1
    dialog.set_busy(True)
    assert str(dialog.queue_button.cget("state")) == "disabled"
    before = dialog.selection_ids()
    dialog._select_all()
    dialog._toggle()
    assert dialog.selection_ids() == before
    dialog.set_busy(False)
    dialog.refuse_stale()
    dialog._select_all()
    assert dialog.selection_ids() == ()
    assert str(dialog.select_all_button.cget("state")) == "disabled"
    ui.root.update_idletasks()
    for button in (dialog.select_all_button, dialog.queue_button, dialog.save_button):
        assert button.winfo_ismapped()
        assert (
            button.winfo_rooty() + button.winfo_height()
            <= dialog.winfo_rooty() + dialog.winfo_height()
        )


def test_queue_selected_asks_once_and_queues_every_experiment_without_visible_switch(
    ui, tmp_path, monkeypatch
):
    connection = connect(ui, tmp_path)
    try:
        window = ui.window
        window._qualification_prompt = (
            "a lighthouse at dusk",
            "blurry",
            {"prompt_source": "custom"},
        )
        window._plan()
        pump(ui.root, window)
        dialog = window._proposal_dialog
        ask = Mock(return_value=True)
        monkeypatch.setattr("src.gui.views.model_evidence_window.messagebox.askyesno", ask)
        before = ui.owner.learning_controller.learning_state.to_dict()
        dialog.queue_button.invoke()
        pump(ui.root, window)
        assert ask.call_count == 1
        assert "New images: 24" in ask.call_args.args[1]
        assert connection.repo.count() == 4, window.status.get()
        assert ui.owner.learning_controller.learning_state.to_dict() == before
        assert "Confirmed admissions: 2" in dialog.status.get()
        dialog.queue_button.invoke()
        pump(ui.root, window)
        assert ask.call_count == 1
        assert connection.repo.count() == 4
        assert "already has jobs" in dialog.status.get()
    finally:
        connection.execution.close()
        connection.repo.close()


def test_declined_confirmation_and_stale_confirmation_admit_nothing(ui, tmp_path, monkeypatch):
    connection = connect(ui, tmp_path)
    try:
        window = ui.window
        window._qualification_prompt = ("a lighthouse at dusk", "", {"prompt_source": "custom"})
        window._plan()
        pump(ui.root, window)
        dialog = window._proposal_dialog
        ask = Mock(return_value=False)
        monkeypatch.setattr("src.gui.views.model_evidence_window.messagebox.askyesno", ask)
        dialog.queue_button.invoke()
        pump(ui.root, window)
        assert ask.call_count == 1
        assert connection.repo.count() == 0
        assert "not confirmed" in dialog.status.get()

        def invalidate(*_args, **_kwargs):
            dialog.refuse_stale()
            return True

        monkeypatch.setattr("src.gui.views.model_evidence_window.messagebox.askyesno", invalidate)
        dialog.queue_button.invoke()
        pump(ui.root, window)
        assert connection.repo.count() == 0
    finally:
        connection.execution.close()
        connection.repo.close()
