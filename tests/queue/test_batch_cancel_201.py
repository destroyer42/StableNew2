"""PR-BATCH-OPS-201: Cancel Remaining acts only on still-QUEUED members of the selected batch."""

from __future__ import annotations

import threading
from collections import Counter

import pytest

from src.controller.batch_operations_service import BatchOperationRefused
from src.queue.batch_membership import BatchKey, BatchKind
from src.queue.dispatch_evidence import NEVER_INVOKED
from src.queue.job_model import JobStatus
from src.queue.job_repository import InvalidLifecycleTransition, JobStatusChanged
from tests.helpers.batch_ops_201 import (
    admit,
    make_stack,
    plain_njr,
    review_njr,
    status_of,
    video_njr,
)

A = BatchKey(BatchKind.VIDEO_WORKFLOW, "batch-a")
B = BatchKey(BatchKind.REVIEW, "batch-b")


@pytest.fixture
def stack(tmp_path):
    return make_stack(tmp_path)


def _populate(stack, *, a=8, b=5, ordinary=2):
    a_jobs = [video_njr(f"a{i:02d}", "batch-a", i, a) for i in range(a)]
    b_jobs = [review_njr(f"b{i:02d}", "batch-b", source_count=b) for i in range(b)]
    admit(stack, a_jobs + b_jobs + [plain_njr(f"o{i}") for i in range(ordinary)])
    return [j.job_id for j in a_jobs], [j.job_id for j in b_jobs]


# ------------------------------------------------------------------ scope (11, 13)


def test_only_queued_members_of_the_selected_batch_are_cancelled(stack):
    a_ids, b_ids = _populate(stack)
    # a00 completes, a01 fails, a02 is RUNNING; the rest of A is still queued.
    for ordinal in range(3):
        job = stack.queue.claim_next_job()
        assert job.job_id == a_ids[ordinal]
        if ordinal == 0:
            stack.queue.mark_completed(job.job_id, {"success": True})
        elif ordinal == 1:
            stack.queue.mark_failed(job.job_id, "synthetic")
    running = stack.queue.get_job(a_ids[2])
    notified: list[tuple[str, JobStatus]] = []
    stack.queue.register_status_callback(lambda job, status: notified.append((job.job_id, status)))
    cleanups: list[str] = []
    stack.service.cleanup_external_processes = lambda job_id, reason=None: cleanups.append(job_id)

    plan = stack.operations.plan_cancel_remaining(A)
    assert plan.target_job_ids == tuple(a_ids[3:]) and plan.untouched_count == 3
    result = stack.operations.cancel_remaining(A, confirmed_job_ids=plan.target_job_ids)

    assert result.cancelled == tuple(a_ids[3:]) and not result.skipped and not result.errors
    assert [status_of(stack, j) for j in a_ids] == (
        [JobStatus.COMPLETED, JobStatus.FAILED, JobStatus.RUNNING] + [JobStatus.CANCELLED] * 5)
    # Another batch and non-batch jobs are untouched; the RUNNING job was not interrupted or cleaned up.
    assert {status_of(stack, j) for j in b_ids} == {JobStatus.QUEUED}
    assert status_of(stack, "o0") is status_of(stack, "o1") is JobStatus.QUEUED
    assert running.status is JobStatus.RUNNING and running._cancel_token is None
    assert a_ids[2] not in cleanups and stack.runner.started == 0
    # Normal status callbacks fired exactly once per cancelled job and for nothing else.
    assert Counter(notified) == Counter((j, JobStatus.CANCELLED) for j in a_ids[3:])
    assert "Cancelled 5 queued job(s)" in result.message


# ------------------------------------------------------------------ races (12)


def test_a_member_claimed_after_confirmation_is_skipped_not_cancelled(stack):
    a_ids, _ = _populate(stack)
    plan = stack.operations.plan_cancel_remaining(A)
    assert len(plan.target_job_ids) == 8
    claimed = stack.queue.claim_next_job()  # the runner claims a00 between confirmation and execution
    assert claimed.job_id == a_ids[0] and claimed.status is JobStatus.RUNNING

    result = stack.operations.cancel_remaining(A, confirmed_job_ids=plan.target_job_ids)

    assert result.cancelled == tuple(a_ids[1:])
    assert [item.job_id for item in result.skipped] == [a_ids[0]]
    assert status_of(stack, a_ids[0]) is JobStatus.RUNNING and claimed.status is JobStatus.RUNNING
    assert "1 had already started" in result.message


