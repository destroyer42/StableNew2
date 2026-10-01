"""Tests covering retry metadata captured by JobService (Phase 7)."""

from __future__ import annotations

from src.queue.single_node_runner import _ensure_job_envelope
from tests.helpers.njr_factory import make_queue_job


def test_job_service_retry_metadata_survives_envelope(job_service_with_stub_runner_factory):
    service, queue, _ = job_service_with_stub_runner_factory
    job = make_queue_job("retry-metadata")
    queue.submit(job)

    service.record_retry_attempt(job.job_id, "txt2img", 1, 3, "TimeoutError")
    service.record_retry_attempt(job.job_id, "txt2img", 2, 3, "TimeoutError")

    assert len(job.execution_metadata.retry_attempts) == 2

    exc = RuntimeError("boom")
    _ensure_job_envelope(job, exc)

    assert job.error_envelope is not None
    assert job.error_envelope.retry_info
    attempts = job.error_envelope.retry_info["attempts"]
    assert attempts[-1]["attempt_index"] == 2
    assert attempts[-1]["reason"] == "TimeoutError"
