"""Unit tests for DurationStatsService (PR-PIPE-002).

Tests the duration statistics aggregation service that provides queue ETA
estimates based on historical job durations.
"""

from __future__ import annotations

import unittest
from datetime import datetime
from typing import Any
from unittest.mock import MagicMock, Mock

from src.queue.job_history_store import JobHistoryEntry
from src.queue.job_model import JobStatus
from src.services.duration_stats_service import (
    STAGE_FALLBACK_SECONDS,
    DurationStatsService,
    StageChainStats,
)


class MockHistoryStore:
    """Mock history store for testing."""

    def __init__(self, entries: list[JobHistoryEntry] | None = None) -> None:
        self._entries = entries or []

    def list_jobs(self, limit: int = 50, **kwargs: Any) -> list[JobHistoryEntry]:
        return self._entries[:limit]


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


class TestRefresh(unittest.TestCase):
    """Test DurationStatsService.refresh()."""

    def test_refresh_with_empty_history(self) -> None:
        """Empty history should produce no stats."""
        store = MockHistoryStore([])
        service = DurationStatsService(store)

        service.refresh()

        self.assertEqual(len(service._stats_cache), 0)
        self.assertIsNotNone(service._last_refresh)

    def test_refresh_with_valid_history(self) -> None:
        """Valid history should compute correct stats."""
        entries = [
            make_entry("job1", ["txt2img", "adetailer"], 120000),
            make_entry("job2", ["txt2img", "adetailer"], 130000),
            make_entry("job3", ["txt2img", "adetailer"], 140000),
        ]
        store = MockHistoryStore(entries)
        service = DurationStatsService(store, min_samples_for_stats=3)

        service.refresh()

        # Should have stats for the chain
        chain = ("txt2img", "adetailer")
        stats = service.get_stats(chain)
        self.assertIsNotNone(stats)
        self.assertEqual(stats.sample_count, 3)
        self.assertEqual(stats.median_duration_ms, 130000.0)
        self.assertEqual(stats.mean_duration_ms, 130000.0)
        self.assertEqual(stats.min_duration_ms, 120000)
        self.assertEqual(stats.max_duration_ms, 140000)

    def test_refresh_with_insufficient_samples(self) -> None:
        """Chains with fewer than min_samples should not get stats."""
        entries = [
            make_entry("job1", ["txt2img"], 60000),
            make_entry("job2", ["txt2img"], 70000),
        ]
        store = MockHistoryStore(entries)
        service = DurationStatsService(store, min_samples_for_stats=3)

        service.refresh()

        # Should not have stats (need 3 samples)
        chain = ("txt2img",)
        stats = service.get_stats(chain)
        self.assertIsNone(stats)

    def test_refresh_ignores_invalid_durations(self) -> None:
        """Should skip entries with None or negative durations."""
        entries = [
            make_entry("job1", ["txt2img"], 60000),
            make_entry("job2", ["txt2img"], -1000),  # Invalid
            make_entry("job3", ["txt2img"], 70000),
        ]
        # Manually set one to None
        entries[1].duration_ms = None

        store = MockHistoryStore(entries)
        service = DurationStatsService(store, min_samples_for_stats=2)

        service.refresh()

        chain = ("txt2img",)
        stats = service.get_stats(chain)
        self.assertIsNotNone(stats)
        self.assertEqual(stats.sample_count, 2)  # Only valid ones

    def test_refresh_handles_missing_snapshot(self) -> None:
        """Should skip entries without stage chain in snapshot."""
        entry = JobHistoryEntry(
            job_id="job1",
            created_at=datetime.utcnow(),
            status=JobStatus.COMPLETED,
            duration_ms=60000,
            snapshot=None,  # No snapshot
        )
        store = MockHistoryStore([entry])
        service = DurationStatsService(store)

        service.refresh()

        # No stats should be generated
        self.assertEqual(len(service._stats_cache), 0)

    def test_refresh_max_samples_window(self) -> None:
        """Should keep only max_samples most recent entries."""
        # Create 150 entries
        entries = [
            make_entry(f"job{i}", ["txt2img"], 60000 + i * 1000)
            for i in range(150)
        ]
        store = MockHistoryStore(entries)
        service = DurationStatsService(store, max_samples_per_chain=100)

        service.refresh()

        chain = ("txt2img",)
        stats = service.get_stats(chain)
        self.assertIsNotNone(stats)
        # Should cap at 100 most recent
        self.assertEqual(stats.sample_count, 100)