def test_queue_guard_skips_a_job_already_running_even_in_its_own_view(stack):
    a_ids, _ = _populate(stack, a=2, b=0, ordinary=0)
    outcome_before = stack.queue.cancel_if_queued("missing-job")
    assert (outcome_before.outcome, outcome_before.detail) == ("skipped", "unknown job")
    claimed = stack.queue.claim_next_job()
    outcome = stack.queue.cancel_if_queued(claimed.job_id, "late")
    assert outcome.outcome == "skipped" and outcome.observed_status is JobStatus.RUNNING
    assert status_of(stack, claimed.job_id) is JobStatus.RUNNING


def test_repository_transition_is_conditional_on_the_durable_status(stack):
    a_ids, _ = _populate(stack, a=2, b=0, ordinary=0)
    job = stack.repository.get_job_model(a_ids[0])
    stack.repository.transition_job(job, JobStatus.RUNNING)  # another writer wins the race
    with pytest.raises(JobStatusChanged) as raised:
        stack.repository.transition_job(job, JobStatus.CANCELLED, expected_status=JobStatus.QUEUED)
    assert raised.value.actual is JobStatus.RUNNING and isinstance(raised.value, InvalidLifecycleTransition)
    assert status_of(stack, a_ids[0]) is JobStatus.RUNNING  # no write happened
    # The ordinary (unguarded) lifecycle API is unchanged: it still allows RUNNING -> CANCELLED.
    stack.repository.transition_job(job, JobStatus.CANCELLED)
    assert status_of(stack, a_ids[0]) is JobStatus.CANCELLED


def test_stale_queue_view_cannot_cancel_a_job_the_repository_already_started(stack):
    a_ids, _ = _populate(stack, a=2, b=0, ordinary=0)
    stack.repository.transition_job(stack.repository.get_job_model(a_ids[0]), JobStatus.RUNNING)
    outcome = stack.queue.cancel_if_queued(a_ids[0])  # the queue still believes it is QUEUED
    assert outcome.outcome == "skipped" and outcome.observed_status is JobStatus.RUNNING
    assert status_of(stack, a_ids[0]) is JobStatus.RUNNING


def _dispatcher(stack, claimed, start):
    def run():
        start.wait()
        while True:
            job = stack.queue.claim_next_job()
            if job is None:
                return
            claimed.append(job.job_id)
            stack.queue.mark_completed(job.job_id, {"success": True})

    return run


def test_concurrent_dispatch_never_loses_a_claimed_job_to_cancellation(tmp_path):
    for round_index in range(5):
        stack = make_stack(tmp_path, name=f"race-{round_index}.sqlite3")
        ids = [f"r{i:02d}" for i in range(25)]
        admit(stack, [video_njr(job_id, "race", i, 25) for i, job_id in enumerate(ids)])
        claimed: list[str] = []
        start = threading.Barrier(2)
        worker = threading.Thread(target=_dispatcher(stack, claimed, start))
        worker.start()
        start.wait()
        outcomes = stack.queue.cancel_queued_jobs(ids, reason="race")
        worker.join(10)
        assert not worker.is_alive()
        final = {job_id: status_of(stack, job_id) for job_id in ids}
        cancelled = {o.job_id for o in outcomes if o.outcome == "cancelled"}
        assert not [o for o in outcomes if o.outcome == "error"]
        # A job the dispatcher claimed is COMPLETED, never CANCELLED; every other job is CANCELLED.
        assert not cancelled & set(claimed)
        assert all(final[j] is JobStatus.COMPLETED for j in claimed)
        assert all(final[j] is JobStatus.CANCELLED for j in cancelled)
        assert set(ids) == set(claimed) | cancelled
        assert Counter(final.values()) == Counter(
            {JobStatus.COMPLETED: len(claimed), JobStatus.CANCELLED: len(cancelled)})
        stack.repository.close()


