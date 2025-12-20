"""Tests for duration tracking in job history and timing features."""

from datetime import datetime, timedelta

from src.history.duration_stats import DurationStats
from src.queue.job_history_store import JobHistoryEntry, JSONLJobHistoryStore
from src.queue.job_model import Job, JobPriority, JobStatus


def test_duration_ms_calculated_and_persisted(tmp_path):
    """Test that duration_ms is calculated when job completes and persisted to history."""
    store = JSONLJobHistoryStore(tmp_path / "history.jsonl")
    job = Job(job_id="timed-job", priority=JobPriority.NORMAL)

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


def test_duration_ms_roundtrip_serialization(tmp_path):
    """Test that duration_ms survives JSON serialization/deserialization."""
    history_path = tmp_path / "history.jsonl"
    store = JSONLJobHistoryStore(history_path)

    start_time = datetime.utcnow()
    end_time = start_time + timedelta(seconds=5.3)

    entry = JobHistoryEntry(
        job_id="test-job",
        created_at=start_time,
        started_at=start_time,
        completed_at=end_time,
        status=JobStatus.COMPLETED,
        duration_ms=5300,
    )

    # Serialize and write
    json_str = entry.to_json()
    history_path.write_text(json_str + "\n", encoding="utf-8")

    # Load back
    loaded = store.list_jobs()
    assert len(loaded) == 1
    assert loaded[0].duration_ms == 5300


def test_duration_stats_calculates_average():
    """Test that DurationStats can calculate average duration from history."""
    stats = DurationStats()

    # Create mock history entries with known durations
    entries = [
        JobHistoryEntry(
            job_id=f"job-{i}",
            created_at=datetime.utcnow(),
            status=JobStatus.COMPLETED,
            duration_ms=duration,
        )
        for i, duration in enumerate([1000, 2000, 3000, 4000, 5000])
    ]

    stats.load_history(entries)

    avg = stats.get_average_duration_ms()
    assert avg == 3000  # (1000+2000+3000+4000+5000) / 5


def test_duration_stats_ignores_none_durations():
    """Test that DurationStats ignores entries without duration_ms."""
    stats = DurationStats()

    entries = [
        JobHistoryEntry(
            job_id="job-1",
            created_at=datetime.utcnow(),
            status=JobStatus.COMPLETED,
            duration_ms=2000,
        ),
        JobHistoryEntry(
            job_id="job-2",
            created_at=datetime.utcnow(),
            status=JobStatus.COMPLETED,
            duration_ms=None,  # No duration
        ),
        JobHistoryEntry(
            job_id="job-3",
            created_at=datetime.utcnow(),
            status=JobStatus.COMPLETED,
            duration_ms=4000,
        ),
    ]

    stats.load_history(entries)

    avg = stats.get_average_duration_ms()
    assert avg == 3000  # Only averages entries with duration_ms


def test_duration_stats_format_duration_ms():
    """Test duration formatting to human-readable strings."""
    stats = DurationStats()

    # Less than 60 seconds
    assert stats.format_duration_ms(5000) == "5s"
    assert stats.format_duration_ms(45000) == "45s"

    # Minutes and seconds
    assert stats.format_duration_ms(90000) == "1m 30s"
    assert stats.format_duration_ms(125000) == "2m 5s"

    # Hours
    assert stats.format_duration_ms(3661000) == "1h 1m"
    assert stats.format_duration_ms(7380000) == "2h 3m"

    # Edge cases
    assert stats.format_duration_ms(None) == "-"
    assert stats.format_duration_ms(0) == "-"
    assert stats.format_duration_ms(-100) == "-"


def test_duration_not_calculated_for_failed_jobs(tmp_path):
    """Test that duration is still calculated for failed jobs."""
    store = JSONLJobHistoryStore(tmp_path / "history.jsonl")
    job = Job(job_id="failed-job", priority=JobPriority.NORMAL)

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

