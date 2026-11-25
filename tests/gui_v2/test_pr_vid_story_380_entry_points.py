"""PR-VID-STORY-380 B6: the Continue in Storyboard entry points (Job History and Recent outputs).

Recent outputs is the Video Workflow tab's Make Video result list.  Real Tk widgets with scripted windows; nothing is
queued and no GPU, runtime or network is used.  The route itself is covered in ``test_pr_vid_story_380_handoff``.
"""

from __future__ import annotations

import time
import tkinter as tk
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

from src.gui.app_state_v2 import AppStateV2
from src.gui.job_history_panel_v2 import JobHistoryPanelV2
from src.gui.views.video_workflow_recent_outputs_panel_v2 import WorkflowRecentOutputsPanel
from src.queue.job_history_store import JobHistoryEntry, JobStatus
from src.video.recent_video_outputs import RecentVideoOutput
from tests.helpers.motion_library_353 import write_clip

pytestmark = pytest.mark.gui


class _Tab:
    def __init__(self) -> None:
        self.started: list[tuple[str, str | None]] = []

    def start_from_job(self, job_id: str, *, status_message: str | None = None) -> None:
        self.started.append((job_id, status_message))


class _Notebook:
    selected: object = None

    def select(self, tab: object) -> None:
        self.selected = tab


class _Window:
    def __init__(self) -> None:
        self.storyboard_tab = _Tab()
        self.center_notebook = _Notebook()


def _pump_until(root: tk.Misc, predicate, timeout: float = 10.0) -> bool:
    end = time.monotonic() + timeout
    while time.monotonic() < end:
        root.update()
        if predicate():
            return True
        time.sleep(0.01)
    return False


def _select_recent(panel: WorkflowRecentOutputsPanel, root: tk.Misc, job_id: str) -> None:
    panel.request_refresh()
    assert _pump_until(root, lambda: bool(panel.tree.get_children()))
    panel.tree.selection_set(job_id)
    panel.tree.event_generate("<<TreeviewSelect>>")
    assert _pump_until(root, lambda: str(panel.open_button.cget("state")) == "normal")


def _output(tmp_path: Path, job_id: str) -> RecentVideoOutput:
    clip = write_clip(tmp_path / f"{job_id}.mp4", b"finished clip")
    return RecentVideoOutput(job_id=job_id, video_path=str(clip), completed_at=None)


# ------------------------------------------------------------------------------ Recent outputs


def test_recent_outputs_continue_in_storyboard_hands_over_the_selected_clip(tk_root, tmp_path):
    output = _output(tmp_path, "job-2")
    continued: list[RecentVideoOutput] = []
    panel = WorkflowRecentOutputsPanel(
        tk_root, list_outputs=lambda: [output], continue_in_storyboard=continued.append
    )
    try:
        assert str(panel.storyboard_button.cget("state")) == "disabled"  # nothing selected yet
        _select_recent(panel, tk_root, "job-2")
        assert str(panel.storyboard_button.cget("state")) == "normal"
        panel.storyboard_button.invoke()
        assert continued == [output]
    finally:
        panel.destroy()


def test_recent_outputs_without_a_storyboard_owner_never_enables_the_button(tk_root, tmp_path):
    output = _output(tmp_path, "job-x")
    panel = WorkflowRecentOutputsPanel(tk_root, list_outputs=lambda: [output])
    try:
        _select_recent(panel, tk_root, "job-x")
        assert str(panel.storyboard_button.cget("state")) == "disabled"
    finally:
        panel.destroy()


def test_recent_outputs_shows_a_refusal_in_its_status_line(tk_root, tmp_path):
    output = _output(tmp_path, "job-x")

    def refuse(_output: RecentVideoOutput) -> None:
        raise RuntimeError("Storyboard tab is not available")

    panel = WorkflowRecentOutputsPanel(
        tk_root, list_outputs=lambda: [output], continue_in_storyboard=refuse
    )
    try:
        _select_recent(panel, tk_root, "job-x")
        panel.storyboard_button.invoke()
        assert "Storyboard tab is not available" in panel.status_var.get()
    finally:
        panel.destroy()


# ------------------------------------------------------------------------------ Job History


def _history_entry(
    job_id: str, video: Path | None, *, status: JobStatus = JobStatus.COMPLETED
) -> JobHistoryEntry:
    stamp = "2025-01-01T12:00:00"
    result: dict[str, Any] = {}
    if video is not None:
        result = {
            "video_bundle": {
                "stage": "video_workflow",
                "primary_path": str(video),
                "output_paths": [str(video)],
            }
        }
    return JobHistoryEntry(
        job_id=job_id,
        created_at=stamp,
        status=status,
        payload_summary="a clip",
        completed_at=stamp,
        started_at=stamp,
        snapshot=None,
        result=result,
    )


@pytest.fixture
def history_env(tk_root, tmp_path):
    window = _Window()
    state = AppStateV2()
    panel = JobHistoryPanelV2(
        tk_root, controller=SimpleNamespace(main_window=window), app_state=state
    )
    yield SimpleNamespace(panel=panel, window=window, state=state, root=tk_root, tmp=tmp_path)
    panel.destroy()


def _show(env: SimpleNamespace, entry: JobHistoryEntry) -> None:
    env.state.set_history_items([entry])
    env.root.update_idletasks()
    [item] = env.panel.history_tree.get_children()
    env.panel.history_tree.selection_set(item)
    env.panel.history_tree.event_generate("<<TreeviewSelect>>")
    env.root.update()


def test_job_history_continues_a_completed_video_job_in_the_storyboard(history_env):
    env = history_env
    video = write_clip(env.tmp / "out" / "gen.mp4", b"generated")
    _show(env, _history_entry("job-1", video))
    assert env.panel.storyboard_btn.instate(["!disabled"])

    env.panel.storyboard_btn.invoke()

    assert env.window.storyboard_tab.started == [("job-1", None)]
    assert env.window.center_notebook.selected is env.window.storyboard_tab
    assert env.panel.replay_status_var.get() == ""


def test_job_history_offers_nothing_for_an_unfinished_or_videoless_job(history_env):
    env = history_env
    video = write_clip(env.tmp / "out" / "gen.mp4", b"generated")
    _show(env, _history_entry("job-failed", video, status=JobStatus.FAILED))
    assert env.panel.storyboard_btn.instate(["disabled"])
    _show(env, _history_entry("job-none", None))
    assert env.panel.storyboard_btn.instate(["disabled"])
    env.panel._on_continue_in_storyboard()  # even a direct call refuses, with a reason
    assert env.window.storyboard_tab.started == []
    assert "completed video job" in env.panel.replay_status_var.get()


def test_job_history_reports_a_missing_main_window(tk_root, tmp_path):
    state = AppStateV2()
    panel = JobHistoryPanelV2(tk_root, controller=SimpleNamespace(), app_state=state)
    try:
        video = write_clip(tmp_path / "out" / "gen.mp4", b"generated")
        state.set_history_items([_history_entry("job-1", video)])
        tk_root.update_idletasks()
        [item] = panel.history_tree.get_children()
        panel.history_tree.selection_set(item)
        panel.history_tree.event_generate("<<TreeviewSelect>>")
        tk_root.update()
        panel._on_continue_in_storyboard()
        assert "main window" in panel.replay_status_var.get()
    finally:
        panel.destroy()
