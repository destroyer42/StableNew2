from __future__ import annotations

from src.controller.job_service import JobService
from src.queue.job_model import JobStatus
from src.queue.job_queue import JobQueue
from src.queue.single_node_runner import SingleNodeJobRunner
from tests.helpers.job_helpers import make_test_job_from_njr, make_test_njr


def _job_service_with_stub_runner(queue: JobQueue) -> JobService:
    runner = SingleNodeJobRunner(queue, run_callable=lambda job: {"ok": True}, poll_interval=0.01)
    return JobService(job_queue=queue, runner=runner, require_normalized_records=True)


def test_pack_job_missing_pack_id_fails_gracefully() -> None:
    queue = JobQueue()
    service = _job_service_with_stub_runner(queue)
    njr = make_test_njr(prompt_pack_id="", prompt_source="pack")
    job = make_test_job_from_njr(njr)

    service.submit_job_with_run_mode(job)

    assert job.status == JobStatus.FAILED
    assert job.error_message
    assert job.result and job.result.get("code") == "pack_required"


def test_manual_job_without_pack_id_runs() -> None:
    queue = JobQueue()
    service = _job_service_with_stub_runner(queue)
    njr = make_test_njr(prompt_source="manual", prompt_pack_id="")
    job = make_test_job_from_njr(njr, prompt_source="manual")

    service.submit_job_with_run_mode(job)

    # Manual jobs without pack metadata are rejected under pack-only model
    assert job.status == JobStatus.FAILED
    assert job.result and job.result.get("code") == "pack_required"
