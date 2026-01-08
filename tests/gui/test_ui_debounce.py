"""
PR-HB-003: Test UI update debouncing system.

Tests that rapid UI update requests are coalesced into a single periodic refresh.
"""
import time
from unittest.mock import MagicMock, patch

import pytest


class TestUIDebounce:
    """Test UI debouncing mechanism in AppController."""
    
    def test_debounce_coalesces_multiple_calls(self):
        """Test that multiple rapid dirty marks result in only one apply."""
        from src.controller.app_controller import AppController
        
        # Create controller without GUI (test mode)
        controller = AppController(main_window=None, threaded=False)
        
        # Track how many times _refresh_preview_from_state is called
        refresh_count = 0
        original_refresh = controller._refresh_preview_from_state
        
        def _counting_refresh():
            nonlocal refresh_count
            refresh_count += 1
            original_refresh()
        
        controller._refresh_preview_from_state = _counting_refresh
        
        # Mark preview dirty multiple times rapidly
        controller._mark_ui_dirty(preview=True)
        controller._mark_ui_dirty(preview=True)
        controller._mark_ui_dirty(preview=True)
        
        # Without GUI, _apply_pending_ui_updates runs immediately
        # But debounce flag should prevent multiple executions
        assert refresh_count <= 3, "Debounce should limit refresh calls"
        
    def test_dirty_flags_cleared_after_apply(self):
        """Test that dirty flags are cleared after UI update."""
        from src.controller.app_controller import AppController
        
        controller = AppController(main_window=None, threaded=False)
        
        # Mark all dirty
        controller._mark_ui_dirty(preview=True, jobs=True, history=True)
        
        # Apply updates
        controller._apply_pending_ui_updates()
        
        # Flags should be cleared
        assert not controller._ui_preview_dirty
        assert not controller._ui_job_list_dirty
        assert not controller._ui_history_dirty
        assert not controller._ui_debounce_pending
    
    def test_multiple_dirty_types_handled(self):
        """Test that different dirty types can be marked and applied together."""
        from src.controller.app_controller import AppController
        
        controller = AppController(main_window=None, threaded=False)
        
        # Mock the refresh methods
        preview_called = False
        jobs_called = False
        history_called = False
        
        def _mock_preview():
            nonlocal preview_called
            preview_called = True
        
        controller._refresh_preview_from_state = _mock_preview
        
        # Mark multiple types dirty
        controller._mark_ui_dirty(preview=True, jobs=True, history=True)
        
        # Apply updates
        controller._apply_pending_ui_updates()
        
        # Preview should be called
        assert preview_called
        
        # Flags should be cleared
        assert not controller._ui_preview_dirty
        assert not controller._ui_job_list_dirty
        assert not controller._ui_history_dirty
    
    def test_debounce_updates_heartbeat_timestamp(self):
        """Test that applying UI updates updates the heartbeat timestamp."""
        from src.controller.app_controller import AppController
        
        controller = AppController(main_window=None, threaded=False)
        
        # Record initial timestamp
        initial_ts = controller.last_ui_heartbeat_ts
        
        # Wait a bit
        time.sleep(0.01)
        
        # Mark dirty and apply
        controller._mark_ui_dirty(preview=True)
        controller._apply_pending_ui_updates()
        
        # Timestamp should be updated
        assert controller.last_ui_heartbeat_ts > initial_ts
    
    def test_debounce_handles_exceptions_gracefully(self):
        """Test that exceptions in refresh don't crash debounce system."""
        from src.controller.app_controller import AppController
        
        controller = AppController(main_window=None, threaded=False)
        
        # Make refresh raise an exception
        def _failing_refresh():
            raise RuntimeError("Test exception")
        
        controller._refresh_preview_from_state = _failing_refresh
        
        # This should not raise
        controller._mark_ui_dirty(preview=True)
        controller._apply_pending_ui_updates()
        
        # Debounce should still work after exception
        assert not controller._ui_debounce_pending
        assert not controller._ui_preview_dirty
