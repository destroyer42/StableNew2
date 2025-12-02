import tkinter as tk
import pytest
from tkinter import ttk

from src.gui.job_history_panel_v2 import JobHistoryPanelV2
from src.controller.job_history_service import JobViewModel
from src.queue.job_model import JobStatus


def _vm(job_id: str, status: JobStatus, *, payload: str = "", active: bool = False):
    return JobViewModel(
        job_id=job_id,
        status=status,
        created_at="2025-11-22T00:00:00",
        started_at=None,
        completed_at="2025-11-22T01:00:00",
        payload_summary=payload or job_id,
        is_active=active,
        last_error=None,
    )


def test_job_history_panel_renders_rows(tk_root: tk.Tk):
    class FakeService:
        def __init__(self):
            self.active_calls = 0
            self.recent_calls = 0
            self.cancelled = []
            self.retried = []

        def list_active_jobs(self):
            self.active_calls += 1
            return [_vm("job-active", JobStatus.RUNNING, active=True)]

        def list_recent_jobs(self, limit=50):
            self.recent_calls += 1
            return [_vm("job-done", JobStatus.COMPLETED, payload="payload summary")]

        def cancel_job(self, job_id: str):
            self.cancelled.append(job_id)

        def retry_job(self, job_id: str):
            self.retried.append(job_id)
            return "new-id"

    svc = FakeService()
    panel = JobHistoryPanelV2(tk_root, job_history_service=svc)

    assert len(panel.active_tree.get_children()) == 1
    assert len(panel.recent_tree.get_children()) == 1

    # select active job and cancel
    sel = panel.active_tree.get_children()[0]
    panel.active_tree.selection_set(sel)
    panel._on_select_active()
    panel.cancel_btn.invoke()
    assert "job-active" in svc.cancelled

    # select recent job and retry
    sel_recent = panel.recent_tree.get_children()[0]
    panel.recent_tree.selection_set(sel_recent)
    panel._on_select_recent()
    panel.retry_btn.invoke()
    assert "job-done" in svc.retried

    panel.refresh_btn.invoke()
    assert svc.active_calls >= 2
    assert svc.recent_calls >= 2


def test_job_history_panel_empty_states(tk_root: tk.Tk):
    class EmptyService:
        def list_active_jobs(self):
            return []

        def list_recent_jobs(self, limit=50):
            return []

    panel = JobHistoryPanelV2(tk_root, job_history_service=EmptyService())

    assert len(panel.active_tree.get_children()) == 0
    assert len(panel.recent_tree.get_children()) == 0

    active_labels = [
        c for c in panel.active_frame.winfo_children() if isinstance(c, ttk.Label)
    ]
    recent_labels = [
        c for c in panel.recent_frame.winfo_children() if isinstance(c, ttk.Label)
    ]
    assert any("No active" in lbl.cget("text") for lbl in active_labels)
    assert any("No recent" in lbl.cget("text") for lbl in recent_labels)


def test_app_layout_creates_job_history_panel(gui_app_factory):
    class FakeService:
        def list_active_jobs(self):
            return []

        def list_recent_jobs(self, limit=50):
            return []

    app = gui_app_factory()
    app.job_history_service = FakeService()
    app._layout_v2.build_layout(app.root)

    assert hasattr(app, "job_history_panel_v2")
    assert app.job_history_panel_v2._service is app.job_history_service
