from __future__ import annotations

from unittest.mock import Mock

from src.controller.pipeline_controller_services.queue_submission_service import (
    QueueSubmissionService,
)
from src.controller.submission_policy_v26 import SubmissionPolicy
from tests.helpers.job_helpers import make_test_njr


def test_split_queueable_records_accepts_only_valid_njr_sources() -> None:
    service = QueueSubmissionService(job_service=Mock())
    queueable, non_queueable = service.split_queueable_records(
        [
            make_test_njr(prompt_source="pack", prompt_pack_id="pack-a"),
            make_test_njr(prompt_source="manual", prompt_pack_id=""),
        ]
    )

    assert len(queueable) == 2
    assert non_queueable == []


def test_submit_normalized_jobs_delegates_complete_njr_batch() -> None:
    job_service = Mock()
    job_service.submit_njrs.return_value = ["job-1", "job-2"]
    service = QueueSubmissionService(job_service=job_service)
    records = [
        make_test_njr(prompt_source="manual", prompt_pack_id=""),
        make_test_njr(prompt_source="manual", prompt_pack_id=""),
    ]

    submitted = service.submit_normalized_jobs(
        records,
        policy=SubmissionPolicy(),
        can_enqueue_learning_jobs=lambda count: (True, ""),
        is_queue_submission_blocked=lambda: False,
        sort_jobs_by_model=lambda rows: rows,
    )

    assert submitted == 2
    job_service.submit_njrs.assert_called_once_with(records, SubmissionPolicy())


def test_submit_normalized_jobs_blocks_learning_source_over_cap() -> None:
    job_service = Mock()
    service = QueueSubmissionService(job_service=job_service)

    submitted = service.submit_normalized_jobs(
        [make_test_njr(prompt_source="learning", prompt_pack_id="")],
        policy=SubmissionPolicy(),
        can_enqueue_learning_jobs=lambda count: (False, "queue cap exceeded"),
        is_queue_submission_blocked=lambda: False,
        sort_jobs_by_model=lambda rows: rows,
    )

    assert submitted == 0
    job_service.submit_njrs.assert_not_called()
