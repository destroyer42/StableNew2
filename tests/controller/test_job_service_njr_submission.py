from __future__ import annotations

import pytest

from src.controller.job_service import JobService
from src.controller.submission_policy_v26 import SubmissionPolicy
from src.queue.job_model import JobPriority
from src.queue.job_queue import JobQueue
from tests.helpers.job_helpers import make_test_njr


class _Runner:
    def __init__(self, queue: JobQueue) -> None:
        self.job_queue = queue
        self.started = False

    def start(self) -> None:
        self.started = True

    def stop(self) -> None:
        self.started = False

    def is_running(self) -> bool:
        return self.started

    def run_once(self, job):
        return {"success": True}

    def cancel_current(self, *, return_to_queue: bool = False) -> None:
        return None


def _service() -> tuple[JobService, _Runner]:
    queue = JobQueue()
    runner = _Runner(queue)
    return JobService(queue, runner=runner), runner


def test_submit_njrs_derives_source_and_keeps_pack_identity_conditional() -> None:
    service, _runner = _service()
    records = [make_test_njr(prompt_source="manual", prompt_pack_id="")]

    job_ids = service.submit_njrs(records)

    assert job_ids == [records[0].job_id]
    job = service.job_queue.get_job(job_ids[0])
    assert job is not None
    assert job.prompt_pack_id is None
    assert job.source == records[0].source.kind.value


def test_submit_njrs_validates_duplicate_batch_before_queue_write() -> None:
    service, _runner = _service()
    record = make_test_njr(prompt_source="manual", prompt_pack_id="")

    with pytest.raises(ValueError, match="duplicate"):
        service.submit_njrs([record, record])

    assert service.job_queue.list_jobs() == []


def test_run_now_is_a_submission_policy() -> None:
    service, runner = _service()
    record = make_test_njr(prompt_source="manual", prompt_pack_id="")

    service.submit_njrs(
        [record],
        SubmissionPolicy(priority=JobPriority.HIGH, start_when_idle=True),
    )

    assert runner.started is True
    job = service.job_queue.get_job(record.job_id)
    assert job is not None
    assert job.priority is JobPriority.HIGH
    assert job.run_mode == "queue"
