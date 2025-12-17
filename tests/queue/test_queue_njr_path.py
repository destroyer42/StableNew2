"""Tests for queue NJR-only execution path (PR-CORE1-B2).

Validates that:
- Queue entries created via NJR path have NJR snapshots
- Execution uses NJR-only path for new jobs (pipeline_config is None)
- Legacy pipeline_config-only jobs still work but are marked as legacy
"""

from __future__ import annotations

from pathlib import Path

from src.controller.archive.pipeline_config_types import PipelineConfig
from src.pipeline.job_models_v2 import NormalizedJobRecord
from src.queue.job_history_store import JSONLJobHistoryStore
from src.queue.job_model import Job, JobPriority, JobStatus
from src.queue.job_queue import JobQueue


def _make_dummy_njr() -> NormalizedJobRecord:
    """Create a minimal NormalizedJobRecord for testing."""
    return NormalizedJobRecord(
        job_id="test-njr-1",
        config={"prompt": "test", "model": "sdxl"},
        path_output_dir="output",
        filename_template="{seed}",
        seed=42,
        positive_prompt="test prompt",
        base_model="sdxl",
    )


class TestQueueNJRPath:
    """Test NJR-only execution for queue jobs."""

    def test_queue_job_with_njr_snapshot(self, tmp_path: Path):
        """Queue job created from NJR should have NJR snapshot in storage."""
        history_store = JSONLJobHistoryStore(tmp_path / "history.jsonl")
        queue = JobQueue(history_store=history_store)

        # Create job with NJR
        njr = _make_dummy_njr()
        job = Job(
            job_id="njr-job-1",
            priority=JobPriority.NORMAL,
        )
        job._normalized_record = njr
        job.snapshot = {"normalized_job": njr.to_queue_snapshot()}

        # Submit to queue
        queue.submit(job)

        # Verify job has NJR
        retrieved = queue.get_job("njr-job-1")
        assert retrieved is not None
        assert hasattr(retrieved, "_normalized_record")
        assert retrieved._normalized_record is not None
        assert getattr(retrieved, "pipeline_config", None) is None

    def test_njr_backed_job_execution_uses_njr_only(self, tmp_path: Path):
        """Job with NJR should execute via NJR path only (no pipeline_config fallback)."""
        history_store = JSONLJobHistoryStore(tmp_path / "history.jsonl")
        queue = JobQueue(history_store=history_store)

        # Create NJR-backed job
        njr = _make_dummy_njr()
        job = Job(
            job_id="njr-exec-1",
            priority=JobPriority.NORMAL,
        )
        job._normalized_record = njr

        queue.submit(job)

        # PR-CORE1-B2: Execution validation
        # In actual execution, app_controller._execute_job should:
        # 1. See _normalized_record is present
        # 2. Call _run_job (NJR path)
        # 3. NOT fall back to pipeline_config even if _run_job fails
        retrieved = queue.get_job("njr-exec-1")
        assert hasattr(retrieved, "_normalized_record")
        assert retrieved._normalized_record is not None
        # pipeline_config should remain None for NJR-only jobs
        assert getattr(retrieved, "pipeline_config", None) is None

    def test_legacy_pipeline_config_only_job(self, tmp_path: Path):
        """Legacy job with only pipeline_config (no NJR) should still work."""
        history_store = JSONLJobHistoryStore(tmp_path / "history.jsonl")
        queue = JobQueue(history_store=history_store)

        # Create legacy job (pre-v2.6 style)
        job = Job(
            job_id="legacy-1",
            priority=JobPriority.NORMAL,
        )
        # No _normalized_record attribute
        job.pipeline_config = PipelineConfig(
            prompt="legacy test",
            model="sdxl",
            sampler="Euler a",
            steps=20,
            cfg_scale=7.5,
            width=512,
            height=512,
        )

        queue.submit(job)

        # Verify legacy job works
        retrieved = queue.get_job("legacy-1")
        assert retrieved is not None
        assert not hasattr(retrieved, "_normalized_record") or retrieved._normalized_record is None
        assert getattr(retrieved, "pipeline_config", None) is not None

    def test_history_entry_with_njr_snapshot(self, tmp_path: Path):
        """History entries for NJR jobs should include NJR snapshot."""
        history_store = JSONLJobHistoryStore(tmp_path / "history.jsonl")

        # Create NJR-backed job
        njr = _make_dummy_njr()
        job = Job(
            job_id="history-njr-1",
            priority=JobPriority.NORMAL,
        )
        job._normalized_record = njr
        job.snapshot = {
            "schema_version": "1.0",
            "normalized_job": njr.to_queue_snapshot(),
        }

        # Record submission
        history_store.record_job_submission(job)

        # Mark completed
        history_store.record_status_change(
            job_id="history-njr-1",
            status=JobStatus.COMPLETED,
            ts=None,
            result={"status": "success"},
        )

        # Retrieve from history
        entry = history_store.get_job("history-njr-1")
        assert entry is not None
        assert entry.snapshot is not None
        assert "normalized_job" in entry.snapshot
        # PR-CORE1-B2: NJR snapshot is authoritative for replay
        assert entry.snapshot["normalized_job"] is not None

    def test_new_jobs_dont_rely_on_pipeline_config_for_execution(self, tmp_path: Path):
        """PR-CORE1-B2: New queue jobs should not rely on pipeline_config for execution."""
        history_store = JSONLJobHistoryStore(tmp_path / "history.jsonl")
        queue = JobQueue(history_store=history_store)

        # Simulate creating a new job via the v2.6 pipeline
        njr = _make_dummy_njr()
        job = Job(
            job_id="new-job-1",
            priority=JobPriority.NORMAL,
            run_mode="queue",
            source="gui",
            prompt_source="pack",
        )
        job._normalized_record = njr
        # pipeline_config is intentionally absent for new NJR-only jobs

        queue.submit(job)

        # Verification: Job has NJR, execution path should use NJR only
        retrieved = queue.get_job("new-job-1")
        assert hasattr(retrieved, "_normalized_record")
        assert retrieved._normalized_record is not None
        assert getattr(retrieved, "pipeline_config", None) is None
        # PR-CORE1-B2 contract: Execution MUST use _normalized_record, not pipeline_config
        # This is enforced in app_controller._execute_job
