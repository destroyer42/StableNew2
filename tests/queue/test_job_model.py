from src.queue.job_model import Job, JobPriority, JobStatus


def test_job_defaults_include_worker_id_optional():
    job = Job(job_id="j1", priority=JobPriority.NORMAL)
    assert job.worker_id is None
    assert job.status == JobStatus.QUEUED

    as_dict = job.to_dict()
    assert "worker_id" in as_dict


def test_job_dict_does_not_include_pipeline_config():
    job = Job(job_id="j2", priority=JobPriority.NORMAL)
    as_dict = job.to_dict()
    assert "pipeline_config" not in as_dict
