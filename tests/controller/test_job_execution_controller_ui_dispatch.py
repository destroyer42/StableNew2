"""
Test: JobExecutionController and AppController UI dispatcher thread-safety
Ensures queue/job-status-driven callbacks request state-driven projections.
"""

from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

from src.controller.app_controller import AppController
from src.controller.job_execution_controller import JobStatus


class DummyMainWindow:
    def __init__(self):
        self.root = MagicMock()
        self.run_in_main_thread = MagicMock()
        self.queue_panel = MagicMock()
        self.history_panel = MagicMock()
        self.app_state = MagicMock()


@pytest.mark.parametrize("status", [JobStatus.QUEUED, JobStatus.RUNNING, JobStatus.COMPLETED, JobStatus.FAILED])
def test_on_job_status_for_panels_requests_projection_refresh(status):
    mw = DummyMainWindow()
    controller = AppController(main_window=mw)
    job = MagicMock()
    job.job_id = "job-123"
    job.unified_summary = MagicMock()
    calls = {"queue": 0, "history": 0}
    controller._runtime_projection_coordinator = SimpleNamespace(
        publish_queue_refresh=lambda: calls.__setitem__("queue", calls["queue"] + 1),
        publish_history_refresh=lambda **_: calls.__setitem__("history", calls["history"] + 1),
    )
    controller._on_job_status_for_panels(job, status)
    assert calls["queue"] == 1
    if status in {JobStatus.COMPLETED, JobStatus.FAILED}:
        assert calls["history"] == 1
    else:
        assert calls["history"] == 0


def test_run_in_gui_thread_prefers_main_window_dispatch():
    mw = DummyMainWindow()
    controller = AppController(main_window=mw)
    called = []

    def fn():
        called.append("ran")

    mw.run_in_main_thread = lambda cb: cb()
    controller._run_in_gui_thread(fn)
    assert called == ["ran"]


def test_run_in_gui_thread_falls_back_to_root_after():
    mw = DummyMainWindow()
    controller = AppController(main_window=mw)
    called = []

    def fn():
        called.append("ran")

    mw.run_in_main_thread = None
    mw.root.after = lambda delay, cb: cb()
    controller._run_in_gui_thread(fn)
    assert called == ["ran"]


def test_run_in_gui_thread_direct_call_if_no_dispatcher():
    mw = DummyMainWindow()
    controller = AppController(main_window=mw)
    called = []

    def fn():
        called.append("ran")

    mw.run_in_main_thread = None
    mw.root = None
    controller._run_in_gui_thread(fn)
    assert called == ["ran"]
