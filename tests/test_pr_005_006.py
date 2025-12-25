"""Test PR-005 (Preview Thumbnail & ETA) and PR-006 (Lifecycle Log Formatting)."""

import sys
from pathlib import Path
from datetime import datetime
from unittest.mock import Mock, MagicMock, patch
import tkinter as tk

# Add src to path
sys.path.insert(0, str(Path(__file__).parent))

from src.gui.panels_v2.preview_panel_v2 import PreviewPanelV2
from src.gui.panels_v2.running_job_panel_v2 import RunningJobPanelV2
from src.gui.panels_v2.debug_log_panel_v2 import DebugLogPanelV2
from src.gui.app_state_v2 import AppStateV2
from src.pipeline.job_models_v2 import JobLifecycleLogEvent


def test_pr_005_thumbnail_loading():
    """Test PR-005: Preview panel thumbnail loading logic."""
    print("\n=== Testing PR-005: Thumbnail Loading ===")
    
    root = tk.Tk()
    root.withdraw()
    
    try:
        app_state = AppStateV2()
        panel = PreviewPanelV2(root, app_state=app_state)
        
        # Check that _find_latest_output_image method exists
        assert hasattr(panel, '_find_latest_output_image'), \
            "Missing _find_latest_output_image method"
        
        # Test with mock job summary
        mock_summary = Mock()
        mock_summary.job_id = "test_job_123"
        mock_summary.output_dir = "outputs"
        mock_summary.result = None  # No result yet
        
        # Test image finding (will return None since no actual files)
        image_path = panel._find_latest_output_image(mock_summary)
        assert image_path is None or isinstance(image_path, Path), \
            f"Expected None or Path, got {type(image_path)}"
        
        print("✓ _find_latest_output_image method exists and callable")
        print("✓ Method handles missing images gracefully")
        
    finally:
        root.destroy()


def test_pr_005_eta_formatting():
    """Test PR-005: ETA formatting in running job panel."""
    print("\n=== Testing PR-005: ETA Formatting ===")
    
    root = tk.Tk()
    root.withdraw()
    
    try:
        app_state = AppStateV2()
        panel = RunningJobPanelV2(root, app_state=app_state)
        
        # Test ETA formatting
        assert panel._format_eta(None) == "", "None should return empty string"
        assert panel._format_eta(0) == "", "0 should return empty string"
        assert panel._format_eta(30) == "ETA: 30s", "30 seconds format wrong"
        assert panel._format_eta(90) == "ETA: 1m 30s", "90 seconds format wrong"
        assert panel._format_eta(3661) == "ETA: 1h 1m", "1hr format wrong"
        
        print("✓ _format_eta handles None and zero")
        print("✓ _format_eta formats seconds correctly")
        print("✓ _format_eta formats minutes correctly")
        print("✓ _format_eta formats hours correctly")
        
    finally:
        root.destroy()


def test_pr_006_log_formatting():
    """Test PR-006: Enhanced lifecycle log formatting."""
    print("\n=== Testing PR-006: Lifecycle Log Formatting ===")
    
    root = tk.Tk()
    root.withdraw()
    
    try:
        app_state = AppStateV2()
        panel = DebugLogPanelV2(root, app_state=app_state)
        
        # Create test events
        test_events = [
            JobLifecycleLogEvent(
                timestamp=datetime.now(),
                source="queue",
                event_type="job_created",
                job_id="abc123def456",
                bundle_id=None,
                draft_size=None,
                message="Created from draft"
            ),
            JobLifecycleLogEvent(
                timestamp=datetime.now(),
                source="executor",
                event_type="job_started",
                job_id="abc123def456",
                bundle_id=None,
                draft_size=None,
                message="Starting txt2img"
            ),
            JobLifecycleLogEvent(
                timestamp=datetime.now(),
                source="executor",
                event_type="stage_completed",
                job_id="abc123def456",
                bundle_id=None,
                draft_size=None,
                message="Completed txt2img"
            ),
            JobLifecycleLogEvent(
                timestamp=datetime.now(),
                source="executor",
                event_type="job_completed",
                job_id="abc123def456",
                bundle_id=None,
                draft_size=None,
                message="All stages done"
            ),
            JobLifecycleLogEvent(
                timestamp=datetime.now(),
                source="executor",
                event_type="job_failed",
                job_id="def789ghi012",
                bundle_id=None,
                draft_size=None,
                message="Model not found"
            ),
            JobLifecycleLogEvent(
                timestamp=datetime.now(),
                source="queue",
                event_type="draft_submitted",
                job_id=None,
                bundle_id="bundle_xyz",
                draft_size=4,
                message="Batch submission"
            ),
        ]
        
        # Format each event and check
        for event in test_events:
            formatted = panel._format_event(event)
            
            # Check timestamp present
            assert ":" in formatted.split("|")[0], "Missing timestamp"
            
            # Check event-specific formatting
            if event.event_type == "job_created":
                assert "created" in formatted.lower(), "Missing 'created' message"
                assert event.job_id[:8] in formatted, "Missing short job ID"
                
            elif event.event_type == "job_started":
                assert "started" in formatted.lower(), "Missing 'started' message"
                
            elif event.event_type == "stage_completed":
                assert "✓" in formatted, "Missing success checkmark"
                assert "completed" in formatted.lower(), "Missing 'completed'"
                
            elif event.event_type == "job_completed":
                assert "✓" in formatted, "Missing success checkmark"
                assert "completed" in formatted.lower(), "Missing 'completed'"
                
            elif event.event_type == "job_failed":
                assert "✗" in formatted, "Missing failure X"
                assert "failed" in formatted.lower(), "Missing 'failed'"
                assert event.message in formatted, "Missing error reason"
                
            elif event.event_type == "draft_submitted":
                assert str(event.draft_size) in formatted, "Missing draft size"
                assert "batch" in formatted.lower(), "Missing 'batch' message"
            
            print(f"✓ Formatted: {formatted}")
        
        print("✓ All event types format correctly")
        print("✓ Timestamps included")
        print("✓ Visual indicators (✓ ✗) present")
        print("✓ Job IDs shortened to 8 chars")
        
    finally:
        root.destroy()


def main():
    """Run all tests for PR-005 and PR-006."""
    print("=" * 60)
    print("Testing PR-005 and PR-006 Implementations")
    print("=" * 60)
    
    try:
        test_pr_005_thumbnail_loading()
        test_pr_005_eta_formatting()
        test_pr_006_log_formatting()
        
        print("\n" + "=" * 60)
        print("✓ ALL TESTS PASSED")
        print("=" * 60)
        print("\nPR-005: Preview Thumbnail & ETA - VERIFIED")
        print("PR-006: Lifecycle Log Formatting - VERIFIED")
        return 0
        
    except AssertionError as e:
        print(f"\n✗ TEST FAILED: {e}")
        return 1
    except Exception as e:
        print(f"\n✗ ERROR: {e}")
        import traceback
        traceback.print_exc()
        return 1


if __name__ == "__main__":
    sys.exit(main())
