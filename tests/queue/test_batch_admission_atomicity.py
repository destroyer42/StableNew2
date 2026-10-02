"""Canonical NJR batch admission is all-or-none (PR-VID-194T).

Real SQLite repository + JobQueue + JobService; the runner is a spy.  Failures are injected
deterministically at the repository insert seam.  No sleeps, GPU or network.
"""

from __future__ import annotations

import sqlite3
from pathlib import Path
from typing import Any

import pytest

from src.controller.job_service import JobService
from src.controller.submission_policy_v26 import SubmissionPolicy
from src.queue.job_model import JobPriority, JobStatus
from src.queue.job_queue import JobQueue
from src.queue.job_repository import JobConflictError, JobRepository
from tests.helpers.job_helpers import make_test_njr


class _SpyRunner:
    """Records what is durable AND runnable at the moment the runner is asked to start."""

    def __init__(self, queue: JobQueue, db_path: Path) -> None:
        self.queue = queue
        self.db_path = db_path
        self.started = False
        self.start_snapshots: list[dict[str, Any]] = []

    def _snapshot(self) -> dict[str, Any]:
        return {
            "durable": _durable_ids(self.db_path),
            "runnable": [job.job_id for job in self.queue.list_jobs()],
        }

    def start(self) -> None:
        self.start_snapshots.append(self._snapshot())
        self.started = True

    def request_continuous_dispatch(self) -> None:
        self.start_snapshots.append(self._snapshot())

    def stop(self) -> None:
        self.started = False

    def is_running(self) -> bool:
        return self.started

    def run_once(self, job):
        return {"success": True}

    def cancel_current(self, *, return_to_queue: bool = False) -> None:
        return None


def _durable_ids(db_path: Path) -> list[str]:
    connection = sqlite3.connect(db_path)
    try:
        return [
            row[0] for row in connection.execute("SELECT job_id FROM jobs ORDER BY queue_order")
        ]
    finally:
        connection.close()


def _stack(tmp_path: Path, *, auto_run: bool = True):
    db_path = tmp_path / "jobs.sqlite3"
    repository = JobRepository(db_path)
    queue = JobQueue(repository=repository)
    runner = _SpyRunner(queue, db_path)
    service = JobService(queue, runner=runner)
    service.auto_run_enabled = auto_run
    events: list[tuple[str, Any]] = []
    service.register_callback(
        JobService.EVENT_JOB_SUBMITTED, lambda job, *_a: events.append(("submitted", job.job_id))
    )
    service.register_callback(
        JobService.EVENT_QUEUE_UPDATED, lambda *_a: events.append(("queue_updated", None))
    )
    repo_announced: list[str] = []
    repository.register_callback(lambda entry: repo_announced.append(entry.job_id))
    state_views: list[list[str]] = []
    queue.register_state_listener(
        lambda: state_views.append([job.job_id for job in queue.list_jobs()])
    )
    return SimpleStack(
        repository, queue, service, runner, db_path, events, repo_announced, state_views
    )


class SimpleStack:
    def __init__(self, repository, queue, service, runner, db_path, events, announced, views):
        self.repository = repository
        self.queue = queue
        self.service = service
        self.runner = runner
        self.db_path = db_path
        self.events = events
        self.announced = announced
        self.state_views = views


def _records(count: int, prefix: str = "batch") -> list:
    return [
        make_test_njr(job_id=f"{prefix}-{index}", prompt_source="manual", prompt_pack_id="")
        for index in range(count)
    ]


def _fail_on_nth_insert(monkeypatch, repository: JobRepository, nth: int) -> None:
    original = repository._insert_job_submission
    calls = {"n": 0}

    def flaky(connection, prepared, queue_order):
        calls["n"] += 1
        if calls["n"] == nth:
            raise sqlite3.OperationalError("injected write failure")
        return original(connection, prepared, queue_order)

    monkeypatch.setattr(repository, "_insert_job_submission", flaky)


