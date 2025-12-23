"""Integration tests for QueuePanelV2 with DurationStatsService (PR-PIPE-002).

Tests the queue panel's ETA display functionality with the duration stats service.
"""

from __future__ import annotations

import tkinter as tk
import unittest
from datetime import datetime
from unittest.mock import MagicMock, Mock, patch

from src.gui.panels_v2.queue_panel_v2 import QueuePanelV2
from src.pipeline.job_models_v2 import QueueJobV2
from src.queue.job_history_store import JobHistoryEntry
from src.queue.job_model import JobStatus
from src.services.duration_stats_service import DurationStatsService


def make_entry(
    job_id: str,
    stage_chain: list[str],
    duration_ms: int,
) -> JobHistoryEntry:
    """Create a test JobHistoryEntry with NJR snapshot."""
    return JobHistoryEntry(
        job_id=job_id,
        created_at=datetime.utcnow(),
        status=JobStatus.COMPLETED,
        duration_ms=duration_ms,
        snapshot={
            "normalized_job": {
                "stage_chain": stage_chain,
            }
        },
    )


class MockHistoryStore:
    """Mock history store for testing."""

    def __init__(self, entries: list[JobHistoryEntry] | None = None) -> None:
        self._entries = entries or []

    def list_jobs(self, limit: int = 50, **kwargs) -> list[JobHistoryEntry]:  # type: ignore[no-untyped-def]
        return self._entries[:limit]


