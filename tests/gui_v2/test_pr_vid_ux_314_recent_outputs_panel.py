"""PR-VID-UX-314: the Recent outputs section of the Video Workflow tab.

Real Tk widgets, the production controller and a real SQLite repository; outputs are tiny placeholder
files and every shell launch is injected.  No GPU, Comfy process, model or network is involved.
"""

from __future__ import annotations

import threading
import time
import tkinter as tk
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

from src.gui.view_contracts.video_experiment_contract import BackgroundWorkRunner
from src.gui.view_contracts.video_recent_outputs_contract import EMPTY_TEXT, RecentOutputsSession
from src.gui.views.video_workflow_recent_outputs_panel_v2 import WorkflowRecentOutputsPanel
from src.gui.views.video_workflow_tab_frame_v2 import VideoWorkflowTabFrameV2
from src.queue.job_model import JobStatus
from src.utils.os_shell import ShellResult
from src.video.recent_video_outputs import RecentVideoOutput
from src.video.review_preview import PreviewResult
from tests.helpers.make_video_313 import TI2V_ID, make_app, make_image, make_window
from tests.helpers.video_review_211 import finish, new_repository, persist, video_result

pytestmark = pytest.mark.gui


def _pump_until(root: tk.Misc, predicate, timeout: float = 10.0) -> bool:
    end = time.monotonic() + timeout
    while time.monotonic() < end:
        root.update()
        if predicate():
            return True
        time.sleep(0.01)
    return False


def _output(tmp_path: Path, name: str, **extra: Any) -> RecentVideoOutput:
    path = tmp_path / f"{name}.mp4"
    path.write_bytes(b"clip")
    return RecentVideoOutput(
        job_id=f"job-{name}",
        video_path=str(path),
        completed_at=None,
        workflow_label="Wan2.2 TI2V-5B",
        frame_count=49,
        fps=24.0,
        bundle={"primary_path": str(path), "video_paths": [str(path)], "stage": "video_workflow"},
        **extra,
    )


class _ManualRunner(BackgroundWorkRunner):
    def __init__(self) -> None:
        self.queue: list[Any] = []
        super().__init__(
            spawn=lambda name, target: self.queue.append(target), dispatch=lambda fn: fn()
        )

    def run_next(self) -> None:
        self.queue.pop(0)()


# ------------------------------------------------------------------ session


def test_a_stale_refresh_is_dropped_and_the_selection_survives_a_refresh(tmp_path) -> None:
    first = [_output(tmp_path, "a"), _output(tmp_path, "b")]
    second = [_output(tmp_path, "b"), _output(tmp_path, "c")]
    batches = iter([first, second])
    runner = _ManualRunner()
    session = RecentOutputsSession(list_outputs=lambda: next(batches), runner=runner)

    session.refresh()
    session.refresh()  # supersedes the first
    runner.run_next()
    assert session.outputs == () and session.busy  # the first delivery changed nothing
    runner.run_next()
    assert [o.job_id for o in session.outputs] == ["job-b", "job-c"] and not session.busy
    assert session.selected_job_id == "job-b"

    session.select("job-c")
    batches = iter([second])
    session._list_outputs = lambda: next(batches)
    session.refresh()
    runner.run_next()
    assert session.selected_job_id == "job-c"  # still listed: still selected


def test_an_empty_or_failing_refresh_says_so(tmp_path) -> None:
    runner = _ManualRunner()
    session = RecentOutputsSession(list_outputs=lambda: [], runner=runner)
    session.refresh()
    runner.run_next()
    assert session.status == EMPTY_TEXT and session.selected is None
    assert not session.can_send_to_movie

    def broken() -> list[RecentVideoOutput]:
        raise OSError("database is locked")

    session = RecentOutputsSession(list_outputs=broken, runner=runner)
    session.refresh()
    runner.run_next()
    assert "database is locked" in session.status and session.outputs == ()


