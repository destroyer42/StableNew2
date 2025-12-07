"""Queue helpers for converting JobService Job models into UI-ready objects."""

from __future__ import annotations

from datetime import datetime

from src.pipeline.job_models_v2 import JobStatusV2, QueueJobV2
from src.queue.job_model import Job, JobStatus


def job_to_queue_job(job: Job) -> QueueJobV2:
    """Convert a JobService Job into a QueueJobV2 for GUI consumption."""

    status_value = JobStatusV2.QUEUED
    if isinstance(job.status, JobStatus):
        try:
            status_value = JobStatusV2(job.status.value)
        except ValueError:
            status_value = JobStatusV2.QUEUED
    elif isinstance(job.status, str):
        try:
            status_value = JobStatusV2(job.status)
        except ValueError:
            status_value = JobStatusV2.QUEUED

    created_at = job.created_at if job.created_at else datetime.now()
    metadata = {
        "source": job.source,
        "run_mode": job.run_mode,
    }
    queue_job = QueueJobV2(
        job_id=job.job_id,
        config_snapshot=job.config_snapshot or {},
        status=status_value,
        created_at=created_at,
        started_at=job.started_at,
        completed_at=job.completed_at,
        progress=getattr(job, "progress", 0.0) or 0.0,
        eta_seconds=getattr(job, "eta_seconds", None),
        error_message=job.error_message,
        metadata=metadata,
    )
    return queue_job
