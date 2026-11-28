"""QUEUE-MULTI: batched removal on the queue authority (one transaction, one notification)."""

from __future__ import annotations

import time

import pytest

from src.controller.job_service_queue_batch import remove_queued_jobs
from src.queue.job_model import JobStatus
from src.queue.job_repository import JobRepository
from tests.helpers.batch_ops_201 import admit, make_stack, plain_njr


@pytest.fixture
def stack(tmp_path):
    built = make_stack(tmp_path)
    yield built
    built.repository.close()


def _ids(n: int) -> list[str]:
    return [f"j{i:04d}" for i in range(n)]


def _status(stack, job_id: str) -> JobStatus:
    return stack.repository.get_job_model(job_id).status


def test_remove_many_cancels_only_the_requested_jobs_with_the_single_remove_record(stack):
    ids = _ids(6)
    admit(stack, [plain_njr(i) for i in ids])

    outcome = stack.queue.remove_many(ids[1:4])

    assert outcome.removed == tuple(ids[1:4])
    assert outcome.running == outcome.missing == outcome.errors == ()
    for kept in (ids[0], ids[4], ids[5]):
        assert _status(stack, kept) is JobStatus.QUEUED
    for gone in ids[1:4]:
        row = stack.repository.get_job_model(gone)
        assert row.status is JobStatus.CANCELLED
        assert row.error_message == "removed from queue"  # exactly what single remove records
    assert [job.job_id for job in stack.queue.list_jobs(JobStatus.QUEUED)] == [
        ids[0],
        ids[4],
        ids[5],
    ]
    claimed = [stack.queue.claim_next_job().job_id for _ in range(3)]
    assert claimed == [ids[0], ids[4], ids[5]]  # heap order of the survivors is intact


def test_remove_many_matches_single_remove_row_for_row(tmp_path):
    single, batched = make_stack(tmp_path / "a"), make_stack(tmp_path / "b")
    for stack in (single, batched):
        admit(stack, [plain_njr(i) for i in _ids(3)])
    for job_id in _ids(3):
        single.queue.remove(job_id)
    batched.queue.remove_many(_ids(3))
    for job_id in _ids(3):
        one, many = (
            single.repository.get_job_model(job_id),
            batched.repository.get_job_model(job_id),
        )
        assert (one.status, one.error_message, one.progress, one.eta_seconds, one.result) == (
            many.status,
            many.error_message,
            many.progress,
            many.eta_seconds,
            many.result,
        )
        assert (
            one.execution_metadata.last_control_action
            == many.execution_metadata.last_control_action
        )
    single.repository.close()
    batched.repository.close()


def test_running_jobs_are_skipped_and_reported_unknown_ones_are_missing(stack):
    ids = _ids(4)
    admit(stack, [plain_njr(i) for i in ids])
    running = stack.queue.claim_next_job().job_id

    outcome = stack.queue.remove_many([running, ids[2], "nope", ids[2]])

    assert outcome.removed == (ids[2],)  # a duplicate id counts once
    assert outcome.running == (running,)
    assert outcome.missing == ("nope",)
    assert _status(stack, running) is JobStatus.RUNNING
    assert stack.queue.get_job(running).status is JobStatus.RUNNING


def test_a_job_the_worker_claims_after_the_decision_is_reported_running_not_cancelled(
    stack, monkeypatch
):
    ids = _ids(3)
    admit(stack, [plain_njr(i) for i in ids])
    real = stack.repository.transition_jobs

    def claimed_first(jobs, status, **kwargs):
        # Another connection's worker wins the race for the first job just before the batch commits.
        with stack.repository.transaction() as connection:
            connection.execute("UPDATE jobs SET status = 'running' WHERE job_id = ?", (ids[0],))
        return real(jobs, status, **kwargs)

    monkeypatch.setattr(stack.repository, "transition_jobs", claimed_first)

    outcome = stack.queue.remove_many(ids)

    assert outcome.running == (ids[0],)
    assert outcome.removed == (ids[1], ids[2])
    assert _status(stack, ids[0]) is JobStatus.RUNNING