class TestEstimates(unittest.TestCase):
    """Test estimate retrieval methods."""

    def setUp(self) -> None:
        """Create service with sample history."""
        entries = [
            make_entry("job1", ["txt2img", "adetailer"], 120000),
            make_entry("job2", ["txt2img", "adetailer"], 130000),
            make_entry("job3", ["txt2img", "adetailer"], 140000),
            make_entry("job4", ["txt2img"], 30000),
            make_entry("job5", ["txt2img"], 40000),
            make_entry("job6", ["txt2img"], 50000),
        ]
        store = MockHistoryStore(entries)
        self.service = DurationStatsService(store, min_samples_for_stats=3)
        self.service.refresh()

    def test_get_estimate_for_known_chain(self) -> None:
        """Should return median duration for known chain."""
        estimate = self.service.get_estimate_for_chain(["txt2img", "adetailer"])
        self.assertIsNotNone(estimate)
        self.assertEqual(estimate, 130.0)  # 130000ms = 130s

    def test_get_estimate_for_unknown_chain(self) -> None:
        """Should return None for chain without stats."""
        estimate = self.service.get_estimate_for_chain(["upscale"])
        self.assertIsNone(estimate)

    def test_get_fallback_estimate(self) -> None:
        """Should sum per-stage fallbacks."""
        estimate = self.service.get_fallback_estimate(["txt2img", "adetailer", "upscale"])
        expected = (
            STAGE_FALLBACK_SECONDS["txt2img"]
            + STAGE_FALLBACK_SECONDS["adetailer"]
            + STAGE_FALLBACK_SECONDS["upscale"]
        )
        self.assertEqual(estimate, expected)

    def test_get_fallback_for_unknown_stage(self) -> None:
        """Should use default 30s for unknown stages."""
        estimate = self.service.get_fallback_estimate(["unknown_stage"])
        self.assertEqual(estimate, 30.0)


class TestJobEstimates(unittest.TestCase):
    """Test job-specific estimate methods."""

    def setUp(self) -> None:
        """Create service with sample history."""
        entries = [
            make_entry("job1", ["txt2img", "upscale"], 100000),
            make_entry("job2", ["txt2img", "upscale"], 110000),
            make_entry("job3", ["txt2img", "upscale"], 120000),
        ]
        store = MockHistoryStore(entries)
        self.service = DurationStatsService(store, min_samples_for_stats=3)
        self.service.refresh()

    def test_get_estimate_for_job_with_stage_chain(self) -> None:
        """Should extract stage chain from job.stage_chain attribute."""
        job = Mock()
        job.stage_chain = ["txt2img", "upscale"]

        estimate = self.service.get_estimate_for_job(job)
        self.assertIsNotNone(estimate)
        self.assertEqual(estimate, 110.0)  # Median of 100, 110, 120

    def test_get_estimate_for_job_with_config_snapshot(self) -> None:
        """Should extract stage chain from config_snapshot."""
        job = Mock()
        job.stage_chain = None
        job.config_snapshot = {"stages": ["txt2img", "upscale"]}

        estimate = self.service.get_estimate_for_job(job)
        self.assertIsNotNone(estimate)
        self.assertEqual(estimate, 110.0)

    def test_get_estimate_for_job_without_chain(self) -> None:
        """Should return None if no chain can be extracted."""
        job = Mock()
        job.stage_chain = None
        job.config_snapshot = None

        estimate = self.service.get_estimate_for_job(job)
        self.assertIsNone(estimate)