def test_open_reveal_and_movie_actions_report_inline(tmp_path) -> None:
    opened: list[str] = []
    revealed: list[str] = []
    sent: list[str] = []
    runner = _ManualRunner()
    outputs = [_output(tmp_path, "a")]
    session = RecentOutputsSession(
        list_outputs=lambda: outputs,
        runner=runner,
        open_path=lambda p: (opened.append(p), ShellResult(True))[1],
        reveal_path=lambda p: (revealed.append(p), ShellResult(True))[1],
        send_to_movie=lambda o: sent.append(o.job_id),
    )
    assert not session.open_selected().ok  # nothing selected yet
    session.refresh()
    runner.run_next()
    assert session.open_selected().ok and opened == [outputs[0].video_path]
    assert session.reveal_selected().ok and revealed == [outputs[0].video_path]
    assert session.send_selected_to_movie().ok and sent == ["job-a"]
    assert session.status == "Sent a.mp4 to Movie Clips."

    session._open_path = lambda p: ShellResult(False, "The file no longer exists: " + p)
    assert not session.open_selected().ok and "no longer exists" in session.status

    def refuse(_output: RecentVideoOutput) -> None:
        raise RuntimeError("Movie Clips tab is not available")

    session._send_to_movie = refuse
    assert not session.send_selected_to_movie().ok and "not available" in session.status


def test_a_closed_session_ignores_late_results(tmp_path) -> None:
    runner = _ManualRunner()
    session = RecentOutputsSession(list_outputs=lambda: [_output(tmp_path, "a")], runner=runner)
    session.refresh()
    session.close()
    runner.run_next()
    assert session.outputs == ()
    session.refresh()
    assert runner.queue == []


# ------------------------------------------------------------------ panel (real Tk)


def _decode_recorder(calls: list[tuple[str, int]]):
    def decode(path: str, cancel: threading.Event) -> PreviewResult:
        calls.append((path, threading.get_ident()))
        return PreviewResult(path=path, status="failed", message="stub decode: no frames")

    return decode


def test_the_panel_lists_rows_previews_the_selection_and_never_decodes_on_tk(
    tk_root, tmp_path, monkeypatch
) -> None:
    from src.gui.view_contracts import edit_work_runner

    monkeypatch.setattr(edit_work_runner, "coordinator_factory", edit_work_runner._tk_coordinator)
    outputs = [_output(tmp_path, "newest"), _output(tmp_path, "older")]
    calls: list[tuple[str, int]] = []
    tk_root.deiconify()  # hidden/unmapped inspectors deliberately do not decode
    panel = WorkflowRecentOutputsPanel(
        tk_root, list_outputs=lambda: outputs, decode=_decode_recorder(calls)
    )
    panel.pack()
    try:
        assert panel.tree.get_children() == ()  # nothing is read until a refresh is requested
        panel.request_refresh()
        assert _pump_until(tk_root, lambda: panel.session.loaded)
        assert panel.tree.get_children() == ("job-newest", "job-older")
        assert panel.tree.item("job-newest", "values")[3] == "newest.mp4"
        assert str(panel.open_button.cget("state")) == "normal"

        assert _pump_until(tk_root, lambda: bool(calls))
        assert calls[0][0] == outputs[0].video_path and calls[0][1] != threading.get_ident()

        panel.tree.selection_set("job-older")
        panel.tree.event_generate("<<TreeviewSelect>>")
        assert _pump_until(tk_root, lambda: len(calls) >= 2)
        assert calls[-1][0] == outputs[1].video_path
    finally:
        panel.destroy()


def test_the_panel_open_reveal_and_movie_buttons_use_the_selected_clip(tk_root, tmp_path) -> None:
    outputs = [_output(tmp_path, "one")]
    sent: list[str] = []
    panel = WorkflowRecentOutputsPanel(
        tk_root,
        list_outputs=lambda: outputs,
        send_to_movie=lambda o: sent.append(o.video_path),
        decode=_decode_recorder([]),
    )
    panel.pack()
    opened: list[str] = []
    revealed: list[str] = []
    panel.session._open_path = lambda p: (opened.append(p), ShellResult(True))[1]
    panel.session._reveal_path = lambda p: (revealed.append(p), ShellResult(True))[1]
    try:
        panel.request_refresh()
        assert _pump_until(tk_root, lambda: panel.session.loaded)
        panel.open_button.invoke()
        panel.reveal_button.invoke()
        panel.movie_button.invoke()
        assert opened == revealed == sent == [outputs[0].video_path]
        assert panel.status_var.get() == "Sent one.mp4 to Movie Clips."
    finally:
        panel.destroy()


