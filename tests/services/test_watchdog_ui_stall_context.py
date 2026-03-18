from __future__ import annotations

import time
from types import SimpleNamespace

from src.services.watchdog_system_v2 import SystemWatchdogV2


def _build_app(*, ui_age_s: float = 35.0) -> SimpleNamespace:
    return SimpleNamespace(
        last_ui_heartbeat_ts=time.monotonic() - ui_age_s,
        last_queue_activity_ts=time.monotonic() - 10.0,
        last_runner_activity_ts=time.monotonic() - 5.0,
        current_operation_label="test_op",
        last_ui_action="test_action",
        get_queue_state=lambda: {"queued": 2, "running": 1},
        has_running_jobs=lambda: False,
        _is_shutting_down=False,
    )


class _CaptureDiagnostics:
    def __init__(self) -> None:
        self.calls: list[dict[str, object]] = []

    def build(self, *, reason: str, context: dict) -> None:
        self.calls.append({"reason": reason, "context": context})

    def build_async(self, *, reason: str, context: dict, on_done=None) -> None:
        self.build(reason=reason, context=context)
        if on_done is not None:
            on_done()


def test_watchdog_includes_ui_age_s() -> None:
    app = _build_app()
    diagnostics = _CaptureDiagnostics()
    watchdog = SystemWatchdogV2(app, diagnostics_service=diagnostics)

    watchdog._check()

    assert len(diagnostics.calls) == 1
    assert diagnostics.calls[0]["reason"] == "ui_heartbeat_stall"
    assert diagnostics.calls[0]["context"]["ui_age_s"] > 30


def test_watchdog_includes_current_operation_label() -> None:
    app = _build_app()
    app.current_operation_label = "Adding 5 pack(s) to job"
    diagnostics = _CaptureDiagnostics()
    watchdog = SystemWatchdogV2(app, diagnostics_service=diagnostics)

    watchdog._check()

    assert diagnostics.calls[0]["context"]["current_operation_label"] == "Adding 5 pack(s) to job"


def test_watchdog_includes_ui_stall_threshold_s() -> None:
    app = _build_app()
    diagnostics = _CaptureDiagnostics()
    watchdog = SystemWatchdogV2(app, diagnostics_service=diagnostics)

    watchdog._check()

    assert diagnostics.calls[0]["context"]["ui_stall_threshold_s"] == SystemWatchdogV2.UI_STALL_S


def test_watchdog_context_comprehensive() -> None:
    app = _build_app()
    diagnostics = _CaptureDiagnostics()
    watchdog = SystemWatchdogV2(app, diagnostics_service=diagnostics)

    watchdog._check()

    context = diagnostics.calls[0]["context"]
    for field in (
        "ui_age_s",
        "ui_heartbeat_age_s",
        "current_operation_label",
        "last_ui_action",
        "ui_stall_threshold_s",
        "last_ui_heartbeat_ts",
        "watchdog_reason",
    ):
        assert field in context


def test_watchdog_skips_bundle_creation_when_diagnostics_missing() -> None:
    app = _build_app()
    watchdog = SystemWatchdogV2(app, diagnostics_service=None)

    watchdog._check()

    assert watchdog._in_flight["ui_heartbeat_stall"] is False
