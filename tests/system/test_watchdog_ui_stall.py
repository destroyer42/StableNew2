import time
import tempfile
import os
import shutil
import threading
from pathlib import Path
from src.utils.diagnostics_bundle_v2 import build_async
from src.services.watchdog_system_v2 import SystemWatchdogV2

class DummyAppController:
    def __init__(self):
        self.last_ui_heartbeat_ts = time.monotonic()
        self.last_runner_activity_ts = time.monotonic()
        self._running = True
    def has_running_jobs(self):
        return self._running

class DummyDiagnosticsService:
    def __init__(self, bundle_dir):
        self.bundle_dir = Path(bundle_dir)
        self.triggered = []
    def build_async(self, reason, **kwargs):
        self.triggered.append(reason)
        # Actually call the real build_async to create a bundle
        build_async(
            reason=reason,
            log_handler=None,
            job_service=None,
            output_dir=self.bundle_dir,
        )

def test_ui_heartbeat_stall_triggers_diagnostics(tmp_path):
    bundle_dir = tmp_path / "diagnostics"
    bundle_dir.mkdir()
    app = DummyAppController()
    diag = DummyDiagnosticsService(bundle_dir)
    watchdog = SystemWatchdogV2(app, diag)
    watchdog.start()
    # Simulate UI freeze by not updating heartbeat
    app.last_ui_heartbeat_ts -= 5.0
    # Wait for watchdog to trigger
    for _ in range(10):
        if diag.triggered:
            break
        time.sleep(0.5)
    watchdog.stop()
    assert any("ui_heartbeat_stall" in r for r in diag.triggered)
    # Check that a diagnostics zip was created
    zips = list(bundle_dir.glob("stablenew_diagnostics_*.zip"))
    assert zips, "No diagnostics bundle created on UI stall"

def test_queue_runner_stall_triggers_diagnostics(tmp_path):
    bundle_dir = tmp_path / "diagnostics"
    bundle_dir.mkdir()
    app = DummyAppController()
    diag = DummyDiagnosticsService(bundle_dir)
    watchdog = SystemWatchdogV2(app, diag)
    watchdog.start()
    # Simulate running job with no runner activity
    app.last_runner_activity_ts -= 15.0
    # Wait for watchdog to trigger
    for _ in range(10):
        if diag.triggered:
            break
        time.sleep(0.5)
    watchdog.stop()
    assert any("queue_runner_stall" in r for r in diag.triggered)
    zips = list(bundle_dir.glob("stablenew_diagnostics_*.zip"))
    assert zips, "No diagnostics bundle created on runner stall"
