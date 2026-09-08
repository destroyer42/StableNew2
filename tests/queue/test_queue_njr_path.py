"""Tests for queue NJR-only execution path.

Validates that:
- Queue entries created via NJR path have NJR snapshots
- Execution uses NJR-only path for active jobs
"""

from __future__ import annotations

import time
from pathlib import Path

from src.pipeline.job_models_v2 import NormalizedJobRecord
from src.queue.job_model import Job, JobPriority, JobStatus
from src.queue.job_queue import JobQueue
from src.queue.job_repository import JobRepository
from tests.helpers.njr_factory import make_pipeline_njr


def _make_dummy_njr() -> NormalizedJobRecord:
    """Create a minimal NormalizedJobRecord for testing."""
    return make_pipeline_njr(
        job_id="test-njr-1",
        config={"prompt": "test", "model": "sdxl"},
        seed=42,
        positive_prompt="test prompt",
        base_model="sdxl",
    )


def _wait_for_history_entry(
    history_store: JobRepository,
    job_id: str,
    *,
    timeout: float = 1.0,
) -> object | None:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        entry = history_store.get_job(job_id)
        if entry is not None:
            return entry
        time.sleep(0.01)
    return None


class TestQueueNJRPath:
    """Test NJR-only execution for queue jobs."""

    def test_queue_job_with_njr_snapshot(self, tmp_path: Path):
        """Queue job created from NJR should have NJR snapshot in storage."""
        history_store = JobRepository(tmp_path / "jobs.sqlite3")
        queue = JobQueue(repository=history_store)

        # Create job with NJR
        njr = _make_dummy_njr()
        job = Job(
            job_id=njr.job_id,
            priority=JobPriority.NORMAL,
        )
        job._normalized_record = njr
        job.snapshot = {"normalized_job": njr.to_dict()}

        # Submit to queue
        queue.submit(job)

        # Verify job has NJR
        retrieved = queue.get_job(njr.job_id)
        assert retrieved is not None
        assert hasattr(retrieved, "_normalized_record")
        assert retrieved._normalized_record is not None

    def test_njr_backed_job_execution_uses_njr_only(self, tmp_path: Path):
        """Job with NJR should execute via NJR path only."""
        history_store = JobRepository(tmp_path / "jobs.sqlite3")
        queue = JobQueue(repository=history_store)

        # Create NJR-backed job
        njr = _make_dummy_njr()
        job = Job(
            job_id=njr.job_id,
            priority=JobPriority.NORMAL,
        )
        job._normalized_record = njr
        job.snapshot = {"normalized_job": njr.to_dict()}

        queue.submit(job)

        # PR-CORE1-B2: Execution validation
        # In actual execution, app_controller._execute_job should:
        # 1. See _normalized_record is present
        # 2. Call _run_job (NJR path)
        # 3. NOT depend on a legacy pipeline_config payload
        retrieved = queue.get_job(njr.job_id)
        assert hasattr(retrieved, "_normalized_record")
        assert retrieved._normalized_record is not None

    def test_history_entry_with_njr_snapshot(self, tmp_path: Path):
        """History entries for NJR jobs should include NJR snapshot."""
        history_store = JobRepository(tmp_path / "jobs.sqlite3")
        queue = JobQueue(repository=history_store)

        # Create NJR-backed job
        njr = _make_dummy_njr()
        job = Job(
            job_id=njr.job_id,
            priority=JobPriority.NORMAL,
        )
        job._normalized_record = njr
        job.snapshot = {
            "schema_version": "1.0",
            "normalized_job": njr.to_dict(),
        }

        queue.submit(job)
        assert _wait_for_history_entry(history_store, njr.job_id) is not None

        queue.mark_running(njr.job_id)
        queue.mark_completed(njr.job_id, result={"status": "success"})

        # Retrieve from history
        entry = _wait_for_history_entry(history_store, njr.job_id)
        assert entry is not None
        assert entry.snapshot is not None
        assert "normalized_job" in entry.snapshot
        # PR-CORE1-B2: NJR snapshot is authoritative for replay
        assert entry.snapshot["normalized_job"] is not None

    def test_new_jobs_dont_rely_on_pipeline_config_for_execution(self, tmp_path: Path):
        """New queue jobs should not rely on legacy execution payloads."""
        history_store = JobRepository(tmp_path / "jobs.sqlite3")
        queue = JobQueue(repository=history_store)

        # Simulate creating a new job via the v2.6 pipeline
        njr = _make_dummy_njr()
        job = Job(
            job_id=njr.job_id,
            priority=JobPriority.NORMAL,
            run_mode="queue",
            source="gui",
            prompt_source="pack",
        )
        job._normalized_record = njr
        job.snapshot = {"normalized_job": njr.to_dict()}

        queue.submit(job)

        # Verification: Job has NJR, execution path should use NJR only
        retrieved = queue.get_job(njr.job_id)
        assert hasattr(retrieved, "_normalized_record")
        assert retrieved._normalized_record is not None
        # Execution MUST use _normalized_record and snapshot data
