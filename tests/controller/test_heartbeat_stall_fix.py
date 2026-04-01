"""Test for heartbeat stall behavior.

Validates that:
1. `UI_STALL_S` is set to the current fast-fail threshold.
2. Progress reporting updates runner activity, not the UI heartbeat.
"""

from __future__ import annotations

import time
from unittest.mock import Mock

import pytest

from src.controller.app_controller import AppController
from src.controller.core_pipeline_controller import CorePipelineController
from src.services.watchdog_system_v2 import SystemWatchdogV2


def test_ui_stall_threshold_is_realistic():
    """Verify UI_STALL_S is set to 10 seconds for fast failure detection."""
    # 10s is enough to detect true hangs quickly (fail fast) while the Tk-driven
    # UI heartbeat keeps the watchdog quiet during responsive runs.
    assert SystemWatchdogV2.UI_STALL_S == 10.0, \
        "UI_STALL_S should remain at 10.0 for fast failure detection"
    
    print(f"[OK] UI_STALL_S correctly set to {SystemWatchdogV2.UI_STALL_S}s (fast failure detection)")


def test_progress_reporting_updates_runner_activity_not_ui_heartbeat():
    """Verify that report_progress marks runner activity without masking a frozen UI."""
    mock_app_controller = Mock()
    mock_app_controller.last_ui_heartbeat_ts = 123.0

    controller = CorePipelineController(app_controller=mock_app_controller)

    time.sleep(0.01)
    controller.report_progress("txt2img", 50.0, "1m 30s")

    mock_app_controller.notify_runner_activity.assert_called_once_with()
    assert mock_app_controller.last_ui_heartbeat_ts == 123.0


def test_app_controller_runner_activity_updates_timestamp():
    controller = AppController.__new__(AppController)
    controller.last_runner_activity_ts = 0.0

    AppController.notify_runner_activity(controller)

    assert controller.last_runner_activity_ts > 0.0


def test_app_controller_has_running_jobs_reads_job_service_queue():
    controller = AppController.__new__(AppController)

    class _Job:
        def __init__(self, status):
            self.status = status

    class _Queue:
        @staticmethod
        def list_jobs():
            return [_Job("queued"), _Job("running")]

    controller.job_service = Mock(job_queue=None, queue=_Queue())

    assert AppController.has_running_jobs(controller) is True


def test_watchdog_doesnt_trigger_during_normal_generation():
    """Verify watchdog doesn't trigger during a 60-second image generation."""
    from src.services.diagnostics_service_v2 import DiagnosticsServiceV2
    import tempfile
    
    with tempfile.TemporaryDirectory() as tmpdir:
        # Create mock app controller that simulates active generation
        class ActiveGenerationApp:
            def __init__(self):
                self.last_ui_heartbeat_ts = time.monotonic()
                self.last_runner_activity_ts = time.monotonic()
                self._is_shutting_down = False
            
            def has_running_jobs(self):
                return False  # No running jobs for this test
        
        app = ActiveGenerationApp()
        diag = DiagnosticsServiceV2(tmpdir)
        watchdog = SystemWatchdogV2(app, diag, check_interval_s=0.5)
        
        # Start watchdog
        watchdog.start()
        
        # Simulate 5 seconds of responsive GUI main-loop heartbeat ticks.
        for i in range(10):  # 10 iterations * 0.5s = 5 seconds
            time.sleep(0.5)
            app.last_ui_heartbeat_ts = time.monotonic()
        
        # Stop watchdog
        watchdog.stop()
        
        # Check that no diagnostic files were created
        import os
        diagnostics = [f for f in os.listdir(tmpdir) if f.endswith('.zip')]
        
        assert len(diagnostics) == 0, \
            f"Watchdog should not trigger during active generation, but found {len(diagnostics)} diagnostic(s)"
        
        print("[OK] Watchdog correctly did not trigger during simulated generation with UI heartbeats")


def test_watchdog_still_triggers_on_true_stall():
    """Verify watchdog still triggers if UI truly stalls for 90+ seconds."""
    from src.services.diagnostics_service_v2 import DiagnosticsServiceV2
    from src.utils.diagnostics_bundle_v2 import _IN_FLIGHT, _LAST_BUNDLE_TS
    import tempfile
    
    with tempfile.TemporaryDirectory() as tmpdir:
        _IN_FLIGHT.clear()
        _LAST_BUNDLE_TS.clear()
        # Create mock app controller that is truly stalled
        class StalledApp:
            def __init__(self):
                # Set heartbeat to 15 seconds ago (> 10s threshold = true stall)
                self.last_ui_heartbeat_ts = time.monotonic() - 15.0
                self.last_runner_activity_ts = time.monotonic()
                self._is_shutting_down = False
            
            def has_running_jobs(self):
                return False
            
            def get_queue_state(self):
                return {"status": "idle"}
        
        app = StalledApp()
        diag = DiagnosticsServiceV2(tmpdir)
        watchdog = SystemWatchdogV2(app, diag, check_interval_s=0.25)
        
        # Start watchdog
        watchdog.start()
        
        # Wait for watchdog to check and trigger
        time.sleep(1.5)
        
        # Stop watchdog
        watchdog.stop()
        diag.wait_for_idle(timeout_s=10.0)
        time.sleep(0.1)
        
        # Check that diagnostic file WAS created (true stall detected)
        import os
        diagnostics = [f for f in os.listdir(tmpdir) if f.endswith('.zip')]
        
        assert len(diagnostics) >= 1, \
            "Watchdog should trigger on true stall (15s old heartbeat > 10s threshold)"
        
        print(f"[OK] Watchdog correctly triggered on true stall (created {len(diagnostics)} diagnostic(s))")


if __name__ == "__main__":
    test_ui_stall_threshold_is_realistic()
    test_progress_reporting_updates_runner_activity_not_ui_heartbeat()
    test_watchdog_doesnt_trigger_during_normal_generation()
    test_watchdog_still_triggers_on_true_stall()
    print("\n[OK] All heartbeat stall fix tests passed!")
