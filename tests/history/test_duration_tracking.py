"""Tests for duration tracking in job history and timing features."""

from datetime import datetime, timedelta

from src.queue.job_model import JobStatus
from src.queue.job_repository import JobRepository
from tests.helpers.njr_factory import make_queue_job


def test_duration_ms_calculated_and_persisted(tmp_path):
    """Test that duration_ms is calculated when job completes and persisted to history."""
    store = JobRepository(tmp_path / "jobs.sqlite3")
    job = make_queue_job("timed-job")

    # Record submission
    store.record_job_submission(job)

    # Start the job
    start_time = datetime.utcnow()
    store.record_status_change(job.job_id, JobStatus.RUNNING, start_time)

    # Complete the job 2.5 seconds later
    end_time = start_time + timedelta(seconds=2.5)
    store.record_status_change(job.job_id, JobStatus.COMPLETED, end_time)

    # Verify duration was calculated
    entries = store.list_jobs()
    assert len(entries) == 1
    entry = entries[0]

    assert entry.duration_ms is not None
    # Should be approximately 2500ms (2.5 seconds)
    assert 2400 <= entry.duration_ms <= 2600


def test_duration_not_calculated_for_failed_jobs(tmp_path):
    """Test that duration is still calculated for failed jobs."""
    store = JobRepository(tmp_path / "jobs.sqlite3")
    job = make_queue_job("failed-job")

    store.record_job_submission(job)

    start_time = datetime.utcnow()
    store.record_status_change(job.job_id, JobStatus.RUNNING, start_time)

    end_time = start_time + timedelta(seconds=1.5)
    store.record_status_change(
        job.job_id,
        JobStatus.FAILED,
        end_time,
        error="Test failure",
    )

    entries = store.list_jobs()
    entry = entries[0]

    # Even failed jobs should have duration tracked
    assert entry.duration_ms is not None
    assert 1400 <= entry.duration_ms <= 1600
