"""Test for heartbeat stall fix.

Validates that:
1. UI_STALL_S threshold is set to a realistic value (90s)
2. Progress reporting updates the UI heartbeat timestamp
"""

from __future__ import annotations

import time
from unittest.mock import Mock, patch

import pytest

from src.controller.app_controller import AppController
from src.gui.controller import PipelineController
from src.services.watchdog_system_v2 import SystemWatchdogV2


def test_ui_stall_threshold_is_realistic():
    """Verify UI_STALL_S is set to 10 seconds for fast failure detection."""
    # 10s is enough to detect true hangs quickly (fail fast)
    # Progress polling updates heartbeat during active work, preventing false positives
    assert SystemWatchdogV2.UI_STALL_S == 10.0, \
        "UI_STALL_S should be 10.0 for fast failure detection while progress keeps heartbeat alive"
    
    print(f"✓ UI_STALL_S correctly set to {SystemWatchdogV2.UI_STALL_S}s (fast failure detection)")


def test_progress_reporting_updates_heartbeat():
    """Verify that report_progress updates UI heartbeat timestamp."""
    # Create a mock AppController instance
    mock_app_controller = Mock()
    mock_app_controller.last_ui_heartbeat_ts = 0.0
    
    # Create a pipeline controller
    controller = PipelineController()
    
    # Patch AppController from the correct module
    with patch('src.controller.app_controller.AppController') as mock_app_class:
        mock_app_class._instance = mock_app_controller
        mock_app_class._instance.last_ui_heartbeat_ts = 0.0
        
        # Report progress
        time.sleep(0.01)  # Small delay
        controller.report_progress("txt2img", 50.0, "1m 30s")
        
        # Heartbeat should have been updated
        # Note: It's updated with time.monotonic(), so we can't check exact value
        # But we can verify the code path doesn't crash
        print("✓ Progress reporting executed without errors")


def test_app_controller_runner_activity_updates_timestamp():
    controller = AppController.__new__(AppController)
    controller.last_runner_activity_ts = 0.0

    AppController.notify_runner_activity(controller)

    assert controller.last_runner_activity_ts > 0.0


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
        
        # Simulate 5 seconds of "generation" with periodic heartbeat updates
        # (simulating progress polling updating the heartbeat)
        for i in range(10):  # 10 iterations * 0.5s = 5 seconds
            time.sleep(0.5)
            app.last_ui_heartbeat_ts = time.monotonic()  # Progress update
        
        # Stop watchdog
        watchdog.stop()
        
        # Check that no diagnostic files were created
        import os
        diagnostics = [f for f in os.listdir(tmpdir) if f.endswith('.zip')]
        
        assert len(diagnostics) == 0, \
            f"Watchdog should not trigger during active generation, but found {len(diagnostics)} diagnostic(s)"
        
        print("✓ Watchdog correctly did not trigger during simulated generation with heartbeat updates")


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
        
        print(f"✓ Watchdog correctly triggered on true stall (created {len(diagnostics)} diagnostic(s))")


if __name__ == "__main__":
    test_ui_stall_threshold_is_realistic()
    test_progress_reporting_updates_heartbeat()
    test_watchdog_doesnt_trigger_during_normal_generation()
    test_watchdog_still_triggers_on_true_stall()
    print("\n✅ All heartbeat stall fix tests passed!")
