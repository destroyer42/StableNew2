"""Test for job history cache race condition fix.

Validates that history display works correctly even with async persistence.
"""

from __future__ import annotations

import tempfile
import time
from datetime import datetime
from pathlib import Path
from unittest.mock import Mock, patch

from src.queue.job_history_store import JSONLJobHistoryStore, JobHistoryEntry
from src.queue.job_model import JobStatus


def test_history_cache_does_not_invalidate_prematurely():
    """Verify cache is NOT invalidated before file is written.

    This test simulates the race condition that caused intermittent
    empty history display:
    1. Job completes, _append() is called
    2. Write is queued to async persistence worker
    3. Cache should NOT be invalidated yet (old bug)
    4. GUI tries to refresh - should still see old cached data
    5. After file is written, cache naturally invalidates on next load
    """
    with tempfile.TemporaryDirectory() as tmpdir:
        history_file = Path(tmpdir) / "history.jsonl"
        
        # Pre-populate with one entry
        entry1 = JobHistoryEntry(
            job_id="job1",
            created_at=datetime.now(),
            status=JobStatus.COMPLETED,
            payload_summary="First job",
        )
        history_file.write_text(entry1.to_json() + "\n", encoding="utf-8")
        
        # Create store - it will cache the first entry
        store = JSONLJobHistoryStore(history_file)
        
        # Verify we can see the first job
        jobs = store.list_jobs()
        assert len(jobs) == 1
        assert jobs[0].job_id == "job1"
        
        # Now append a second entry (but mock the persistence worker to NOT write it)
        entry2 = JobHistoryEntry(
            job_id="job2",
            created_at=datetime.now(),
            status=JobStatus.COMPLETED,
            payload_summary="Second job",
        )
        
        # Mock the persistence worker to prevent actual write
        with patch("src.services.persistence_worker.get_persistence_worker") as mock_get_worker:
            mock_worker = Mock()
            
            # Append the entry (async write is mocked, so file doesn't change)
            store._append(entry2)
            
            # PR-HISTORY-FIX: Cache should NOT be invalidated yet
            # If we try to list jobs, we should still see the OLD cached data (just job1)
            # This is correct behavior - we wait for file mtime to change naturally
            jobs = store.list_jobs()
            
            # With the fix, we should still see only job1 (from cache)
            # because the file hasn't been written yet
            assert len(jobs) == 1, f"Expected 1 cached job, got {len(jobs)}"
            assert jobs[0].job_id == "job1", "Should still see old cached data"
        
        print("✓ Cache correctly remains valid until file is actually written")


def test_manual_refresh_invalidates_cache():
    """Verify manual refresh forces cache invalidation."""
    with tempfile.TemporaryDirectory() as tmpdir:
        history_file = Path(tmpdir) / "history.jsonl"
        
        # Pre-populate with one entry
        entry1 = JobHistoryEntry(
            job_id="job1",
            created_at=datetime.now(),
            status=JobStatus.COMPLETED,
            payload_summary="First job",
        )
        history_file.write_text(entry1.to_json() + "\n", encoding="utf-8")
        
        # Create store and load (caches entry1)
        store = JSONLJobHistoryStore(history_file)
        jobs = store.list_jobs()
        assert len(jobs) == 1
        
        # Now manually add a second entry to the file (simulating async write completion)
        entry2 = JobHistoryEntry(
            job_id="job2",
            created_at=datetime.now(),
            status=JobStatus.COMPLETED,
            payload_summary="Second job",
        )
        with history_file.open("a", encoding="utf-8") as f:
            f.write(entry2.to_json() + "\n")
        
        # Without invalidation, we'd still see only 1 job (cached)
        # But if we call invalidate_cache(), we should see both
        store.invalidate_cache()
        jobs = store.list_jobs()
        
        assert len(jobs) == 2, f"Expected 2 jobs after cache invalidation, got {len(jobs)}"
        job_ids = {j.job_id for j in jobs}
        assert "job1" in job_ids
        assert "job2" in job_ids
        
        print("✓ Manual cache invalidation forces reload from disk")


def test_cache_auto_invalidates_on_mtime_change():
    """Verify cache automatically invalidates when file is modified."""
    with tempfile.TemporaryDirectory() as tmpdir:
        history_file = Path(tmpdir) / "history.jsonl"
        
        # Pre-populate with one entry
        entry1 = JobHistoryEntry(
            job_id="job1",
            created_at=datetime.now(),
            status=JobStatus.COMPLETED,
            payload_summary="First job",
        )
        history_file.write_text(entry1.to_json() + "\n", encoding="utf-8")
        
        # Create store and load (caches entry1)
        store = JSONLJobHistoryStore(history_file)
        jobs = store.list_jobs()
        assert len(jobs) == 1
        
        # Wait a moment to ensure mtime will change
        time.sleep(0.1)
        
        # Modify the file (add second entry)
        entry2 = JobHistoryEntry(
            job_id="job2",
            created_at=datetime.now(),
            status=JobStatus.COMPLETED,
            payload_summary="Second job",
        )
        with history_file.open("a", encoding="utf-8") as f:
            f.write(entry2.to_json() + "\n")
        
        # Now when we call list_jobs(), it should detect mtime change and reload
        jobs = store.list_jobs()
        
        assert len(jobs) == 2, f"Expected 2 jobs after mtime change, got {len(jobs)}"
        job_ids = {j.job_id for j in jobs}
        assert "job1" in job_ids
        assert "job2" in job_ids
        
        print("✓ Cache auto-invalidates when file mtime changes")


if __name__ == "__main__":
    test_history_cache_does_not_invalidate_prematurely()
    test_manual_refresh_invalidates_cache()
    test_cache_auto_invalidates_on_mtime_change()
    print("\n✅ All job history cache fix tests passed!")
