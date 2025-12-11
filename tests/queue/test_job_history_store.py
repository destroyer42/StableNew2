from dataclasses import asdict
from datetime import datetime

from src.pipeline.job_models_v2 import NormalizedJobRecord
from src.pipeline.pipeline_runner import PipelineRunResult
from src.queue.job_history_store import JSONLJobHistoryStore
from src.queue.job_model import Job, JobPriority, JobStatus


def _make_normalized_record(job_id: str = "job-1") -> NormalizedJobRecord:
    return NormalizedJobRecord(
        job_id=job_id,
        config={},
        path_output_dir="output",
        filename_template="{seed}",
    )


def test_job_history_records_submission_and_status(tmp_path):
    store = JSONLJobHistoryStore(tmp_path / "history.jsonl")
    job = Job(job_id="job-1", priority=JobPriority.NORMAL, worker_id="local")

    store.record_job_submission(job)
    run_ts = datetime.utcnow()
    canon_result = PipelineRunResult(
        run_id=job.job_id,
        success=True,
        error=None,
        variants=[],
        learning_records=[],
        metadata={},
    ).to_dict()
    job.result = canon_result
    store.record_status_change(job.job_id, JobStatus.RUNNING, run_ts)
    store.record_status_change(job.job_id, JobStatus.COMPLETED, run_ts, result=canon_result)

    entries = store.list_jobs()
    assert len(entries) == 1
    entry = entries[0]
    assert entry.job_id == "job-1"
    assert entry.status == JobStatus.COMPLETED
    assert entry.started_at is not None
    assert entry.completed_at is not None
    assert entry.worker_id == "local"
    assert entry.run_mode == "queue"
    assert entry.result == canon_result


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


def test_history_entry_snapshot_contains_njr(tmp_path):
    store = JSONLJobHistoryStore(tmp_path / "history.jsonl")
    record = _make_normalized_record("njr-job")
    job = Job(job_id=record.job_id, priority=JobPriority.NORMAL)
    job.snapshot = {"normalized_job": asdict(record)}
    job._normalized_record = record  # type: ignore[attr-defined]

    store.record_job_submission(job)
    entry = store.list_jobs()[0]
    assert entry.snapshot is not None
    njr_snapshot = entry.snapshot.get("normalized_job")
    assert njr_snapshot == asdict(record)
    assert "pipeline_config" not in njr_snapshot