def test_one_commit_one_state_notification_and_one_history_entry_per_job(stack):
    ids = _ids(40)
    admit(stack, [plain_njr(i) for i in ids])
    state_events: list[int] = []
    stack.queue.register_state_listener(lambda: state_events.append(1))
    history: list[tuple[str, JobStatus]] = []
    stack.repository.register_callback(lambda entry: history.append((entry.job_id, entry.status)))
    status_callbacks: list[str] = []
    stack.queue.register_status_callback(lambda job, status: status_callbacks.append(job.job_id))
    commits = []
    real = stack.repository.transaction

    def counted():
        commits.append(1)
        return real()

    stack.repository.transaction = counted  # type: ignore[method-assign]

    stack.queue.remove_many(ids)

    assert len(commits) == 1
    assert len(state_events) == 1
    assert sorted(job_id for job_id, _ in history) == ids
    assert all(status is JobStatus.CANCELLED for _, status in history)
    assert status_callbacks == ids  # per-job callbacks (events, completion handlers) are kept


def test_a_repository_failure_rolls_the_whole_batch_back(stack, monkeypatch):
    ids = _ids(4)
    admit(stack, [plain_njr(i) for i in ids])
    real = JobRepository._apply_transition
    calls = []

    def fail_third(self, connection, job, status, **kwargs):
        calls.append(job.job_id)
        if len(calls) == 3:
            raise RuntimeError("disk full")
        return real(self, connection, job, status, **kwargs)

    monkeypatch.setattr(JobRepository, "_apply_transition", fail_third)

    with pytest.raises(RuntimeError):
        stack.queue.remove_many(ids)

    monkeypatch.undo()
    assert all(_status(stack, i) is JobStatus.QUEUED for i in ids)
    assert len(stack.queue.list_jobs(JobStatus.QUEUED)) == 4


def test_removed_jobs_stay_removed_after_restart(stack):
    ids = _ids(5)
    admit(stack, [plain_njr(i) for i in ids])
    stack.queue.remove_many(ids[:3])
    again = stack.reopen()
    try:
        assert [job.job_id for job in again.queue.list_jobs(JobStatus.QUEUED)] == ids[3:]
    finally:
        again.repository.close()


def test_job_service_removes_none_means_every_queued_job_and_running_survives(stack):
    ids = _ids(5)
    admit(stack, [plain_njr(i) for i in ids])
    running = stack.queue.claim_next_job().job_id

    outcome = remove_queued_jobs(stack.service, None, "queue cleared")

    assert set(outcome.removed) == set(ids) - {running}
    assert _status(stack, running) is JobStatus.RUNNING
    assert stack.repository.get_job_model(outcome.removed[0]).error_message == "queue cleared"


def test_queue_updated_and_empty_events_fire_once_for_a_batch(stack):
    admit(stack, [plain_njr(i) for i in _ids(30)])
    updates, empties = [], []
    stack.service.register_callback(
        stack.service.EVENT_QUEUE_UPDATED, lambda summaries: updates.append(len(summaries))
    )
    stack.service.register_callback(stack.service.EVENT_QUEUE_EMPTY, lambda: empties.append(1))

    assert stack.queue.clear() == 30

    assert len(updates) == 1 and len(empties) == 1


def test_clear_of_2000_queued_jobs_finishes_in_two_seconds_with_the_service_attached(stack):
    # Before QUEUE-MULTI this took ~8 s here: one COMMIT, one queue-wide summary and one heap rebuild per job.
    ids = _ids(2000)
    admit(stack, [plain_njr(i) for i in ids])
    stack.queue.claim_next_job()  # one running job must survive the clear
    running = stack.queue.list_jobs(JobStatus.RUNNING)[0].job_id

    started = time.perf_counter()
    cleared = stack.queue.clear()
    elapsed = time.perf_counter() - started

    assert cleared == 1999
    assert elapsed < 2.0, f"clear() of 2,000 jobs took {elapsed:.2f}s"
    assert _status(stack, running) is JobStatus.RUNNING
    assert stack.repository.count([JobStatus.QUEUED]) == 0
