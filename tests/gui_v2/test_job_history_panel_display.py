"""Tests for JobHistoryPanelV2 display enhancements (model, seed, duration)."""

import tkinter as tk
import unittest
from datetime import datetime, timedelta
from unittest.mock import Mock

from src.gui.job_history_panel_v2 import JobHistoryPanelV2
from src.queue.job_history_store import JobHistoryEntry, JobStatus
from tests.gui_v2.tk_test_utils import get_shared_tk_root


class TestJobHistoryPanelDisplay(unittest.TestCase):
    """Test job history panel display with model, seed, and duration columns."""

    def setUp(self) -> None:
        """Set up test fixtures."""
        self.root = get_shared_tk_root()
        if not self.root:
            self.skipTest("Tk not available")
        self.controller = Mock()
        self.panel = JobHistoryPanelV2(self.root, controller=self.controller)

    def tearDown(self) -> None:
        """Clean up test fixtures."""
        if hasattr(self, 'panel'):
            try:
                self.panel.destroy()
            except Exception:
                pass

    def test_columns_include_model_and_seed(self) -> None:
        """Test that column configuration includes model and seed columns."""
        columns = self.panel.history_tree["columns"]
        
        assert "model" in columns
        assert "seed" in columns
        assert len(columns) == 8  # time, status, model, packs, duration, seed, images, output
        
        # Verify correct order
        column_list = list(columns)
        assert column_list[2] == "model"
        assert column_list[5] == "seed"

    def test_extract_model_from_snapshot(self) -> None:
        """Test extracting model from NJR snapshot."""
        entry = JobHistoryEntry(
            job_id="test-123",
            created_at=datetime.now(),
            status=JobStatus.COMPLETED,
            snapshot={
                "normalized_job": {
                    "base_model": "epicrealismXL_v5",
                }
            },
        )
        
        model = self.panel._extract_model(entry)
        
        assert "epicrealismXL" in model  # May be truncated
        assert model != "-"

    def test_extract_model_fallback_to_result(self) -> None:
        """Test model extraction falls back to result when snapshot missing."""
        entry = JobHistoryEntry(
            job_id="test-123",
            created_at=datetime.now(),
            status=JobStatus.COMPLETED,
            result={"model": "sd_xl_base_1.0"},
        )
        
        model = self.panel._extract_model(entry)
        
        assert "sd_xl_base" in model
        assert model != "-"

    def test_extract_model_missing_returns_dash(self) -> None:
        """Test model extraction returns '-' when data missing."""
        entry = JobHistoryEntry(
            job_id="test-123",
            created_at=datetime.now(),
            status=JobStatus.COMPLETED,
        )
        
        model = self.panel._extract_model(entry)
        
        assert model == "-"

    def test_extract_seed_from_result(self) -> None:
        """Test extracting actual seed from result."""
        entry = JobHistoryEntry(
            job_id="test-123",
            created_at=datetime.now(),
            status=JobStatus.COMPLETED,
            result={"actual_seed": 123456789},
        )
        
        seed = self.panel._extract_seed(entry)
        
        assert seed == "123456789"

    def test_extract_seed_random_display(self) -> None:
        """Test seed displays 'Random' for -1 seed."""
        entry = JobHistoryEntry(
            job_id="test-123",
            created_at=datetime.now(),
            status=JobStatus.COMPLETED,
            snapshot={
                "normalized_job": {
                    "seed": -1,
                }
            },
        )
        
        seed = self.panel._extract_seed(entry)
        
        assert seed == "Random"

    def test_extract_seed_from_snapshot(self) -> None:
        """Test extracting seed from NJR snapshot."""
        entry = JobHistoryEntry(
            job_id="test-123",
            created_at=datetime.now(),
            status=JobStatus.COMPLETED,
            snapshot={
                "normalized_job": {
                    "seed": 987654321,
                }
            },
        )
        
        seed = self.panel._extract_seed(entry)
        
        assert seed == "987654321"

    def test_ensure_duration_from_duration_ms(self) -> None:
        """Test duration uses pre-calculated duration_ms."""
        entry = JobHistoryEntry(
            job_id="test-123",
            created_at=datetime.now(),
            status=JobStatus.COMPLETED,
            duration_ms=120000,  # 2 minutes
        )
        
        duration = self.panel._ensure_duration(entry)
        
        assert duration == "2m 0s"

    def test_ensure_duration_from_timestamps(self) -> None:
        """Test duration calculates from timestamps when duration_ms missing."""
        now = datetime.now()
        start = now - timedelta(seconds=75)
        
        entry = JobHistoryEntry(
            job_id="test-123",
            created_at=start,
            started_at=start,
            completed_at=now,
            status=JobStatus.COMPLETED,
        )
        
        duration = self.panel._ensure_duration(entry)
        
        # Should be around 1m 15s
        assert "1m" in duration or "75s" in duration
        assert duration != "-"

    def test_ensure_duration_missing_returns_dash(self) -> None:
        """Test duration returns '-' when data missing."""
        entry = JobHistoryEntry(
            job_id="test-123",
            created_at=datetime.now(),
            status=JobStatus.COMPLETED,
        )
        
        duration = self.panel._ensure_duration(entry)
        
        assert duration == "-"

    def test_entry_values_returns_all_columns(self) -> None:
        """Test _entry_values returns tuple with all 8 columns."""
        entry = JobHistoryEntry(
            job_id="test-123",
            created_at=datetime.now(),
            status=JobStatus.COMPLETED,
            snapshot={
                "normalized_job": {
                    "base_model": "test_model",
                    "seed": 12345,
                }
            },
            duration_ms=30000,
        )
        
        values = self.panel._entry_values(entry)
        
        assert len(values) == 8
        assert isinstance(values, tuple)
        # Verify all fields are strings
        assert all(isinstance(v, str) for v in values)

    def test_old_entries_display_without_error(self) -> None:
        """Test old entries without new fields display correctly."""
        # Simulate old entry without snapshot or result
        entry = JobHistoryEntry(
            job_id="old-job",
            created_at=datetime.now(),
            status=JobStatus.COMPLETED,
            payload_summary="Old job without NJR snapshot",
        )
        
        values = self.panel._entry_values(entry)
        
        # Should not raise error and return 8 values
        assert len(values) == 8
        # Model and seed should show '-'
        assert values[2] == "-"  # model
        assert values[5] == "-"  # seed

    def test_extract_full_model_for_tooltip(self) -> None:
        """Test extracting full model name for tooltip."""
        entry = JobHistoryEntry(
            job_id="test-123",
            created_at=datetime.now(),
            status=JobStatus.COMPLETED,
            snapshot={
                "normalized_job": {
                    "base_model": "very_long_model_name_that_would_be_truncated_in_column",
                }
            },
        )
        
        full_model = self.panel._extract_full_model(entry)
        
        assert full_model == "very_long_model_name_that_would_be_truncated_in_column"
        assert len(full_model) > 18  # Would be truncated in display

    def test_format_duration_ms_various_times(self) -> None:
        """Test duration formatting for various time spans."""
        # Test seconds
        assert self.panel._format_duration_ms(5000) == "5s"
        
        # Test minutes
        assert self.panel._format_duration_ms(90000) == "1m 30s"
        
        # Test hours
        assert self.panel._format_duration_ms(7260000) == "2h 1m"

    def test_populate_history_with_new_columns(self) -> None:
        """Test populating history panel with entries containing new columns."""
        entries = [
            JobHistoryEntry(
                job_id="job-1",
                created_at=datetime.now(),
                status=JobStatus.COMPLETED,
                snapshot={
                    "normalized_job": {
                        "base_model": "test_model_1",
                        "seed": 111,
                    }
                },
                duration_ms=15000,
            ),
            JobHistoryEntry(
                job_id="job-2",
                created_at=datetime.now(),
                status=JobStatus.COMPLETED,
                snapshot={
                    "normalized_job": {
                        "base_model": "test_model_2",
                        "seed": 222,
                    }
                },
                duration_ms=25000,
            ),
        ]
        
        self.panel._populate_history(entries)
        
        # Verify entries were added
        children = self.panel.history_tree.get_children()
        assert len(children) == 2
        
        # Verify first entry has correct number of columns
        values = self.panel.history_tree.item(children[0])["values"]
        assert len(values) == 8


if __name__ == "__main__":
    unittest.main()
