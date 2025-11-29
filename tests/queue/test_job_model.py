from src.queue.job_model import Job, JobPriority, JobStatus


def test_job_defaults_include_worker_id_optional():
    job = Job(job_id="j1", pipeline_config=None, priority=JobPriority.NORMAL)
    assert job.worker_id is None
    assert job.status == JobStatus.QUEUED

    as_dict = job.to_dict()
    assert "worker_id" in as_dict
