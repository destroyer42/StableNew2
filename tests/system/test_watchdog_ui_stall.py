import time
from src.services.diagnostics_service_v2 import DiagnosticsServiceV2
from src.services.watchdog_system_v2 import SystemWatchdogV2

class DummyAppController:
    def __init__(self):
        self.last_ui_heartbeat_ts = time.monotonic()
        self.last_runner_activity_ts = time.monotonic()
        self._running = True
    def has_running_jobs(self):
        return self._running



def test_ui_heartbeat_stall_triggers_diagnostics(tmp_path):
    bundle_dir = tmp_path / "diagnostics"
    bundle_dir.mkdir()
    app = DummyAppController()
    diag = DiagnosticsServiceV2(bundle_dir)
    watchdog = SystemWatchdogV2(app, diag, check_interval_s=0.25)
    watchdog.start()
    # Simulate UI freeze by not updating heartbeat
    app.last_ui_heartbeat_ts -= 5.0
    # Wait for watchdog to trigger synchronously
    time.sleep(1.5)
    watchdog.stop()
    zips = list(bundle_dir.glob("stablenew_diagnostics_*.zip"))
    assert zips, "No diagnostics bundle created on UI stall"

def test_queue_runner_stall_triggers_diagnostics(tmp_path):
    bundle_dir = tmp_path / "diagnostics"
    bundle_dir.mkdir()
    app = DummyAppController()
    diag = DiagnosticsServiceV2(bundle_dir)
    watchdog = SystemWatchdogV2(app, diag, check_interval_s=0.25)
    watchdog.start()
    # Simulate running job with no runner activity
    app.last_runner_activity_ts -= 15.0
    # Wait for watchdog to trigger synchronously
    time.sleep(1.5)
    watchdog.stop()
    zips = list(bundle_dir.glob("stablenew_diagnostics_*.zip"))
    assert zips, "No diagnostics bundle created on runner stall"
