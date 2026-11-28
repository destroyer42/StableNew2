"""QUEUE-MULTI: multi-select Remove and a Clear All that runs off the Tk thread."""

from __future__ import annotations

import queue
import threading
import time
import tkinter as tk
from types import SimpleNamespace
from typing import Any

import pytest

from src.controller.app_controller import AppController
from src.controller.app_controller_services.background_task_coordinator import (
    BackgroundTaskCoordinator,
)
from src.gui.panels_v2.queue_panel_v2 import QueuePanelV2
from src.queue.job_queue import RemoveManyOutcome


class _Controller:
    """The panel's boundary: the batch starter records its call and reports back when the test says so."""

    def __init__(self) -> None:
        self.calls: list[Any] = []
        self.on_done: Any = None
        self.start_result = True

    def on_queue_remove_job_v2(self, job_id: str) -> bool:
        self.calls.append(("remove", job_id))
        return True

    def on_queue_clear_v2(self) -> int:  # the legacy synchronous path must stay unused
        raise AssertionError("Clear All must use the worker path")

    def on_queue_remove_jobs_v2(self, job_ids, *, reason=None, on_done=None) -> bool:
        self.calls.append(("remove_many", None if job_ids is None else list(job_ids)))
        self.on_done = on_done
        return self.start_result

    def move_queue_job_up(self, job_id: str) -> bool:
        return True

    move_queue_job_down = move_queue_job_to_front = move_queue_job_to_back = move_queue_job_up


def _job(job_id: str, status: str = "QUEUED") -> SimpleNamespace:
    return SimpleNamespace(job_id=job_id, status=status, get_display_summary=lambda: job_id)


def _panel(tk_root, jobs, controller=None):
    controller = controller or _Controller()
    panel = QueuePanelV2(tk_root, controller=controller, app_state=None)
    messages: list[tuple[str, str]] = []
    panel._emit_status_message = lambda message, level="info": messages.append((message, level))
    panel.update_jobs(jobs)
    return panel, controller, messages


def _select(panel: QueuePanelV2, *indices: int) -> None:
    panel.job_listbox.selection_clear(0, tk.END)
    for index in indices:
        panel.job_listbox.selection_set(index)
    panel._update_button_states()


def _disabled(button) -> bool:
    return bool(button.instate(["disabled"]))


def test_listbox_allows_extended_selection(tk_root) -> None:
    panel, _, _ = _panel(tk_root, [_job("a")])
    assert str(panel.job_listbox.cget("selectmode")) == tk.EXTENDED
    panel.destroy()


def test_remove_label_and_reorder_buttons_follow_the_selection(tk_root) -> None:
    jobs = [_job("a"), _job("b"), _job("c", "RUNNING"), _job("d"), _job("e")]
    panel, _, _ = _panel(tk_root, jobs)

    _select(panel, 3)
    assert panel.remove_button.cget("text") == "Remove"
    assert not _disabled(panel.remove_button)
    assert not _disabled(panel.move_up_button)

    _select(panel, 1, 2, 3)  # two queued rows and the running one
    assert panel.remove_button.cget("text") == "Remove selected (2)"
    assert not _disabled(panel.remove_button)
    for button in (
        panel.move_to_front_button,
        panel.move_up_button,
        panel.move_down_button,
        panel.move_to_back_button,
    ):
        assert _disabled(button)

    _select(panel, 2)  # a running row alone cannot be removed
    assert panel.remove_button.cget("text") == "Remove"
    assert _disabled(panel.remove_button)

    _select(panel)
    assert _disabled(panel.remove_button)
    panel.destroy()


def test_remove_selected_sends_only_queued_ids_disables_buttons_then_reports(tk_root) -> None:
    jobs = [_job("a"), _job("b", "RUNNING"), _job("c"), _job("d")]
    panel, controller, messages = _panel(tk_root, jobs)
    _select(panel, 0, 1, 2)

    panel._on_remove()

    assert controller.calls == [("remove_many", ["a", "c"])]
    assert messages[-1][0].startswith("Removing 2 jobs")
    assert _disabled(panel.remove_button) and _disabled(panel.clear_button)

    controller.on_done(RemoveManyOutcome(removed=("a", "c")))

    assert messages[-1] == ("Removed 2 jobs; 1 running (must be cancelled)", "info")
    assert not _disabled(panel.clear_button)
    panel.destroy()


def test_a_job_that_started_meanwhile_is_reported_as_running(tk_root) -> None:
    panel, controller, messages = _panel(tk_root, [_job("a"), _job("b"), _job("c")])
    _select(panel, 0, 1, 2)
    panel._on_remove()

    controller.on_done(RemoveManyOutcome(removed=("b", "c"), running=("a",)))

    assert messages[-1][0] == "Removed 2 jobs; 1 running (must be cancelled)"
    panel.destroy()


def test_a_selection_of_running_rows_only_is_refused_with_a_note(tk_root) -> None:
    panel, controller, messages = _panel(tk_root, [_job("a", "RUNNING"), _job("b", "RUNNING")])
    _select(panel, 0, 1)

    panel._on_remove()

    assert controller.calls == []
    assert messages[-1] == ("Running jobs must be cancelled, not removed", "warning")
    panel.destroy()


def test_failed_removal_re_enables_the_buttons_and_says_so(tk_root) -> None:
    panel, controller, messages = _panel(tk_root, [_job("a"), _job("b")])
    _select(panel, 0, 1)
    panel._on_remove()

    controller.on_done(None)

    assert messages[-1] == ("Queued jobs could not be removed", "warning")
    assert not _disabled(panel.clear_button)
    panel.destroy()


