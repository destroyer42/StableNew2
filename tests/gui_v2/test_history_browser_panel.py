"""The history browser: real repository, real Tk (skipped without a display), no network or GPU."""

from __future__ import annotations

import time
import tkinter as tk
from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace

import pytest

from src.gui.history_browser_panel_v2 import HistoryBrowserPanelV2, resolve_history_search
from src.gui.job_history_panel_v2 import JobHistoryPanelV2
from src.pipeline.cli_njr_builder import build_cli_njr
from src.queue.job_model import Job
from src.queue.job_repository import JobRepository


def _job(job_id: str, prompt: str) -> Job:
    record = build_cli_njr(
        prompt=prompt,
        batch_size=1,
        run_name=job_id,
        config={
            "txt2img": {
                "model": "m.safetensors",
                "steps": 4,
                "cfg_scale": 5.0,
                "width": 64,
                "height": 64,
            }
        },
    )
    record = replace(record, job_id=job_id)
    job = Job(job_id=job_id, snapshot={"normalized_job": record.to_dict()})
    job._normalized_record = record  # type: ignore[attr-defined]
    return job


@pytest.fixture
def repository(tmp_path: Path) -> JobRepository:
    repo = JobRepository(tmp_path / "jobs.sqlite3")
    for index in range(7):
        job_id = f"job-{index}"
        repo.record_job_submission(_job(job_id, "dragon" if index % 2 else "harbor"))
        with repo.transaction() as connection:
            connection.execute(
                "UPDATE jobs SET created_at = ?, status = 'completed' WHERE job_id = ?",
                (f"2026-10-0{index + 1}T10:00:00", job_id),
            )
    return repo


class _Controller:
    def __init__(self, repo: JobRepository) -> None:
        self.job_service = SimpleNamespace(history_store=repo)
        self.replayed: list[str] = []

    def on_replay_history_job_v2(self, job_id: str) -> bool:
        self.replayed.append(job_id)
        return True

    def send_history_job_image_to_svd(self, job_id: str) -> None:  # present, must not be offered
        raise AssertionError("not offered in the browser")


def _settle(root: tk.Tk, panel: HistoryBrowserPanelV2) -> None:
    deadline = time.monotonic() + 5
    while time.monotonic() < deadline:
        root.update()
        if panel._pending is None and panel.summary_var.get() != "Searching...":
            return
        time.sleep(0.01)
    raise AssertionError("search did not finish")


def _shown_ids(panel: HistoryBrowserPanelV2) -> list[str]:
    return [entry.job_id for entry in panel._shown]


def _panel(tk_root: tk.Tk, repo: JobRepository) -> HistoryBrowserPanelV2:
    controller = _Controller(repo)
    search = resolve_history_search(controller)
    assert search is not None
    panel = HistoryBrowserPanelV2(tk_root, search=search, controller=controller)
    panel.pack()
    _settle(tk_root, panel)
    return panel


def test_opening_lists_the_newest_first(tk_root: tk.Tk, repository: JobRepository) -> None:
    panel = _panel(tk_root, repository)

    assert _shown_ids(panel) == [f"job-{i}" for i in range(6, -1, -1)]
    assert "End of history" in panel.summary_var.get()
    assert str(panel.more_btn.cget("state")) == "disabled"
    panel.destroy()


def test_text_filter_narrows_the_table(tk_root: tk.Tk, repository: JobRepository) -> None:
    panel = _panel(tk_root, repository)

    panel._text_var.set("DRAGON")
    panel._on_search()
    _settle(tk_root, panel)

    assert _shown_ids(panel) == ["job-5", "job-3", "job-1"]
    assert len(panel.history_tree.get_children()) == 3
    panel.destroy()


def test_no_match_says_so(tk_root: tk.Tk, repository: JobRepository) -> None:
    panel = _panel(tk_root, repository)

    panel._text_var.set("zebra")
    panel._on_search()
    _settle(tk_root, panel)

    assert panel._shown == []
    assert panel.empty_state_var.get() == "No jobs match."
    panel.destroy()


