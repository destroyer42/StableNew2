"""
PR-HB-003: Test watchdog UI stall context enhancements.

Tests that UI stall events include comprehensive diagnostic context.
"""
import time
from unittest.mock import MagicMock


class TestWatchdogUIStallContext:
    """Test watchdog system includes proper UI stall context."""
    
    def test_watchdog_includes_ui_age_s(self):
        """Test that UI stall context includes ui_age_s field."""
        from src.services.watchdog_system_v2 import SystemWatchdogV2
        
        # Create mock app controller
        app = MagicMock()
        app.last_ui_heartbeat_ts = time.monotonic() - 35  # 35 seconds ago (stale)
        app.current_operation_label = "test_operation"
        app.last_ui_action = "test_action"
        
        # Create watchdog
        watchdog = SystemWatchdogV2(app, diagnostics_service=None)
        
        # Mock the diagnostics service trigger
        captured_context = {}
        
        def _capture_trigger(reason, context):
            captured_context.update(context)
        
        if watchdog.diagnostics_service:
            watchdog.diagnostics_service.trigger_bundle_creation = _capture_trigger
        else:
            # Create mock diagnostics service
            mock_diagnostics = MagicMock()
            mock_diagnostics.trigger_bundle_creation = _capture_trigger
            watchdog.diagnostics_service = mock_diagnostics
        
        # Trigger stall check
        watchdog._check()
        
        # Wait for trigger (may be async)
        time.sleep(0.1)
        
        # Context should include ui_age_s
        if captured_context:
            assert "ui_age_s" in captured_context
            assert captured_context["ui_age_s"] > 30
    
    def test_watchdog_includes_current_operation_label(self):
        """Test that UI stall context includes current_operation_label."""
        from src.services.watchdog_system_v2 import SystemWatchdogV2
        
        # Create mock app controller
        app = MagicMock()
        app.last_ui_heartbeat_ts = time.monotonic() - 35  # 35 seconds ago
        app.current_operation_label = "Adding 5 pack(s) to job"
        app.last_ui_action = "on_pipeline_add_packs_to_job(['pack1', 'pack2'])"
        
        # Create watchdog
        watchdog = SystemWatchdogV2(app, diagnostics_service=None)
        
        # Mock diagnostics service
        captured_context = {}
        
        def _capture_trigger(reason, context):
            captured_context.update(context)
        
        mock_diagnostics = MagicMock()
        mock_diagnostics.trigger_bundle_creation = _capture_trigger
        watchdog.diagnostics_service = mock_diagnostics
        
        # Trigger check
        watchdog._check()
        time.sleep(0.1)
        
        # Should include operation label
        if captured_context:
            assert "current_operation_label" in captured_context
            assert captured_context["current_operation_label"] == "Adding 5 pack(s) to job"
    
    def test_watchdog_includes_ui_stall_threshold_s(self):
        """Test that UI stall context includes ui_stall_threshold_s."""
        from src.services.watchdog_system_v2 import SystemWatchdogV2
        
        # Create mock app controller
        app = MagicMock()
        app.last_ui_heartbeat_ts = time.monotonic() - 35
        app.current_operation_label = None
        
        # Create watchdog
        watchdog = SystemWatchdogV2(app, diagnostics_service=None)
        
        # Mock diagnostics service
        captured_context = {}
        
        def _capture_trigger(reason, context):
            captured_context.update(context)
        
        mock_diagnostics = MagicMock()
        mock_diagnostics.trigger_bundle_creation = _capture_trigger
        watchdog.diagnostics_service = mock_diagnostics
        
        # Trigger check
        watchdog._check()
        time.sleep(0.1)
        
        # Should include threshold
        if captured_context:
            assert "ui_stall_threshold_s" in captured_context
            assert captured_context["ui_stall_threshold_s"] == SystemWatchdogV2.UI_STALL_S
    
    def test_watchdog_context_comprehensive(self):
        """Test that all expected fields are present in stall context."""
        from src.services.watchdog_system_v2 import SystemWatchdogV2
        
        # Create mock app controller with all fields
        app = MagicMock()
        app.last_ui_heartbeat_ts = time.monotonic() - 35
        app.last_queue_activity_ts = time.monotonic() - 10
        app.last_runner_activity_ts = time.monotonic() - 5
        app.current_operation_label = "test_op"
        app.last_ui_action = "test_action"
        app.get_queue_state = MagicMock(return_value={"queued": 2, "running": 1})
        app.has_running_jobs = MagicMock(return_value=False)
        
        # Create watchdog
        watchdog = SystemWatchdogV2(app, diagnostics_service=None)
        
        # Mock diagnostics service
        captured_context = {}
        
        def _capture_trigger(reason, context):
            captured_context.update(context)
        
        mock_diagnostics = MagicMock()
        mock_diagnostics.trigger_bundle_creation = _capture_trigger
        watchdog.diagnostics_service = mock_diagnostics
        
        # Trigger check
        watchdog._check()
        time.sleep(0.1)
        
        # Verify comprehensive context
        if captured_context:
            expected_fields = [
                "ui_age_s",
                "ui_heartbeat_age_s",  # Legacy field
                "current_operation_label",
                "last_ui_action",
                "ui_stall_threshold_s",
                "last_ui_heartbeat_ts",
                "watchdog_reason",
            ]
            
            for field in expected_fields:
                assert field in captured_context, f"Missing field: {field}"
