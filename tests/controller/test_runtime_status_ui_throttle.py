from __future__ import annotations

from datetime import datetime
import time
from unittest.mock import Mock

from src.controller.app_controller import AppController


def test_runtime_status_updates_are_coalesced_before_ui_apply() -> None:
    controller = AppController(main_window=None, threaded=False)
    controller.app_state = Mock()
    controller._runtime_status_min_interval_ms = 250
    controller._last_runtime_status_flush_ts = time.monotonic()

    scheduled: list[tuple[int, object]] = []
    controller._ui_dispatch_later = lambda delay, fn: scheduled.append((delay, fn))

    callback = controller._get_runtime_status_callback()
    callback({"job_id": "job-1", "current_stage": "txt2img", "progress": 0.10})
    callback({"job_id": "job-1", "current_stage": "txt2img", "progress": 0.25})

    assert len(scheduled) == 1
    assert scheduled[0][0] > 0
    controller.app_state.set_runtime_status.assert_not_called()

    scheduled[0][1]()

    controller.app_state.set_runtime_status.assert_called_once()
    status = controller.app_state.set_runtime_status.call_args[0][0]
    assert status.progress == 0.25


def test_runtime_status_callback_preserves_previous_stage_and_started_at_for_partial_updates() -> None:
    controller = AppController(main_window=None, threaded=False)
    controller.app_state = Mock()

    scheduled: list[object] = []
    controller._ui_dispatch_later = lambda delay, fn: scheduled.append(fn)
    callback = controller._get_runtime_status_callback()
    started_at = datetime(2026, 3, 29, 12, 0, 0)

    callback(
        {
            "job_id": "job-1",
            "current_stage": "svd_native",
            "progress": 0.10,
            "started_at": started_at,
        }
    )
    scheduled.pop(0)()

    controller.app_state.set_runtime_status.reset_mock()

    callback(
        {
            "stage_detail": "postprocess: interpolation",
            "progress": 0.25,
        }
    )
    scheduled.pop(0)()

    status = controller.app_state.set_runtime_status.call_args[0][0]
    assert status.job_id == "job-1"
    assert status.current_stage == "svd_native"
    assert status.stage_detail == "postprocess: interpolation"
    assert status.started_at == started_at
