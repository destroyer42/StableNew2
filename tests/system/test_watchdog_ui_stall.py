import time

from src.services.diagnostics_service_v2 import DiagnosticsServiceV2
from src.services.watchdog_system_v2 import SystemWatchdogV2
from src.utils.diagnostics_bundle_v2 import _IN_FLIGHT, _LAST_BUNDLE_TS


def _bundles(bundle_dir):
    return list(bundle_dir.glob("stablenew_diagnostics_*.zip"))


def _wait_for_bundle(bundle_dir, diag):
    """Until the watchdog thread has run its check and the bundle is on disk (a slow machine just waits longer)."""

    deadline = time.monotonic() + 60.0
    while not _bundles(bundle_dir) and time.monotonic() < deadline:
        time.sleep(0.05)
        diag.wait_for_idle(timeout_s=10.0)
    return _bundles(bundle_dir)


class DummyAppController:
    def __init__(self):
        self.last_ui_heartbeat_ts = time.monotonic()
        self.last_runner_activity_ts = time.monotonic()
        self._running = True

    def has_running_jobs(self):
        return self._running


def test_ui_heartbeat_stall_triggers_diagnostics(tmp_path):
    _IN_FLIGHT.clear()
    _LAST_BUNDLE_TS.clear()
    bundle_dir = tmp_path / "diagnostics"
    bundle_dir.mkdir()
    app = DummyAppController()
    diag = DiagnosticsServiceV2(bundle_dir)
    watchdog = SystemWatchdogV2(app, diag, check_interval_s=0.25)
    watchdog.start()
    # Simulate UI freeze by not updating heartbeat
    app.last_ui_heartbeat_ts -= 15.0
    try:
        zips = _wait_for_bundle(bundle_dir, diag)
    finally:
        watchdog.stop()
    assert zips, "No diagnostics bundle created on UI stall"


def test_queue_runner_stall_triggers_diagnostics(tmp_path):
    _IN_FLIGHT.clear()
    _LAST_BUNDLE_TS.clear()
    bundle_dir = tmp_path / "diagnostics"
    bundle_dir.mkdir()
    app = DummyAppController()
    diag = DiagnosticsServiceV2(bundle_dir)
    watchdog = SystemWatchdogV2(app, diag, check_interval_s=0.25)
    watchdog.start()
    # Simulate running job with no runner activity
    app.last_runner_activity_ts -= SystemWatchdogV2.RUNNER_STALL_S + 5.0
    try:
        zips = _wait_for_bundle(bundle_dir, diag)
    finally:
        watchdog.stop()
    assert zips, "No diagnostics bundle created on runner stall"
