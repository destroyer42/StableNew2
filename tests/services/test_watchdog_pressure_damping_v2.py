from __future__ import annotations

import time
from types import SimpleNamespace

from src.services.watchdog_system_v2 import SystemWatchdogV2


def _build_app() -> SimpleNamespace:
    return SimpleNamespace(
        last_ui_heartbeat_ts=time.monotonic() - 40.0,
        last_queue_activity_ts=time.monotonic() - 5.0,
        last_runner_activity_ts=time.monotonic() - 5.0,
        current_operation_label="txt2img",
        last_ui_action="render",
        get_queue_state=lambda: {"queued": 1, "running": 1},
        has_running_jobs=lambda: True,
        _is_shutting_down=False,
    )


class _CaptureDiagnostics:
    def __init__(self) -> None:
        self.calls: list[dict[str, object]] = []

    def build_async(self, **kwargs) -> None:
        self.calls.append(kwargs)
        on_done = kwargs.get("on_done")
        if callable(on_done):
            on_done()


def test_watchdog_passes_process_state_and_cooldown_to_async_builder() -> None:
    app = _build_app()
    diagnostics = _CaptureDiagnostics()
    watchdog = SystemWatchdogV2(app, diagnostics_service=diagnostics)

    watchdog._check()

    assert diagnostics.calls
    call = diagnostics.calls[0]
    assert call["reason"] == "ui_heartbeat_stall"
    assert call["include_process_state"] is True
    assert call["cooldown_s"] == SystemWatchdogV2.COOLDOWN_S["ui_heartbeat_stall"]


def test_watchdog_skips_when_main_thread_not_alive(monkeypatch) -> None:
    app = _build_app()
    diagnostics = _CaptureDiagnostics()
    watchdog = SystemWatchdogV2(app, diagnostics_service=diagnostics)

    class _DeadThread:
        def is_alive(self) -> bool:
            return False

    monkeypatch.setattr("src.services.watchdog_system_v2.threading.main_thread", lambda: _DeadThread())

    watchdog._check()

    assert diagnostics.calls == []
