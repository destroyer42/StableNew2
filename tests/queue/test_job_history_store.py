from datetime import datetime

from src.queue.job_history_store import JSONLJobHistoryStore
from src.queue.job_model import Job, JobPriority, JobStatus


def test_job_history_records_submission_and_status(tmp_path):
    store = JSONLJobHistoryStore(tmp_path / "history.jsonl")
    job = Job(job_id="job-1", priority=JobPriority.NORMAL, worker_id="local")

    store.record_job_submission(job)
    run_ts = datetime.utcnow()
    store.record_status_change(job.job_id, JobStatus.RUNNING, run_ts)
    store.record_status_change(job.job_id, JobStatus.COMPLETED, run_ts)

    entries = store.list_jobs()
    assert len(entries) == 1
    entry = entries[0]
    assert entry.job_id == "job-1"
    assert entry.status == JobStatus.COMPLETED
    assert entry.started_at is not None
    assert entry.completed_at is not None
    assert entry.worker_id == "local"
    assert entry.run_mode == "queue"


def test_job_history_filters_by_status(tmp_path):
    store = JSONLJobHistoryStore(tmp_path / "history.jsonl")
    job1 = Job(job_id="job-1", priority=JobPriority.NORMAL)
    job2 = Job(job_id="job-2", priority=JobPriority.NORMAL)

    store.record_job_submission(job1)
    store.record_status_change(job1.job_id, JobStatus.FAILED, datetime.utcnow(), error="boom")

    store.record_job_submission(job2)
    store.record_status_change(job2.job_id, JobStatus.RUNNING, datetime.utcnow())

    failed = store.list_jobs(status=JobStatus.FAILED)
    running = store.list_jobs(status=JobStatus.RUNNING)

    assert {e.job_id for e in failed} == {"job-1"}
    assert {e.job_id for e in running} == {"job-2"}


def test_job_history_persists_run_mode(tmp_path):
    store = JSONLJobHistoryStore(tmp_path / "history.jsonl")
    job = Job(job_id="job-direct", priority=JobPriority.NORMAL, run_mode="direct")

    store.record_job_submission(job)
    store.record_status_change(job.job_id, JobStatus.COMPLETED, datetime.utcnow())

    entry = store.list_jobs()[0]
    assert entry.run_mode == "direct"