def test_destroying_the_panel_during_a_refresh_is_safe(tk_root, tmp_path) -> None:
    started, release = threading.Event(), threading.Event()

    def slow() -> list[RecentVideoOutput]:
        started.set()
        release.wait(10)
        return [_output(tmp_path, "late")]

    panel = WorkflowRecentOutputsPanel(tk_root, list_outputs=slow, decode=_decode_recorder([]))
    panel.pack()
    session = panel.session
    panel.request_refresh()
    assert _pump_until(tk_root, started.is_set)
    panel.destroy()
    release.set()
    for _ in range(30):
        tk_root.update()
        time.sleep(0.01)
    assert session.outputs == ()  # the late result was dropped


# ------------------------------------------------------------------ the tab, end to end


def test_the_tab_reads_the_repository_only_when_shown_and_lists_a_finished_clip(
    tk_root, tmp_path
) -> None:
    repository = new_repository(tmp_path)
    app, controller, service = make_app(tmp_path, repository=repository)
    window = make_window(None)
    app.main_window = window
    source = make_image(tmp_path / "src.png")
    controller.submit_video_workflow_job(
        source_image_path=source,
        form_data={
            "workflow_id": TI2V_ID,
            "workflow_version": "1.2.0",
            "prompt": "a slow turn",
            "seed": "9",
            "source_lineage": {"source_job_id": "parent"},
        },
    )
    [job_id] = persist(repository, [service.submitted[-1]])
    clip = tmp_path / "output" / "done.mp4"
    clip.parent.mkdir(parents=True, exist_ok=True)
    clip.write_bytes(b"clip")
    result = video_result(clip)
    finish(repository, job_id, JobStatus.COMPLETED, result=result)

    reads: list[int] = []
    original = controller.list_recent_video_outputs
    controller.list_recent_video_outputs = lambda limit=12: (
        reads.append(threading.get_ident()),
        original(limit),
    )[1]

    tab = VideoWorkflowTabFrameV2(tk_root, app_controller=app, app_state=SimpleNamespace())
    window.video_workflow_tab = tab
    movie_bundles: list[dict[str, Any]] = []
    window.movie_clips_tab = SimpleNamespace(
        set_source_bundle=lambda bundle, status_message=None: movie_bundles.append(bundle)
    )
    try:
        for _ in range(10):
            tk_root.update()
        assert reads == []  # a hidden tab does not touch the repository

        tab._on_tab_shown()  # what Tk does when the tab is mapped
        panel = tab.recent_outputs_panel
        assert _pump_until(tk_root, lambda: panel.session.loaded)
        assert reads and reads[0] != threading.get_ident()  # read on a worker
        assert panel.tree.get_children() == (job_id,)
        values = panel.tree.item(job_id, "values")
        assert (
            values[1] == "Wan2.2 TI2V-5B Prompt-Directed I2V" and values[2] == "49 frames (~2.0 s)"
        )

        panel.movie_button.invoke()  # Send to Movie Clips hands over exactly the recorded bundle
        assert movie_bundles == [result["video_bundle"]]
        assert panel.status_var.get() == "Sent done.mp4 to Movie Clips."
    finally:
        tab.destroy()


def test_send_to_movie_without_a_movie_tab_reports_instead_of_failing_silently(
    tk_root, tmp_path
) -> None:
    app, controller, _service = make_app(tmp_path)
    app.main_window = SimpleNamespace(center_notebook=None)
    tab = VideoWorkflowTabFrameV2(tk_root, app_controller=app, app_state=SimpleNamespace())
    try:
        output = _output(tmp_path, "z")
        tab.recent_outputs_panel.session.outputs = (output,)
        tab.recent_outputs_panel.session.select(output.job_id)
        result = tab.recent_outputs_panel.session.send_selected_to_movie()
        assert not result.ok and "Movie Clips" in result.message
    finally:
        tab.destroy()