# ------------------------------------------------------------------ idempotence, partial report, refusal (14)


def test_repeating_cancel_remaining_is_harmless_and_reports_zero(stack):
    a_ids, b_ids = _populate(stack)
    first = stack.operations.cancel_remaining(A)
    again = stack.operations.cancel_remaining(A)
    assert len(first.cancelled) == 8 and again.cancelled == () and not again.skipped
    assert "Cancelled 0 queued job(s)" in again.message
    assert {status_of(stack, j) for j in b_ids} == {JobStatus.QUEUED}


def test_confirmed_members_that_left_the_queue_are_reported_as_skipped(stack):
    a_ids, _ = _populate(stack, a=4, b=0, ordinary=0)
    plan = stack.operations.plan_cancel_remaining(A)
    stack.queue.mark_cancelled(a_ids[1], "cancelled elsewhere")  # e.g. a single-job Queue action
    result = stack.operations.cancel_remaining(A, confirmed_job_ids=plan.target_job_ids)
    assert result.cancelled == (a_ids[0], a_ids[2], a_ids[3])
    assert [item.job_id for item in result.skipped] == [a_ids[1]]


def test_a_member_that_returned_to_the_queue_after_confirmation_is_not_cancelled_unconfirmed(stack):
    a_ids, _ = _populate(stack, a=3, b=0, ordinary=0)
    plan = stack.operations.plan_cancel_remaining(A)
    stack.queue.claim_next_job()
    stack.queue.cancel_running_job(return_to_queue=True, assessment=NEVER_INVOKED)  # back to QUEUED after the dialog
    # Confirmation covered only the other two jobs.
    result = stack.operations.cancel_remaining(A, confirmed_job_ids=a_ids[1:])
    assert result.cancelled == tuple(a_ids[1:]) and status_of(stack, a_ids[0]) is JobStatus.QUEUED
    assert plan.target_job_ids == tuple(a_ids)


def test_unknown_and_conflicting_batches_are_refused_before_any_change(stack):
    admit(stack, [video_njr("x0", "conflict", 0, 3), video_njr("x1", "conflict", 0, 3)])
    with pytest.raises(BatchOperationRefused, match="conflicting"):
        stack.operations.cancel_remaining(BatchKey(BatchKind.VIDEO_WORKFLOW, "conflict"))
    with pytest.raises(BatchOperationRefused, match="not found"):
        stack.operations.cancel_remaining(BatchKey(BatchKind.REVIEW, "nope"))
    assert {status_of(stack, "x0"), status_of(stack, "x1")} == {JobStatus.QUEUED}


def test_a_repository_error_is_reported_per_job_and_the_rest_continue(stack, monkeypatch):
    a_ids, _ = _populate(stack, a=3, b=0, ordinary=0)
    real = stack.repository.transition_job

    def flaky(job, status, **kwargs):
        if job.job_id == a_ids[1]:
            raise RuntimeError("disk error")
        return real(job, status, **kwargs)

    monkeypatch.setattr(stack.repository, "transition_job", flaky)
    result = stack.operations.cancel_remaining(A)
    assert result.cancelled == (a_ids[0], a_ids[2])
    assert [item.job_id for item in result.errors] == [a_ids[1]]
    assert "could not be cancelled" in result.message
    assert status_of(stack, a_ids[1]) is JobStatus.QUEUED


# ------------------------------------------------------------------ durability (15)


def test_status_and_queue_order_remain_consistent_after_restart(stack):
    a_ids, b_ids = _populate(stack)
    stack.queue.move_to_front(b_ids[3])
    stack.operations.cancel_remaining(A)
    expected = [j.job_id for j in stack.queue.list_active_jobs_ordered()]
    assert expected[0] == b_ids[3] and not set(expected) & set(a_ids)
    reopened = stack.reopen()
    restored = [j.job_id for j in reopened.queue.list_active_jobs_ordered()]
    assert restored == expected
    assert {status_of(reopened, j) for j in a_ids} == {JobStatus.CANCELLED}
    assert reopened.queue.claim_next_job().job_id == b_ids[3]
    reopened.repository.close()