def test_a_worker_that_cannot_start_leaves_the_panel_usable(tk_root) -> None:
    controller = _Controller()
    controller.start_result = False
    panel, _, messages = _panel(tk_root, [_job("a"), _job("b")], controller)
    _select(panel, 0, 1)

    panel._on_remove()

    assert messages[-1][1] == "warning"
    assert not _disabled(panel.clear_button)
    assert panel._removal_in_progress is False
    panel.destroy()


def test_clear_all_runs_on_the_worker_and_blocks_a_second_click(tk_root) -> None:
    panel, controller, messages = _panel(tk_root, [_job("a"), _job("b", "RUNNING"), _job("c")])

    assert panel._on_clear() == 0  # the result arrives through the message, not the return value

    assert controller.calls == [("remove_many", None)]
    assert messages[-1][0] == "Removing 2 jobs…"
    assert _disabled(panel.clear_button) and _disabled(panel.remove_button)
    panel._on_clear()
    assert controller.calls == [("remove_many", None)]  # not started twice

    controller.on_done(RemoveManyOutcome(removed=("a", "c")))
    assert messages[-1][0] == "Removed 2 jobs"
    panel.destroy()


def test_a_multi_selection_survives_a_list_refresh(tk_root) -> None:
    jobs = [_job(name) for name in "abcde"]
    panel, _, _ = _panel(tk_root, jobs)
    _select(panel, 1, 3)

    refreshed = [_job("a"), _job("b"), _job("c", "RUNNING"), _job("d"), _job("e")]
    panel.update_jobs(refreshed)

    assert panel._get_selected_indices() == [1, 3]
    assert panel.remove_button.cget("text") == "Remove selected (2)"
    panel.destroy()


# ----------------------------------------------------------------- the controller's worker path


def _controller_stub(tk_root, remove_queued_jobs):
    log: list[str] = []
    ui_thread = threading.get_ident()

    def dispatch(fn):
        # What AppController._ui_dispatch does for a worker thread: hand it to the Tk thread (drained by the pump).
        _UI_QUEUE.put(fn)

    stub = SimpleNamespace(
        job_service=SimpleNamespace(
            job_queue=SimpleNamespace(remove_many=remove_queued_jobs, list_jobs=lambda status: [])
        ),
        _background_tasks=BackgroundTaskCoordinator(dispatcher=dispatch),
        _refresh_app_state_queue=lambda: log.append(
            ("refresh", threading.get_ident() == ui_thread)
        ),
        _save_queue_state=lambda: log.append(("save", threading.get_ident() == ui_thread)),
        _append_log=log.append,
    )
    return stub, log, ui_thread


_UI_QUEUE: queue.Queue = queue.Queue()


def _pump_until(tk_root, predicate, timeout: float = 5.0) -> bool:
    end = time.monotonic() + timeout
    while time.monotonic() < end:
        tk_root.update()
        while True:
            try:
                _UI_QUEUE.get_nowait()()
            except queue.Empty:
                break
        if predicate():
            return True
        time.sleep(0.005)
    return False


def test_removal_runs_off_the_tk_thread_and_does_not_block_it(tk_root) -> None:
    release = threading.Event()
    worked_on: list[int] = []

    def slow_remove(ids, reason):
        worked_on.append(threading.get_ident())
        assert release.wait(5.0)
        return RemoveManyOutcome(removed=tuple(ids or ()))

    stub, log, ui_thread = _controller_stub(tk_root, slow_remove)
    done: list[tuple[Any, bool]] = []

    started = time.perf_counter()
    ok = AppController.on_queue_remove_jobs_v2(
        stub,
        ["a", "b"],
        on_done=lambda outcome: done.append((outcome, threading.get_ident() == ui_thread)),
    )
    returned_in = time.perf_counter() - started

    assert ok is True
    assert returned_in < 0.5  # the call only starts the worker
    ticks = []
    assert _pump_until(
        tk_root, lambda: ticks.append(1) or len(ticks) > 20, 2.0
    )  # Tk keeps turning meanwhile
    assert done == []
    release.set()
    assert _pump_until(tk_root, lambda: bool(done))

    assert worked_on and worked_on[0] != ui_thread
    outcome, on_ui = done[0]
    assert outcome.removed == ("a", "b") and on_ui
    assert ("refresh", True) in log and ("save", True) in log


def test_a_failing_removal_reports_none_to_the_panel(tk_root) -> None:
    def boom(ids, reason):
        raise RuntimeError("database is locked")

    stub, log, _ = _controller_stub(tk_root, boom)
    done: list[Any] = []

    assert AppController.on_queue_remove_jobs_v2(stub, None, on_done=done.append) is True
    assert _pump_until(tk_root, lambda: bool(done))

    assert done == [None]
    assert any("database is locked" in str(entry) for entry in log if isinstance(entry, str))


def test_no_job_service_means_no_worker(tk_root) -> None:
    stub, _, _ = _controller_stub(tk_root, lambda ids, reason: None)
    stub.job_service = None
    assert AppController.on_queue_remove_jobs_v2(stub, ["a"]) is False


@pytest.mark.parametrize(
    "ids,expected_reason", [(None, "queue cleared"), (["a"], "removed from queue")]
)
def test_reason_defaults_follow_clear_versus_remove(tk_root, ids, expected_reason) -> None:
    seen: list[str] = []

    def remove(job_ids, reason):
        seen.append(reason)
        return RemoveManyOutcome()

    stub, _, _ = _controller_stub(tk_root, remove)
    done: list[Any] = []
    AppController.on_queue_remove_jobs_v2(stub, ids, on_done=done.append)
    assert _pump_until(tk_root, lambda: bool(done))
    assert seen == [expected_reason]
