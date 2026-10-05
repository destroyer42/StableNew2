"""AppController UI-update debouncing (PR-HB-003), migrated from the former ``tests/gui`` surface.

Time and scheduling are injected: a recording scheduler stands in for ``_ui_dispatch_later`` (the Tk loop in
the real application) and a fake clock replaces ``time.monotonic``; nothing here sleeps.
"""

from __future__ import annotations

import logging
import time
from unittest.mock import MagicMock

import pytest

from src.controller.app_controller import AppController


class _Scheduler:
    """Records delayed UI work instead of running it; ``run_all`` plays the Tk loop."""

    def __init__(self) -> None:
        self.scheduled: list = []

    def __call__(self, delay_ms, fn) -> None:
        self.scheduled.append(fn)

    def run_all(self) -> None:
        pending, self.scheduled = self.scheduled, []
        for fn in pending:
            fn()


@pytest.fixture
def controller():
    controller = AppController(main_window=None, threaded=False)
    try:
        yield controller
    finally:
        root_logger = logging.getLogger()
        for name in ("gui_log_handler", "json_log_handler"):
            handler = getattr(controller, name, None)
            if handler is not None:
                root_logger.removeHandler(handler)


@pytest.fixture
def scheduler(controller) -> _Scheduler:
    scheduler = _Scheduler()
    controller._ui_dispatch_later = scheduler
    return scheduler


def _all_flags_clear(controller) -> bool:
    return not (
        controller._ui_preview_dirty
        or controller._ui_job_list_dirty
        or controller._ui_history_dirty
        or controller._ui_queue_dirty
        or controller._ui_debounce_pending
    )


def test_rapid_dirty_marks_schedule_one_callback_and_refresh_once(controller, scheduler) -> None:
    controller._refresh_preview_from_state_async = MagicMock()

    controller._mark_ui_dirty(preview=True)
    controller._mark_ui_dirty(preview=True)
    controller._mark_ui_dirty(preview=True)

    assert len(scheduler.scheduled) == 1, "three marks must coalesce into one scheduled callback"
    controller._refresh_preview_from_state_async.assert_not_called()
    assert controller._ui_preview_dirty is True
    assert controller._ui_debounce_pending is True

    scheduler.run_all()

    controller._refresh_preview_from_state_async.assert_called_once()
    assert _all_flags_clear(controller)

    # A later mark schedules a fresh callback (the debounce is re-armed).
    controller._mark_ui_dirty(preview=True)
    assert len(scheduler.scheduled) == 1


def test_multiple_dirty_categories_are_applied_together_and_cleared(controller, scheduler) -> None:
    controller._refresh_preview_from_state_async = MagicMock()

    controller._mark_ui_dirty(preview=True, jobs=True, history=True)
    assert len(scheduler.scheduled) == 1
    controller._apply_pending_ui_updates()

    controller._refresh_preview_from_state_async.assert_called_once()
    assert _all_flags_clear(controller)


def test_applying_scheduled_ui_work_advances_the_ui_heartbeat(
    controller, scheduler, monkeypatch: pytest.MonkeyPatch
) -> None:
    clock = {"now": 1000.0}
    monkeypatch.setattr(time, "monotonic", lambda: clock["now"])
    controller._refresh_preview_from_state_async = MagicMock()
    controller.last_ui_heartbeat_ts = 100.0

    controller._mark_ui_dirty(preview=True)
    assert controller.last_ui_heartbeat_ts == 100.0, "heartbeat must not move until the UI loop runs the work"

    clock["now"] = 1250.0
    scheduler.run_all()

    assert controller.last_ui_heartbeat_ts == 1250.0


def test_a_failing_refresh_does_not_wedge_the_debounce(controller, scheduler) -> None:
    def _failing_refresh():
        raise RuntimeError("Test exception")

    controller._refresh_preview_from_state_async = _failing_refresh

    controller._mark_ui_dirty(preview=True)
    scheduler.run_all()  # must not raise

    assert _all_flags_clear(controller)

    # The debounce still works afterwards.
    controller._refresh_preview_from_state_async = MagicMock()
    controller._mark_ui_dirty(preview=True)
    scheduler.run_all()
    controller._refresh_preview_from_state_async.assert_called_once()


def test_queue_updates_are_coalesced_into_one_refresh(controller, scheduler) -> None:
    """Queue update events should mark queue dirty and coalesce refresh work."""
    controller.app_state = MagicMock()
    controller._refresh_app_state_queue = MagicMock()

    controller._on_queue_updated(["job-1"])
    controller._on_queue_updated(["job-1", "job-2"])
    controller._on_queue_updated(["job-1", "job-2", "job-3"])

    assert controller._ui_queue_dirty is True
    assert controller._ui_debounce_pending is True
    assert len(scheduler.scheduled) == 1
    controller._refresh_app_state_queue.assert_not_called()

    scheduler.run_all()

    controller._refresh_app_state_queue.assert_called_once()
    assert controller._ui_queue_dirty is False
    assert controller._ui_debounce_pending is False
