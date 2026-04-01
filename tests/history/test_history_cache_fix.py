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


def test_history_cache_uses_pending_overlay_before_file_write():
    """Verify pending entries remain visible before async file write completes.

    This test simulates the race condition that caused intermittent
    stale history display:
    1. Job completes, _append() is called
    2. Write is queued to async persistence worker
    3. Cache should remain stable, but pending overlay should still surface
       the newest in-memory entry
    4. GUI tries to refresh - it should see both the cached disk entry and
       the new pending entry
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
            
            # Cache should remain stable, but pending entries should still be visible
            # immediately so status transitions do not read back as stale.
            jobs = store.list_jobs()

            assert len(jobs) == 2, f"Expected 2 jobs with pending overlay, got {len(jobs)}"
            job_ids = {job.job_id for job in jobs}
            assert job_ids == {"job1", "job2"}


def test_pending_overlay_replaces_stale_cached_status():
    """Verify pending status updates override stale cached disk state."""
    with tempfile.TemporaryDirectory() as tmpdir:
        history_file = Path(tmpdir) / "history.jsonl"

        queued_entry = JobHistoryEntry(
            job_id="job1",
            created_at=datetime.now(),
            status=JobStatus.RUNNING,
            payload_summary="Job 1",
        )
        history_file.write_text(queued_entry.to_json() + "\n", encoding="utf-8")

        store = JSONLJobHistoryStore(history_file)
        cached = store.get_job("job1")
        assert cached is not None
        assert cached.status == JobStatus.RUNNING

        failed_entry = JobHistoryEntry(
            job_id="job1",
            created_at=queued_entry.created_at,
            started_at=queued_entry.created_at,
            completed_at=datetime.now(),
            status=JobStatus.FAILED,
            payload_summary="Job 1",
            error_message="connection refused",
        )

        with patch("src.services.persistence_worker.get_persistence_worker") as mock_get_worker:
            mock_worker = Mock()
            mock_worker.enqueue.return_value = True
            mock_get_worker.return_value = mock_worker

            store._append(failed_entry)

            updated = store.get_job("job1")
            assert updated is not None
            assert updated.status == JobStatus.FAILED
            assert updated.error_message == "connection refused"


def test_record_status_change_uses_pending_entry_without_disk_reload():
    """Hot status transitions must not rescan the history file for the same job."""
    with tempfile.TemporaryDirectory() as tmpdir:
        history_file = Path(tmpdir) / "history.jsonl"
        store = JSONLJobHistoryStore(history_file)

        entry = JobHistoryEntry(
            job_id="job1",
            created_at=datetime.now(),
            status=JobStatus.QUEUED,
            payload_summary="Job 1",
        )

        with patch("src.services.persistence_worker.get_persistence_worker") as mock_get_worker:
            mock_worker = Mock()
            mock_worker.enqueue.return_value = True
            mock_get_worker.return_value = mock_worker
            store._append(entry)

            with patch.object(
                store,
                "_load_latest_by_job",
                side_effect=AssertionError("disk reload should not occur"),
            ):
                store.record_status_change(entry.job_id, JobStatus.RUNNING, datetime.now())


def test_persisted_callback_keeps_cache_current_without_disk_reload():
    """Persistence completion should advance the cache state without a full reread."""
    with tempfile.TemporaryDirectory() as tmpdir:
        history_file = Path(tmpdir) / "history.jsonl"

        entry1 = JobHistoryEntry(
            job_id="job1",
            created_at=datetime.now(),
            status=JobStatus.COMPLETED,
            payload_summary="First job",
        )
        history_file.write_text(entry1.to_json() + "\n", encoding="utf-8")

        store = JSONLJobHistoryStore(history_file)
        jobs = store.list_jobs()
        assert len(jobs) == 1

        entry2 = JobHistoryEntry(
            job_id="job2",
            created_at=datetime.now(),
            status=JobStatus.COMPLETED,
            payload_summary="Second job",
        )

        with patch("src.services.persistence_worker.get_persistence_worker") as mock_get_worker:
            mock_worker = Mock()
            mock_worker.enqueue.return_value = True
            mock_get_worker.return_value = mock_worker

            store._append(entry2)

            with history_file.open("a", encoding="utf-8") as handle:
                handle.write(entry2.to_json() + "\n")
            task = mock_worker.enqueue.call_args.args[0]
            task.callback()

        with patch.object(
            Path,
            "read_text",
            side_effect=AssertionError("disk reload should not occur"),
        ):
            jobs = store.list_jobs()

        assert len(jobs) == 2
        assert {job.job_id for job in jobs} == {"job1", "job2"}


def test_list_recent_jobs_returns_latest_unique_terminal_entries():
    """Recent-history reads should scan from the end and ignore older duplicates."""
    with tempfile.TemporaryDirectory() as tmpdir:
        history_file = Path(tmpdir) / "history.jsonl"
        store = JSONLJobHistoryStore(history_file)

        queued = JobHistoryEntry(
            job_id="job1",
            created_at=datetime.now(),
            status=JobStatus.QUEUED,
            payload_summary="queued",
        )
        completed = JobHistoryEntry(
            job_id="job1",
            created_at=datetime.now(),
            status=JobStatus.COMPLETED,
            payload_summary="completed",
        )
        failed = JobHistoryEntry(
            job_id="job2",
            created_at=datetime.now(),
            status=JobStatus.FAILED,
            payload_summary="failed",
        )
        running = JobHistoryEntry(
            job_id="job3",
            created_at=datetime.now(),
            status=JobStatus.RUNNING,
            payload_summary="running",
        )
        history_file.write_text(
            "\n".join(
                [
                    queued.to_json(),
                    completed.to_json(),
                    failed.to_json(),
                    running.to_json(),
                ]
            )
            + "\n",
            encoding="utf-8",
        )

        entries = store.list_recent_jobs(
            limit=5,
            statuses={JobStatus.COMPLETED, JobStatus.FAILED},
        )

        assert [entry.job_id for entry in entries] == ["job2", "job1"]
        assert [entry.status for entry in entries] == [JobStatus.FAILED, JobStatus.COMPLETED]


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
        