class TestQueuePanelETA(unittest.TestCase):
    """Test QueuePanelV2 ETA display with duration stats service."""

    def setUp(self) -> None:
        """Set up test fixtures."""
        self.root = tk.Tk()
        self.root.withdraw()  # Don't show window during tests

    def tearDown(self) -> None:
        """Clean up test fixtures."""
        try:
            self.root.destroy()
        except Exception:
            pass

    def test_queue_panel_eta_with_stats_service(self) -> None:
        """Panel should use stats service for ETA when available."""
        # Create stats service with history
        entries = [
            make_entry("job1", ["txt2img", "adetailer"], 120000),
            make_entry("job2", ["txt2img", "adetailer"], 130000),
            make_entry("job3", ["txt2img", "adetailer"], 140000),
        ]
        store = MockHistoryStore(entries)
        stats_service = DurationStatsService(store, min_samples_for_stats=3)
        stats_service.refresh()

        # Create mock controller with stats service
        controller = Mock()
        controller.duration_stats_service = stats_service

        # Create panel
        panel = QueuePanelV2(self.root, controller=controller)

        # Create jobs with matching stage chain
        job1 = QueueJobV2.create({"prompt": "test job 1"})
        job1.stage_chain = ["txt2img", "adetailer"]
        job2 = QueueJobV2.create({"prompt": "test job 2"})
        job2.stage_chain = ["txt2img", "adetailer"]

        # Update panel with jobs
        panel.update_jobs([job1, job2])

        # Check ETA label contains estimate and confidence indicator
        eta_text = panel.queue_eta_label.cget("text")
        self.assertIn("~", eta_text)  # Should have confidence indicator
        # Should show approximately 260s (130s median × 2)
        self.assertTrue(
            "4m" in eta_text or "260" in eta_text,
            f"Expected 4m or 260s in ETA, got: {eta_text}",
        )

    def test_queue_panel_eta_without_stats_service(self) -> None:
        """Panel should fall back to hardcoded estimate without stats service."""
        # Create mock controller without stats service
        controller = Mock()
        controller.duration_stats_service = None

        # Create panel
        panel = QueuePanelV2(self.root, controller=controller)

        # Create jobs
        job1 = QueueJobV2.create({"prompt": "test job 1"})
        job2 = QueueJobV2.create({"prompt": "test job 2"})

        # Update panel with jobs
        panel.update_jobs([job1, job2])

        # Check ETA label contains fallback estimate
        eta_text = panel.queue_eta_label.cget("text")
        self.assertIn("?", eta_text)  # Should have fallback indicator
        # Should show 120s (60s × 2 fallback)
        self.assertIn("2m", eta_text)

    def test_queue_panel_eta_updates_on_refresh(self) -> None:
        """Panel ETA should update when stats are refreshed."""
        # Create stats service with initial history
        entries = [
            make_entry("job1", ["txt2img"], 30000),
            make_entry("job2", ["txt2img"], 40000),
            make_entry("job3", ["txt2img"], 50000),
        ]
        store = MockHistoryStore(entries)
        stats_service = DurationStatsService(store, min_samples_for_stats=3)
        stats_service.refresh()

        # Create mock controller
        controller = Mock()
        controller.duration_stats_service = stats_service

        # Create panel
        panel = QueuePanelV2(self.root, controller=controller)

        # Create job
        job = QueueJobV2.create({"prompt": "test job"})
        job.stage_chain = ["txt2img"]

        # Update panel
        panel.update_jobs([job])

        # Get initial ETA
        initial_eta = panel.queue_eta_label.cget("text")

        # Add more history entries (higher durations)
        store._entries.extend(
            [
                make_entry("job4", ["txt2img"], 80000),
                make_entry("job5", ["txt2img"], 90000),
                make_entry("job6", ["txt2img"], 100000),
            ]
        )
        stats_service.refresh()

        # Update panel again
        panel.update_jobs([job])

        # ETA should have changed (increased)
        new_eta = panel.queue_eta_label.cget("text")
        self.assertNotEqual(initial_eta, new_eta)

    def test_queue_panel_displays_confidence_indicators(self) -> None:
        """Panel should show correct confidence indicators."""
        # Create stats service with history for one chain only
        entries = [
            make_entry("job1", ["txt2img"], 30000),
            make_entry("job2", ["txt2img"], 40000),
            make_entry("job3", ["txt2img"], 50000),
        ]
        store = MockHistoryStore(entries)
        stats_service = DurationStatsService(store, min_samples_for_stats=3)
        stats_service.refresh()

        controller = Mock()
        controller.duration_stats_service = stats_service

        panel = QueuePanelV2(self.root, controller=controller)

        # Test all with history (should show ~)
        job1 = QueueJobV2.create({"prompt": "test 1"})
        job1.stage_chain = ["txt2img"]
        job2 = QueueJobV2.create({"prompt": "test 2"})
        job2.stage_chain = ["txt2img"]
        panel.update_jobs([job1, job2])
        eta_text = panel.queue_eta_label.cget("text")
        self.assertIn("~", eta_text)
        self.assertNotIn("?", eta_text)  # Only ~, no ?

        # Test mixed (should show ~?)
        job3 = QueueJobV2.create({"prompt": "test 3"})
        job3.stage_chain = ["upscale"]  # No history for this
        panel.update_jobs([job1, job3])
        eta_text = panel.queue_eta_label.cget("text")
        self.assertIn("~?", eta_text)

    def test_queue_panel_empty_queue(self) -> None:
        """Panel should handle empty queue correctly."""
        controller = Mock()
        stats_service = DurationStatsService(None)
        controller.duration_stats_service = stats_service

        panel = QueuePanelV2(self.root, controller=controller)
        panel.update_jobs([])

        eta_text = panel.queue_eta_label.cget("text")
        self.assertEqual(eta_text, "")

    def test_queue_panel_per_job_eta_display(self) -> None:
        """Panel should show per-job ETAs in listbox."""
        # Create stats service
        entries = [
            make_entry("job1", ["txt2img"], 30000),
            make_entry("job2", ["txt2img"], 40000),
            make_entry("job3", ["txt2img"], 50000),
        ]
        store = MockHistoryStore(entries)
        stats_service = DurationStatsService(store, min_samples_for_stats=3)
        stats_service.refresh()

        controller = Mock()
        controller.duration_stats_service = stats_service

        panel = QueuePanelV2(self.root, controller=controller)

        # Create job
        job = QueueJobV2.create({"prompt": "test prompt"})
        job.stage_chain = ["txt2img"]

        panel.update_jobs([job])

        # Get listbox item
        listbox_text = panel.job_listbox.get(0)

        # Should contain ETA in parentheses
        self.assertIn("(", listbox_text)
        self.assertTrue(
            "40s" in listbox_text or "~0m" in listbox_text,
            f"Expected ETA in listbox text: {listbox_text}",
        )

    def test_queue_panel_per_job_eta_without_history(self) -> None:
        """Panel should not show ETA for jobs without history."""
        # Empty stats service
        stats_service = DurationStatsService(None)

        controller = Mock()
        controller.duration_stats_service = stats_service

        panel = QueuePanelV2(self.root, controller=controller)

        # Create job
        job = QueueJobV2.create({"prompt": "test prompt"})
        job.stage_chain = ["txt2img"]

        panel.update_jobs([job])

        # Get listbox item
        listbox_text = panel.job_listbox.get(0)

        # Should not contain ETA (no parentheses from ETA)
        # Note: Summary might have other parentheses, so check for absence of time indicators
        self.assertNotIn("~", listbox_text)

    def test_compute_queue_eta_method(self) -> None:
        """Test _compute_queue_eta method directly."""
        # Create stats service
        entries = [
            make_entry("job1", ["txt2img"], 60000),
            make_entry("job2", ["txt2img"], 60000),
            make_entry("job3", ["txt2img"], 60000),
        ]
        store = MockHistoryStore(entries)
        stats_service = DurationStatsService(store, min_samples_for_stats=3)
        stats_service.refresh()

        controller = Mock()
        controller.duration_stats_service = stats_service

        panel = QueuePanelV2(self.root, controller=controller)

        # Create jobs
        job1 = QueueJobV2.create({"prompt": "test 1"})
        job1.stage_chain = ["txt2img"]
        job2 = QueueJobV2.create({"prompt": "test 2"})
        job2.stage_chain = ["txt2img"]

        panel._jobs = [job1, job2]

        # Call method
        total_seconds, confidence = panel._compute_queue_eta()

        self.assertEqual(total_seconds, 120.0)  # 60s × 2
        self.assertEqual(confidence, "~")  # All from history


if __name__ == "__main__":
    unittest.main()