# ------------------------------------------------------------------ pre-mutation rejection


def test_duplicate_identities_in_one_batch_are_rejected_before_any_mutation(tmp_path):
    stack = _stack(tmp_path)
    record = _records(1)[0]
    with pytest.raises(ValueError, match="duplicate"):
        stack.service.submit_njrs([record, record])
    assert _durable_ids(stack.db_path) == [] and stack.queue.list_jobs() == []
    assert stack.events == [] and stack.runner.start_snapshots == []


# ------------------------------------------------------------------ rollback on failure


def test_conflict_on_a_later_job_rolls_back_earlier_new_jobs_and_spares_existing(tmp_path):
    stack = _stack(tmp_path, auto_run=False)
    existing = _records(1, "existing")[0]
    stack.service.submit_njrs([existing])
    stack.events.clear()
    stack.announced.clear()
    stack.state_views.clear()

    new_a, new_b = _records(2, "new")
    with pytest.raises(JobConflictError):
        stack.service.submit_njrs([new_a, new_b, existing])  # existing identity conflicts last

    assert _durable_ids(stack.db_path) == [existing.job_id]  # new rows rolled back
    assert [job.job_id for job in stack.queue.list_jobs()] == [existing.job_id]
    assert stack.queue.get_job(existing.job_id).status is JobStatus.QUEUED  # untouched
    assert stack.events == [] and stack.announced == [] and stack.state_views == []


def test_injected_sqlite_failure_mid_batch_rolls_back_every_new_row(tmp_path, monkeypatch):
    stack = _stack(tmp_path)
    existing = _records(1, "existing")[0]
    stack.service.submit_njrs([existing])
    stack.events.clear()
    stack.announced.clear()
    stack.state_views.clear()
    starts_before = len(stack.runner.start_snapshots)
    _fail_on_nth_insert(monkeypatch, stack.repository, 3)

    with pytest.raises(sqlite3.OperationalError, match="injected"):
        stack.service.submit_njrs(_records(4))

    assert _durable_ids(stack.db_path) == [existing.job_id]
    assert [job.job_id for job in stack.queue.list_jobs()] == [existing.job_id]
    assert stack.queue._queue and len(stack.queue._queue) == 1  # no heap entries for the batch
    # nothing announced for the failed batch: no repository callback, no state change, no
    # submitted/queue-updated event, and the runner was not asked to start because of it
    assert stack.announced == [] and stack.state_views == [] and stack.events == []
    assert len(stack.runner.start_snapshots) == starts_before


def test_failed_batch_leaves_the_repository_usable_for_the_next_submission(tmp_path, monkeypatch):
    stack = _stack(tmp_path, auto_run=False)
    _fail_on_nth_insert(monkeypatch, stack.repository, 2)
    with pytest.raises(sqlite3.OperationalError):
        stack.service.submit_njrs(_records(3, "bad"))
    monkeypatch.undo()
    ids = stack.service.submit_njrs(_records(3, "good"))
    assert _durable_ids(stack.db_path) == ids


# ------------------------------------------------------------------ successful batch


def test_successful_batch_is_durable_projected_ordered_and_announced_once(tmp_path):
    stack = _stack(tmp_path, auto_run=False)
    records = _records(4)

    ids = stack.service.submit_njrs(records)

    assert ids == [record.job_id for record in records]
    assert _durable_ids(stack.db_path) == ids  # one transaction, sequential queue order
    assert [job.job_id for job in stack.queue.list_jobs()] == ids
    assert [stack.queue.get_next_job().job_id for _ in ids] == ids  # FIFO
    assert stack.announced == ids
    # exactly one projection notification, and it already showed the whole batch
    assert stack.state_views == [ids]
    assert [e for e in stack.events if e[0] == "submitted"] == [("submitted", i) for i in ids]
    assert [e for e in stack.events if e[0] == "queue_updated"] == [("queue_updated", None)]
    # lifecycle events come after the batch is complete, queue-updated last
    assert stack.events[-1] == ("queue_updated", None)


