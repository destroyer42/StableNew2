from types import SimpleNamespace

from src.controller.app_controller import AppController
from src.queue.job_model import JobStatus


class DummyMainWindow:
    def __init__(self) -> None:
        self.calls: list = []

    def run_in_main_thread(self, cb):
        self.calls.append(cb)
        cb()


class DummyQueuePanel:
    def __init__(self) -> None:
        self.upserts: list = []

    def upsert_job(self, dto):
        self.upserts.append(dto)

    def remove_job(self, job_id: str):
        return None


class DummyHistoryPanel:
    def __init__(self) -> None:
        self.history: list = []

    def append_history_item(self, item):
        self.history.append(item)


def _new_controller_with_main_window(main_window):
    controller = AppController.__new__(AppController)
    controller.main_window = main_window
    controller._append_log = lambda *_, **__: None
    controller._ui_dispatch = lambda fn: fn()
    return controller


def test_run_in_gui_thread_prefers_main_window_dispatch():
    mw = DummyMainWindow()
    controller = _new_controller_with_main_window(mw)

    called = {"ran": False}

    def task():
        called["ran"] = True

    controller._run_in_gui_thread(task)

    assert mw.calls, "run_in_main_thread should be used when available"
    assert called["ran"], "task should execute via dispatcher"


def test_on_job_status_for_panels_uses_gui_dispatcher():
    queue_panel = DummyQueuePanel()
    history_panel = DummyHistoryPanel()
    mw = SimpleNamespace(queue_panel=queue_panel, history_panel=history_panel)
    controller = _new_controller_with_main_window(mw)

    dispatch_calls = {"count": 0}

    def dispatch(fn):
        dispatch_calls["count"] += 1
        fn()

    controller._run_in_gui_thread = dispatch

    job = SimpleNamespace(job_id="job-1", unified_summary=None)
    controller._on_job_status_for_panels(job, JobStatus.RUNNING)

    assert dispatch_calls["count"] == 1, "status callbacks must be marshaled to GUI thread"
    assert queue_panel.upserts, "queue panel should receive an upsert via dispatched callback"
