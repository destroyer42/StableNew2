from __future__ import annotations

import pytest

import tkinter as tk

from src.gui.app_state_v2 import AppStateV2
from src.gui.job_history_panel_v2 import JobHistoryPanelV2
from src.queue.job_history_store import JobHistoryEntry, JobStatus


class DummyController:
    def __init__(self) -> None:
        self.refresh_calls = 0

    def refresh_job_history(self) -> None:
        self.refresh_calls += 1


def _make_entry(job_id: str) -> JobHistoryEntry:
    timestamp = "2025-01-01T12:00:00"
    return JobHistoryEntry(
        job_id=job_id,
        created_at=timestamp,
        status=JobStatus.COMPLETED,
        payload_summary="PackA",
        completed_at=timestamp,
        started_at=timestamp,
    )


@pytest.mark.gui
def test_job_history_panel_updates_and_opens_folder(tk_root, tmp_path, monkeypatch) -> None:
    controller = DummyController()
    app_state = AppStateV2()
    open_calls: list[str] = []

    def fake_opener(path: str) -> None:
        open_calls.append(path)

    panel = JobHistoryPanelV2(
        tk_root,
        controller=controller,
        app_state=app_state,
        folder_opener=fake_opener,
    )

    entry = _make_entry("job123")
    app_state.set_history_items([entry])
    tk_root.update_idletasks()

    children = panel.history_tree.get_children()
    assert children, "Panel should have history entries"

    panel.history_tree.selection_set(children[0])
    panel.history_tree.event_generate("<<TreeviewSelect>>")
    panel.open_btn.invoke()

    assert open_calls, "Open folder should be invoked for selected job"
    assert controller.refresh_calls == 0
    panel.refresh_btn.invoke()
    assert controller.refresh_calls == 1
