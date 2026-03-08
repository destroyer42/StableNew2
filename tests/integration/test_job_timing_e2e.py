"""Integration tests for job timing features end-to-end."""

from datetime import datetime, timedelta

from src.history.duration_stats import DurationStats
from src.queue.job_history_store import JobHistoryEntry, JSONLJobHistoryStore
from src.queue.job_model import Job, JobPriority, JobStatus


def test_end_to_end_job_timing_flow(tmp_path):
    """Test complete flow: job submission → execution → history with timing."""
    # Setup
    history_store = JSONLJobHistoryStore(tmp_path / "history.jsonl")

    # Create and submit a job
    job = Job(job_id="integration-test-job", priority=JobPriority.NORMAL)
    job.snapshot = {"normalized_job": {"job_id": "integration-test-job"}}

    # Record submission
    history_store.record_job_submission(job)

    # Simulate execution
    start_time = datetime.utcnow()
    history_store.record_status_change(job.job_id, JobStatus.RUNNING, start_time)

    # Simulate completion after 3 seconds
    end_time = start_time + timedelta(seconds=3)
    history_store.record_status_change(job.job_id, JobStatus.COMPLETED, end_time)

    # Verify history entry has timing
    entries = history_store.list_jobs()
    assert len(entries) == 1
    entry = entries[0]

    assert entry.started_at is not None
    assert entry.completed_at is not None
    assert entry.duration_ms is not None
    assert 2900 <= entry.duration_ms <= 3100  # ~3000ms

    # Verify duration stats can calculate from history
    stats = DurationStats()
    stats.load_history(entries)
    avg = stats.get_average_duration_ms()
    assert avg is not None
    assert 2900 <= avg <= 3100


def test_duration_stats_handles_large_history():
    """Test that DurationStats handles large history files efficiently."""
    stats = DurationStats()

    # Create 1000 mock history entries
    large_history = [
        JobHistoryEntry(
            job_id=f"job-{i}",
            created_at=datetime.utcnow(),
            status=JobStatus.COMPLETED,
            duration_ms=1000 + (i % 100),  # Vary durations 1000-1099ms
        )
        for i in range(1000)
    ]

    stats.load_history(large_history)

    # Should filter to only entries with duration
    avg = stats.get_average_duration_ms()
    assert avg is not None
    # Average should be around middle of range (1000-1099)
    assert 1040 <= avg <= 1060


def test_job_timing_edge_case_very_fast_completion(tmp_path):
    """Test jobs that complete in <1ms."""
    store = JSONLJobHistoryStore(tmp_path / "history.jsonl")
    job = Job(job_id="fast-job", priority=JobPriority.NORMAL)

    store.record_job_submission(job)

    # Job starts and completes in same microsecond (edge case)
    start_time = datetime.utcnow()
    store.record_status_change(job.job_id, JobStatus.RUNNING, start_time)
    store.record_status_change(job.job_id, JobStatus.COMPLETED, start_time)

    entries = store.list_jobs()
    entry = entries[0]

    # Duration should be 0ms (or very close)
    assert entry.duration_ms is not None
    assert entry.duration_ms >= 0
    assert entry.duration_ms < 100  # Less than 100ms


def test_job_timing_edge_case_long_running(tmp_path):
    """Test jobs running for extended periods (days)."""
    store = JSONLJobHistoryStore(tmp_path / "history.jsonl")
    job = Job(job_id="long-job", priority=JobPriority.NORMAL)

    store.record_job_submission(job)

    start_time = datetime.utcnow()
    store.record_status_change(job.job_id, JobStatus.RUNNING, start_time)

    # Job runs for 2 days
    end_time = start_time + timedelta(days=2, hours=3, minutes=15)
    store.record_status_change(job.job_id, JobStatus.COMPLETED, end_time)

    entries = store.list_jobs()
    entry = entries[0]

    # 2 days + 3 hours + 15 minutes = 48*3600 + 3*3600 + 15*60 = 184500 seconds
    expected_ms = 184500 * 1000
    assert entry.duration_ms is not None
    assert abs(entry.duration_ms - expected_ms) < 1000  # Within 1 second tolerance

    # Test formatting
    stats = DurationStats()
    formatted = stats.format_duration_ms(entry.duration_ms)
    assert "51h" in formatted  # 51 hours + 15 minutes


def test_gui_duration_formatting_consistency(tmp_path):
    """Test that GUI panel formatting methods produce consistent output."""
    from src.gui.job_history_panel_v2 import JobHistoryPanelV2

    # Test various durations match expected format
    test_cases = [
        (500, "0s"),       # Less than 1 second
        (5000, "5s"),      # 5 seconds
        (45000, "45s"),    # 45 seconds
        (90000, "1m 30s"), # 1.5 minutes
        (3661000, "1h 1m"), # Just over 1 hour
    ]

    for duration_ms, expected in test_cases:
        result = JobHistoryPanelV2._format_duration_ms(duration_ms)
        assert result == expected, f"Duration {duration_ms}ms formatted as '{result}', expected '{expected}'"


def test_running_job_elapsed_time_calculation():
    """Test elapsed time calculation in running job panel."""
    from src.gui.panels_v2.running_job_panel_v2 import RunningJobPanelV2

    # Mock a job that started 65 seconds ago
    started_at = datetime.utcnow() - timedelta(seconds=65)

    # Test formatting (should show "Elapsed: 1m 5s")
    elapsed_text = RunningJobPanelV2._format_elapsed(None, started_at)

    assert elapsed_text.startswith("Elapsed:")
    assert "1m" in elapsed_text or "65s" in elapsed_text  # Depends on exact timing

    # Test None case
    assert RunningJobPanelV2._format_elapsed(None, None) == ""


def test_queue_eta_estimation_placeholder():
    """Test queue ETA estimation (currently placeholder at 60s per job)."""
    from src.gui.panels_v2.queue_panel_v2 import QueuePanelV2

    # Test with various queue sizes
    test_cases = [
        (1, 60),      # 1 job = 60s
        (5, 300),     # 5 jobs = 300s = 5m
        (120, 7200),  # 120 jobs = 7200s = 2h
    ]

    for _job_count, expected_seconds in test_cases:
        # Placeholder estimate is 60s per job
        eta_text = QueuePanelV2._format_queue_eta(None, expected_seconds)
        assert "Est. total:" in eta_text

        # Verify reasonable formatting
        if expected_seconds < 60:
            assert "s" in eta_text
        elif expected_seconds < 3600:
            assert "m" in eta_text
        else:
            assert "h" in eta_text

