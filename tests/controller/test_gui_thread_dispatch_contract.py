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
    controller._ui_thread_id = -1
    controller._runtime_projection_coordinator = SimpleNamespace(
        publish_queue_refresh=lambda: None,
        publish_history_refresh=lambda **_: None,
    )
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


def test_on_job_status_for_panels_requests_state_projection_refresh():
    mw = SimpleNamespace()
    controller = _new_controller_with_main_window(mw)
    calls = {"queue": 0, "history": 0}
    controller._runtime_projection_coordinator = SimpleNamespace(
        publish_queue_refresh=lambda: calls.__setitem__("queue", calls["queue"] + 1),
        publish_history_refresh=lambda **_: calls.__setitem__("history", calls["history"] + 1),
    )

    job = SimpleNamespace(job_id="job-1", unified_summary=None)
    controller._on_job_status_for_panels(job, JobStatus.RUNNING)
    controller._on_job_status_for_panels(job, JobStatus.COMPLETED)

    assert calls["queue"] == 2
    assert calls["history"] == 1