def test_priority_and_fifo_semantics_are_preserved_across_batches(tmp_path):
    stack = _stack(tmp_path, auto_run=False)
    first = stack.service.submit_njrs(_records(2, "normal"))
    high = stack.service.submit_njrs(
        _records(2, "high"), SubmissionPolicy(priority=JobPriority.HIGH)
    )
    order = [stack.queue.get_next_job().job_id for _ in range(4)]
    assert order == high + first
    assert _durable_ids(stack.db_path) == first + high  # durable order is submission order


# ------------------------------------------------------------------ runner ordering


def test_auto_run_starts_the_runner_once_only_after_the_whole_batch_is_present(tmp_path):
    stack = _stack(tmp_path, auto_run=True)
    ids = stack.service.submit_njrs(_records(3))

    assert len(stack.runner.start_snapshots) == 1  # once for the batch, not once per arm
    snapshot = stack.runner.start_snapshots[0]
    assert snapshot["durable"] == ids and snapshot["runnable"] == ids


def test_running_worker_is_asked_to_dispatch_once_with_everything_already_visible(tmp_path):
    stack = _stack(tmp_path, auto_run=True)
    stack.runner.started = True  # a worker is already running (e.g. a one-shot)
    ids = stack.service.submit_njrs(_records(3))
    assert len(stack.runner.start_snapshots) == 1
    assert stack.runner.start_snapshots[0]["runnable"] == ids


def test_start_when_idle_still_dispatches_after_the_complete_batch(tmp_path):
    stack = _stack(tmp_path, auto_run=False)
    dispatched: list[list[str]] = []
    stack.service.run_next_now = (
        lambda: dispatched.append(  # type: ignore[method-assign]
            [job.job_id for job in stack.queue.list_jobs()]
        )
        or True
    )
    ids = stack.service.submit_njrs(_records(3), SubmissionPolicy(start_when_idle=True))
    assert dispatched == [ids]


def test_failed_batch_never_triggers_start_when_idle(tmp_path, monkeypatch):
    stack = _stack(tmp_path, auto_run=True)
    dispatched: list[bool] = []
    stack.service.run_next_now = lambda: dispatched.append(True) or True  # type: ignore[method-assign]
    _fail_on_nth_insert(monkeypatch, stack.repository, 2)
    with pytest.raises(sqlite3.OperationalError):
        stack.service.submit_njrs(_records(3), SubmissionPolicy(start_when_idle=True))
    assert dispatched == [] and stack.runner.start_snapshots == []


# ------------------------------------------------------------------ single-job paths


def test_single_record_submission_and_queue_submit_still_work(tmp_path):
    stack = _stack(tmp_path, auto_run=False)
    [only] = _records(1, "single")
    assert stack.service.submit_njrs([only]) == [only.job_id]

    job = stack.queue.get_job(only.job_id)
    assert job is not None and job.status is JobStatus.QUEUED
    assert _durable_ids(stack.db_path) == [only.job_id]

    # JobQueue.submit(single) is the same implementation as a one-job batch
    other = stack.service._job_from_njr(_records(1, "direct")[0], policy=SubmissionPolicy())
    stack.queue.submit(other)
    assert _durable_ids(stack.db_path) == [only.job_id, other.job_id]
    assert [stack.queue.get_next_job().job_id for _ in range(2)] == [only.job_id, other.job_id]
    with pytest.raises(JobConflictError):
        stack.queue.submit(other)  # resubmitting an identity is still a conflict


def test_recovery_rebuilds_the_projection_from_the_committed_batch(tmp_path):
    stack = _stack(tmp_path, auto_run=False)
    ids = stack.service.submit_njrs(_records(3))
    stack.repository.close()
    reopened = JobQueue(repository=JobRepository(stack.db_path))
    assert [reopened.get_next_job().job_id for _ in ids] == ids