def test_bad_date_is_reported_and_runs_no_search(tk_root: tk.Tk, repository: JobRepository) -> None:
    panel = _panel(tk_root, repository)
    before = list(panel._shown)

    panel._from_var.set("soon")
    panel._on_search()

    assert "From must be a date" in panel.summary_var.get()
    assert panel._pending is None
    assert panel._shown == before
    panel.destroy()


def test_load_more_appends_the_next_page(tk_root: tk.Tk, repository: JobRepository) -> None:
    panel = _panel(tk_root, repository)
    panel.page_size = 3
    panel._on_search()
    _settle(tk_root, panel)
    assert _shown_ids(panel) == ["job-6", "job-5", "job-4"]
    assert str(panel.more_btn.cget("state")) == "normal"

    panel._on_load_more()
    _settle(tk_root, panel)
    assert _shown_ids(panel) == ["job-6", "job-5", "job-4", "job-3", "job-2", "job-1"]
    assert len(panel.history_tree.get_children()) == 6

    panel._on_load_more()
    _settle(tk_root, panel)
    assert len(_shown_ids(panel)) == 7
    assert str(panel.more_btn.cget("state")) == "disabled"
    panel.destroy()


def test_clear_resets_the_filters(tk_root: tk.Tk, repository: JobRepository) -> None:
    panel = _panel(tk_root, repository)
    panel._text_var.set("dragon")
    panel._status_var.set("Failed")
    panel._on_search()
    _settle(tk_root, panel)
    assert panel._shown == []

    panel._on_clear()
    _settle(tk_root, panel)

    assert panel._text_var.get() == ""
    assert panel._status_var.get() == "Any"
    assert len(panel._shown) == 7
    panel.destroy()


def test_handoff_actions_are_not_offered_but_replay_is(
    tk_root: tk.Tk, repository: JobRepository
) -> None:
    panel = _panel(tk_root, repository)
    entry = panel._shown[0]

    state = panel._history_action_state(entry)

    assert (state.svd, state.video_workflow, state.movie_clips, state.explain) == (
        False,
        False,
        False,
        False,
    )
    assert state.replay is True
    panel.destroy()


def test_a_failing_search_shows_the_reason_and_recovers(
    tk_root: tk.Tk, repository: JobRepository
) -> None:
    calls = {"n": 0}
    real = repository.query_history

    def flaky(query):  # type: ignore[no-untyped-def]
        calls["n"] += 1
        if calls["n"] == 2:
            raise RuntimeError("disk gone")
        return real(query)

    panel = HistoryBrowserPanelV2(tk_root, search=flaky, controller=_Controller(repository))
    panel.pack()
    _settle(tk_root, panel)
    panel._on_search()
    _settle(tk_root, panel)

    assert "disk gone" in panel.summary_var.get()
    assert str(panel.search_btn.cget("state")) == "normal"

    panel._on_search()
    _settle(tk_root, panel)
    assert len(panel._shown) == 7
    panel.destroy()


def test_destroy_stops_the_worker(tk_root: tk.Tk, repository: JobRepository) -> None:
    panel = _panel(tk_root, repository)

    panel.destroy()

    assert panel._executor is None


def test_resolve_history_search_needs_a_repository() -> None:
    assert resolve_history_search(None) is None
    assert (
        resolve_history_search(SimpleNamespace(job_service=SimpleNamespace(history_store=object())))
        is None
    )


def test_browse_all_opens_one_window(tk_root: tk.Tk, repository: JobRepository) -> None:
    panel = JobHistoryPanelV2(tk_root, controller=_Controller(repository), app_state=None)
    panel.pack()

    panel._on_browse_all()
    first = panel._browser_window
    panel._on_browse_all()

    assert first is not None
    assert panel._browser_window is first
    first.destroy()
    panel.destroy()
