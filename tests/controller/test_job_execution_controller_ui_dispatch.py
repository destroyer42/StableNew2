"""
Test: JobExecutionController and AppController UI dispatcher thread-safety
Ensures all queue/job-status-driven UI updates are dispatched on the main thread.
"""

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


@pytest.mark.parametrize(
    "status", [JobStatus.QUEUED, JobStatus.RUNNING, JobStatus.COMPLETED, JobStatus.FAILED]
)
def test_on_job_status_for_panels_dispatches_to_main_thread(status):
    mw = DummyMainWindow()
    controller = AppController(main_window=mw)
    job = MagicMock()
    job.job_id = "job-123"
    job.unified_summary = MagicMock()
    # Patch _run_in_gui_thread to track calls
    called = []

    def fake_dispatch(fn):
        called.append(fn)
        # Simulate immediate call for test
        fn()

    controller._run_in_gui_thread = fake_dispatch
    # Should always schedule UI update via dispatcher
    controller._on_job_status_for_panels(job, status)
    assert called, "UI dispatcher was not called"
    # Should update queue/history panels only via dispatcher
    # (panel methods may or may not be called depending on status)


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