class TestQueueEstimates(unittest.TestCase):
    """Test queue total estimate methods."""

    def setUp(self) -> None:
        """Create service with sample history."""
        entries = [
            make_entry("job1", ["txt2img"], 30000),
            make_entry("job2", ["txt2img"], 40000),
            make_entry("job3", ["txt2img"], 50000),
        ]
        store = MockHistoryStore(entries)
        self.service = DurationStatsService(store, min_samples_for_stats=3)
        self.service.refresh()

    def test_get_queue_total_estimate_all_known(self) -> None:
        """Should sum estimates for all jobs with history."""
        job1 = Mock()
        job1.stage_chain = ["txt2img"]
        job2 = Mock()
        job2.stage_chain = ["txt2img"]

        total, count = self.service.get_queue_total_estimate([job1, job2])

        self.assertEqual(count, 2)  # Both had estimates
        self.assertEqual(total, 80.0)  # 40s median × 2

    def test_get_queue_total_estimate_mixed(self) -> None:
        """Should use fallback for unknown chains."""
        job1 = Mock()
        job1.stage_chain = ["txt2img"]
        job2 = Mock()
        job2.stage_chain = ["upscale"]  # No history

        total, count = self.service.get_queue_total_estimate([job1, job2])

        self.assertEqual(count, 1)  # Only job1 had history
        # job1: 40s (median), job2: 60s (fallback)
        self.assertEqual(total, 100.0)

    def test_get_queue_total_estimate_empty_queue(self) -> None:
        """Should handle empty queue."""
        total, count = self.service.get_queue_total_estimate([])
        self.assertEqual(total, 0.0)
        self.assertEqual(count, 0)


class TestNoneHistoryStore(unittest.TestCase):
    """Test service behavior with None history store."""

    def test_refresh_with_none_store(self) -> None:
        """Should not crash with None store."""
        service = DurationStatsService(None)
        service.refresh()  # Should not raise

    def test_estimates_with_none_store(self) -> None:
        """Should return None estimates with no store."""
        service = DurationStatsService(None)
        service.refresh()

        estimate = service.get_estimate_for_chain(["txt2img"])
        self.assertIsNone(estimate)

    def test_fallback_works_without_store(self) -> None:
        """Fallback should work even without history store."""
        service = DurationStatsService(None)

        estimate = service.get_fallback_estimate(["txt2img", "adetailer"])
        expected = (
            STAGE_FALLBACK_SECONDS["txt2img"] + STAGE_FALLBACK_SECONDS["adetailer"]
        )
        self.assertEqual(estimate, expected)


class TestStatsRetrieval(unittest.TestCase):
    """Test full stats object retrieval."""

    def test_get_stats_returns_full_object(self) -> None:
        """get_stats should return StageChainStats with all fields."""
        entries = [
            make_entry("job1", ["txt2img"], 30000),
            make_entry("job2", ["txt2img"], 40000),
            make_entry("job3", ["txt2img"], 50000),
            make_entry("job4", ["txt2img"], 60000),
        ]
        store = MockHistoryStore(entries)
        service = DurationStatsService(store, min_samples_for_stats=3)
        service.refresh()

        stats = service.get_stats(("txt2img",))
        self.assertIsNotNone(stats)
        self.assertIsInstance(stats, StageChainStats)
        self.assertEqual(stats.stage_chain, ("txt2img",))
        self.assertEqual(stats.sample_count, 4)
        self.assertEqual(stats.median_duration_ms, 45000.0)
        self.assertEqual(stats.mean_duration_ms, 45000.0)
        self.assertEqual(stats.min_duration_ms, 30000)
        self.assertEqual(stats.max_duration_ms, 60000)
        self.assertGreater(stats.stddev_ms, 0)
        self.assertIsInstance(stats.last_updated, datetime)


if __name__ == "__main__":
    unittest.main()
