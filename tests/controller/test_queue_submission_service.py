from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import Mock

from src.controller.pipeline_controller_services.queue_submission_service import (
    QueueSubmissionService,
)
from tests.helpers.job_helpers import make_test_njr


def test_split_queueable_records_rejects_pack_rows_without_pack_id() -> None:
    service = QueueSubmissionService(job_service=Mock())
    queueable, non_queueable = service.split_queueable_records(
        [
            make_test_njr(prompt_source="pack", prompt_pack_id="pack-a"),
            make_test_njr(prompt_source="pack", prompt_pack_id=""),
            make_test_njr(prompt_source="manual", prompt_pack_id=""),
        ]
    )

    assert len(queueable) == 2
    assert len(non_queueable) == 1


def test_submit_normalized_jobs_uses_coalesced_batch_updates() -> None:
    batch_entries: list[str] = []

    class _QueueBatchSpy:
        def coalesce_state_notifications(self):
            class _Context:
                def __enter__(self_inner):
                    batch_entries.append("enter")
                    return self_inner

                def __exit__(self_inner, exc_type, exc, tb):
                    batch_entries.append("exit")
                    return False

            return _Context()

    job_service = Mock()
    job_service.job_queue = _QueueBatchSpy()
    service = QueueSubmissionService(job_service=job_service)
    fake_jobs = [Mock(payload=None), Mock(payload=None)]
    to_queue_job = Mock(side_effect=fake_jobs)

    submitted = service.submit_normalized_jobs(
        [
            make_test_njr(prompt_source="manual", prompt_pack_id="pack-a"),
            make_test_njr(prompt_source="manual", prompt_pack_id="pack-b"),
        ],
        run_config=None,
        source="gui",
        prompt_source="manual",
        last_run_config=None,
        can_enqueue_learning_jobs=lambda count: (True, ""),
        is_queue_submission_blocked=lambda: False,
        sort_jobs_by_model=lambda rows: rows,
        ensure_record_prompt_pack_metadata=lambda *_args: None,
        to_queue_job=to_queue_job,
        log_add_to_queue_event=lambda _job_id: None,
        run_job_payload_factory=lambda job: (lambda j=job: {"job_id": j.job_id}),
    )

    assert submitted == 2
    assert batch_entries == ["enter", "exit"]
    assert job_service.submit_job_with_run_mode.call_count == 2
    job_service._emit_queue_updated.assert_called_once_with()


def test_submit_normalized_jobs_stops_mid_batch_when_shutdown_starts() -> None:
    job_service = Mock()
    service = QueueSubmissionService(job_service=job_service)
    fake_jobs = [Mock(payload=None), Mock(payload=None), Mock(payload=None)]
    to_queue_job = Mock(side_effect=fake_jobs)
    shutdown_state = SimpleNamespace(active=False)
    submitted_jobs: list[Mock] = []

    def _submit(job, emit_queue_updated=False):
        submitted_jobs.append(job)
        shutdown_state.active = True

    job_service.submit_job_with_run_mode.side_effect = _submit

    submitted = service.submit_normalized_jobs(
        [
            make_test_njr(prompt_source="manual", prompt_pack_id="pack-a"),
            make_test_njr(prompt_source="manual", prompt_pack_id="pack-b"),
            make_test_njr(prompt_source="manual", prompt_pack_id="pack-c"),
        ],
        run_config=None,
        source="gui",
        prompt_source="manual",
        last_run_config=None,
        can_enqueue_learning_jobs=lambda count: (True, ""),
        is_queue_submission_blocked=lambda: bool(shutdown_state.active),
        sort_jobs_by_model=lambda rows: rows,
        ensure_record_prompt_pack_metadata=lambda *_args: None,
        to_queue_job=to_queue_job,
        log_add_to_queue_event=lambda _job_id: None,
        run_job_payload_factory=lambda job: (lambda j=job: {"job_id": j.job_id}),
    )

    assert submitted == 1
    assert submitted_jobs == [fake_jobs[0]]
    assert to_queue_job.call_count == 1
    job_service._emit_queue_updated.assert_called_once_with()


def test_submit_normalized_jobs_blocks_learning_source_over_cap() -> None:
    job_service = Mock()
    service = QueueSubmissionService(job_service=job_service)

    submitted = service.submit_normalized_jobs(
        [make_test_njr(prompt_source="manual", prompt_pack_id="")],
        run_config=None,
        source="learning_auto_micro",
        prompt_source="manual",
        last_run_config=None,
        can_enqueue_learning_jobs=lambda count: (False, "queue cap exceeded"),
        is_queue_submission_blocked=lambda: False,
        sort_jobs_by_model=lambda rows: rows,
        ensure_record_prompt_pack_metadata=lambda *_args: None,
        to_queue_job=Mock(),
        log_add_to_queue_event=lambda _job_id: None,
    )

    assert submitted == 0
    job_service.submit_job_with_run_mode.assert_not_called()
