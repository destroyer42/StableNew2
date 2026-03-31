from __future__ import annotations

from unittest.mock import Mock

from src.controller.pipeline_submission_service import PipelinePreviewSubmissionService
from tests.helpers.job_helpers import make_test_njr


def test_submit_preview_jobs_stamps_shared_submission_batch_id() -> None:
    job_service = Mock()
    service = PipelinePreviewSubmissionService(
        job_service=job_service,
        run_job_callback=lambda _job: {},
        learning_enabled=False,
    )
    records = [
        make_test_njr(job_id="job-1", prompt_source="pack", prompt_pack_id="pack-a"),
        make_test_njr(job_id="job-2", prompt_source="pack", prompt_pack_id="pack-b"),
    ]

    result = service.submit_preview_jobs(
        records,
        run_mode="queue",
        source="gui",
        prompt_source="pack",
        prompt_pack_id="pack-a",
        last_run_config=None,
    )

    batch_ids = {
        str(getattr(record, "extra_metadata", {}).get("submission_batch_id") or "")
        for record in records
    }

    assert result is not None
    assert result.submitted_jobs == 2
    assert len(batch_ids) == 1
    assert "" not in batch_ids
    job_service.submit_jobs_with_run_mode.assert_called_once()