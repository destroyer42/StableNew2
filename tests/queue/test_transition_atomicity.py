"""PR-RUNTIME-QUEUE-TRANSITION-ATOMICITY: queue/repository transitions commit atomically and project coherently.

The SQLite row is the lifecycle authority; the live job and the runnable heap are projections of it. Each test here
forces one interleaving with events (see ``tests/helpers/queue_choreography.py``; no sleeps) and then asserts that the
row, the live job and the heap still describe the same job. Every test records, in its docstring, how it failed
against the code at ``15690eab`` (the base of this work) before the fix.
"""

from __future__ import annotations

import copy
import threading
from pathlib import Path
from types import SimpleNamespace

import pytest

from src.controller.job_execution_controller import JobExecutionController
from src.queue.dispatch_evidence import NEVER_INVOKED
from src.queue.job_model import Job, JobStatus, RetryAttempt, StageCheckpoint
from src.queue.job_queue import JobQueue
from src.queue.job_repository import JobRepository
from tests.helpers.njr_factory import make_queue_job
from tests.helpers.queue_choreography import (
    PATIENCE,
    Gate,
    GatedRepository,
    ObservableLock,
    Worker,
    assert_three_way_agreement,
    once,
)

JOB = "job-1"


@pytest.fixture
def stack(tmp_path: Path):
    repository = GatedRepository(tmp_path / "jobs.sqlite3")
    queue = JobQueue(repository=repository)
    lock = ObservableLock()
    queue._lock = lock  # noqa: SLF001 - lets a test see when a racing call is parked behind a transition
    yield SimpleNamespace(repository=repository, queue=queue, lock=lock)
    repository.close()


def _claimed(stack, job_id: str = JOB) -> Job:
    stack.queue.submit(make_queue_job(job_id))
    job = stack.queue.claim_next_job()
    assert job is not None and job.job_id == job_id
    return job


def _return(queue: JobQueue, path: str) -> Job | None:
    """A return backed by positive evidence, so these tests exercise only the commit/projection mechanics."""

    if path == "operator":
        return queue.cancel_running_job(return_to_queue=True, assessment=NEVER_INVOKED)
    return queue.return_undispatched_to_queue(JOB, reason="test", assessment=NEVER_INVOKED)


# --- the repository never edits the job it is given ----------------------------------------------------------------


def test_transition_job_does_not_mutate_the_job_it_is_given():
    """Pre-fix: ``progress`` was zeroed and ``eta_seconds`` cleared on the caller's object (0.0, None)."""

    repository = JobRepository(":memory:")
    job = make_queue_job(JOB)
    repository.record_job_submission(job)
    repository.transition_job(job, JobStatus.RUNNING)
    job.progress, job.eta_seconds = 0.7, 12.0

    persisted = repository.transition_job(job, JobStatus.COMPLETED, result={"ok": True})

    assert (job.progress, job.eta_seconds) == (0.7, 12.0)
    assert (persisted.progress, persisted.eta_seconds) == (
        0.0,
        None,
    )  # the durable terminal row is reset
    repository.close()


def test_a_failed_transaction_leaves_the_candidate_unchanged():
    """Pre-fix: the progress reset happened before the write that then failed (candidate left at 0.0 / None)."""

    repository = JobRepository(":memory:")
    job = make_queue_job(JOB)
    repository.record_job_submission(job)
    repository.transition_job(job, JobStatus.RUNNING)
    job.progress, job.eta_seconds = 0.7, 12.0

    with pytest.raises(TypeError):
        repository.transition_job(job, JobStatus.COMPLETED, result={"not": object()})

    assert (job.progress, job.eta_seconds) == (0.7, 12.0)
    assert repository.get_job_model(JOB).status is JobStatus.RUNNING
    repository.close()


# --- a losing compare-and-transition changes nothing ----------------------------------------------------------------


@pytest.mark.parametrize("path", ["operator", "outage"])
def test_a_losing_return_leaves_the_live_job_untouched(stack, path):
    """Pre-fix: the return edited the live job first, so a lost race left ``result`` wiped and the count raised."""

    live = _claimed(stack)
    live.result, live.error_message, live.progress = {"keep": "me"}, "keep me", 0.4
    before = (
        copy.deepcopy(live.execution_metadata),
        live.result,
        live.error_message,
        live.progress,
        live.status,
    )
    # Durable state moves on behind the queue's back: the compare-and-transition must lose.
    stack.repository.transition_job(copy.copy(live), JobStatus.COMPLETED, result={"done": True})

    assert _return(stack.queue, path) is None

    after = (live.execution_metadata, live.result, live.error_message, live.progress, live.status)
    assert after == before


# --- double return ----------------------------------------------------------------------------------------------


@pytest.mark.parametrize("path", ["operator", "outage"])
def test_a_double_return_counts_once(stack, path):
    """Pre-fix: both callers edited the shared live job, so one return persisted ``return_to_queue_count == 2``."""

    _claimed(stack)
    gate = Gate()
    stack.repository.before_commit = once(
        lambda _job, status: status is JobStatus.QUEUED, lambda *_: gate.pause()
    )
    first = Worker(lambda: _return(stack.queue, path), stack.lock)
    gate.wait_arrived()
    second = Worker(lambda: _return(stack.queue, path), stack.lock)
    second.settled()  # finished (old code) or parked behind the transition in flight (serialized)
    gate.release()
    first.join()
    second.join()

    assert first.error is None and second.error is None
    assert [first.result is not None, second.result is not None].count(True) == 1, (
        "exactly one return takes effect"
    )
    assert stack.repository.get_job_model(JOB).execution_metadata.return_to_queue_count == 1
    assert_three_way_agreement(stack.repository, stack.queue, JOB)


# --- completion / cancel / failure racing a return in flight ----------------------------------------------------------


_RACERS = {
    "cancel": lambda queue: queue.mark_cancelled(JOB, "operator"),
    "publish_completed": lambda queue: queue.publish_result(
        JOB, status=JobStatus.COMPLETED, result={"success": True}, stage_checkpoints=[]
    ),
    "publish_failed": lambda queue: queue.publish_result(
        JOB,
        status=JobStatus.FAILED,
        result={"success": False},
        stage_checkpoints=[],
        error_message="boom",
    ),
}


@pytest.mark.parametrize("racer", sorted(_RACERS))
@pytest.mark.parametrize("path", ["operator", "outage"])
def test_a_return_in_flight_is_not_overtaken(stack, path, racer):
    """Pre-fix: the return held no lock while committing. A cancel then committed over it and the return's stale
    projection resurrected QUEUED on the cancelled job; a publish raised ``JobStatusChanged`` to the runner."""

    _claimed(stack)
    gate = Gate()
    stack.repository.after_commit = once(
        lambda _job, status: status is JobStatus.QUEUED, lambda *_: gate.pause()
    )
    returning = Worker(lambda: _return(stack.queue, path), stack.lock)
    gate.wait_arrived()  # QUEUED is durable; the projection has not run yet
    racing = Worker(lambda: _RACERS[racer](stack.queue), stack.lock)
    racing.settled()
    gate.release()
    returning.join()
    racing.join()

    assert returning.error is None and returning.result is not None
    assert racing.error is None, racing.error
    expected = JobStatus.CANCELLED if racer == "cancel" else JobStatus.QUEUED
    assert stack.repository.get_job_model(JOB).status is expected
    assert_three_way_agreement(stack.repository, stack.queue, JOB)


# --- progress, ETA and execution metadata written by other threads ---------------------------------------------------


def _report_progress(queue: JobQueue, value: float) -> None:
    controller = SimpleNamespace(_queue=queue, _app_state=None)
    JobExecutionController._handle_runtime_status_update(  # noqa: SLF001
        controller, {"job_id": JOB, "progress": value, "eta_seconds": 9.0}
    )


def test_progress_that_loses_the_race_with_a_return_is_not_resurrected(stack):
    """Pre-fix: the late report passed its RUNNING check and wrote 0.6 onto the QUEUED row (live job said 0.0)."""

    _claimed(stack)
    gate = Gate()
    stack.repository.after_commit = once(
        lambda _job, status: status is JobStatus.QUEUED, lambda *_: gate.pause()
    )
    returning = Worker(lambda: _return(stack.queue, "outage"), stack.lock)
    gate.wait_arrived()
    reporting = Worker(lambda: _report_progress(stack.queue, 0.6), stack.lock)
    reporting.settled()
    gate.release()
    returning.join()
    reporting.join()

    assert reporting.error is None
    row = stack.repository.get_job_model(JOB)
    assert (row.status, row.progress, row.eta_seconds) == (JobStatus.QUEUED, 0.0, None)
    assert_three_way_agreement(stack.repository, stack.queue, JOB)


def test_progress_while_running_is_persisted_and_never_regresses(stack):
    """Guard: a valid update is neither lost nor lowered (the high-water mark is kept)."""

    live = _claimed(stack)
    _report_progress(stack.queue, 0.4)
    _report_progress(stack.queue, 0.2)

    assert live.progress == 0.4
    assert stack.repository.get_job_model(JOB).progress == 0.4
    assert_three_way_agreement(stack.repository, stack.queue, JOB)


def _append_pid(job: Job) -> None:
    job.execution_metadata.external_pids.append(4242)


def _append_retry(job: Job) -> None:
    job.execution_metadata.retry_attempts.append(
        RetryAttempt(
            stage="txt2img", attempt_index=1, max_attempts=2, reason="retry", timestamp=1.0
        )
    )


def _replace_checkpoints(job: Job) -> None:
    job.execution_metadata.stage_checkpoints = [
        StageCheckpoint(stage_name="txt2img", completed_at=1.0, output_paths=["out/a.png"])
    ]


_WRITERS = {
    "external_pid": (_append_pid, lambda meta: meta.external_pids == [4242]),
    "retry_attempt": (
        _append_retry,
        lambda meta: [a.reason for a in meta.retry_attempts] == ["retry"],
    ),
    "stage_checkpoint": (
        _replace_checkpoints,
        lambda meta: [c.stage_name for c in meta.stage_checkpoints] == ["txt2img"],
    ),
}


@pytest.mark.parametrize("writer", sorted(_WRITERS))
def test_metadata_written_during_a_transition_survives_the_projection(stack, writer):
    """Pre-fix: the projection replaced the live ``execution_metadata`` wholesale with a snapshot taken before the
    write, so the pid / retry / checkpoint existed in SQLite but was gone from the live job (and the job's external
    process was never cleaned up because cleanup reads the live metadata)."""

    mutate, present = _WRITERS[writer]
    live = _claimed(stack)
    gate = Gate()
    stack.repository.after_commit = once(
        lambda _job, status: status is JobStatus.CANCELLED, lambda *_: gate.pause()
    )
    transitioning = Worker(lambda: stack.queue.mark_cancelled(JOB, "operator"), stack.lock)
    gate.wait_arrived()
    appended = threading.Event()

    def _write() -> None:
        mutate(live)  # in-place on the live job, exactly as the real writers do ...
        appended.set()
        stack.queue.persist_runtime_state(live)  # ... followed by their own persist

    writing = Worker(_write, stack.lock)
    assert appended.wait(PATIENCE)
    writing.settled()
    gate.release()
    transitioning.join()
    writing.join()

    assert writing.error is None
    assert present(live.execution_metadata), "the live job lost a valid update"
    assert present(stack.repository.get_job_model(JOB).execution_metadata), (
        "SQLite lost a valid update"
    )
    assert_three_way_agreement(stack.repository, stack.queue, JOB)


def test_a_progress_write_in_flight_is_not_overtaken_by_a_return(stack):
    """The queue lock (not only the SQL guard) keeps a progress write and a return from interleaving: the write is
    paused after its SQL update and before it assigns the live job; the return must wait for it."""

    live = _claimed(stack)
    gate = Gate()
    stack.repository.after_progress = lambda _job_id, _applied: gate.pause()
    reporting = Worker(lambda: stack.queue.record_progress(JOB, 0.6, 9.0), stack.lock)
    gate.wait_arrived()
    stack.repository.after_progress = None
    returning = Worker(lambda: _return(stack.queue, "outage"), stack.lock)
    returning.settled()  # parked behind the progress write
    gate.release()
    reporting.join()
    returning.join()

    assert reporting.error is None and returning.error is None and returning.result is live
    assert (live.status, live.progress, live.eta_seconds) == (JobStatus.QUEUED, 0.0, None)
    assert_three_way_agreement(stack.repository, stack.queue, JOB)


def test_a_persist_between_commit_and_projection_cannot_write_stale_progress(stack):
    """``persist_runtime_state`` writes the live job's progress. Fired between a terminal commit and its projection it
    would write the old 0.4 onto the cancelled row; under the queue lock it runs after the projection (0.0)."""

    live = _claimed(stack)
    live.progress, live.eta_seconds = 0.4, 7.0
    gate = Gate()
    stack.repository.after_commit = once(
        lambda _job, status: status is JobStatus.CANCELLED, lambda *_: gate.pause()
    )
    cancelling = Worker(lambda: stack.queue.mark_cancelled(JOB, "operator"), stack.lock)
    gate.wait_arrived()
    persisting = Worker(lambda: stack.queue.persist_runtime_state(live), stack.lock)
    persisting.settled()
    gate.release()
    cancelling.join()
    persisting.join()

    assert cancelling.error is None and persisting.error is None
    assert (live.progress, live.eta_seconds) == (0.0, None)
    assert_three_way_agreement(stack.repository, stack.queue, JOB)


def test_published_checkpoints_reach_the_live_job_and_the_row(stack):
    live = _claimed(stack)
    checkpoint = StageCheckpoint(stage_name="txt2img", completed_at=1.0, output_paths=["out/a.png"])

    stack.queue.publish_result(
        JOB, status=JobStatus.COMPLETED, result={"success": True}, stage_checkpoints=[checkpoint]
    )

    assert [c.stage_name for c in live.execution_metadata.stage_checkpoints] == ["txt2img"]
    assert [
        c.stage_name
        for c in stack.repository.get_job_model(JOB).execution_metadata.stage_checkpoints
    ] == ["txt2img"]
    assert_three_way_agreement(stack.repository, stack.queue, JOB)


# --- failures after the commit point -----------------------------------------------------------------------------------


def test_an_exception_after_a_successful_commit_is_reconciled_from_the_row(stack):
    """Pre-fix: the commit succeeded but the caller saw an exception, leaving the live job RUNNING (and in the
    projection) while SQLite said COMPLETED."""

    _claimed(stack)

    def _fail(_job: Job, _status: JobStatus) -> None:
        raise RuntimeError("repository failed after COMMIT")

    stack.repository.after_commit = once(lambda _job, status: status is JobStatus.COMPLETED, _fail)
    stack.queue.mark_completed(
        JOB, {"success": True}
    )  # the row confirms the commit, so the caller is not failed

    assert stack.repository.get_job_model(JOB).status is JobStatus.COMPLETED
    assert_three_way_agreement(stack.repository, stack.queue, JOB)


def test_a_projection_failure_after_commit_is_reconciled_from_the_row(stack, monkeypatch):
    """Pre-fix: the status was copied but the job stayed in the live projection and heap as a COMPLETED job."""

    _claimed(stack)
    calls: list[str] = []
    original = stack.queue._add_finalized_job  # noqa: SLF001

    def _flaky(job_id: str, job: Job) -> None:
        calls.append(job_id)
        if len(calls) == 1:
            raise MemoryError("projection failed after COMMIT")
        original(job_id, job)

    monkeypatch.setattr(stack.queue, "_add_finalized_job", _flaky)
    stack.queue.mark_completed(
        JOB, {"success": True}
    )  # the commit stands; the projection is re-derived from it

    assert stack.repository.get_job_model(JOB).status is JobStatus.COMPLETED
    assert_three_way_agreement(stack.repository, stack.queue, JOB)


# --- observers ---------------------------------------------------------------------------------------------------


@pytest.mark.parametrize("path", ["operator", "outage"])
def test_observers_see_committed_state_only_after_it_is_visible(stack, path):
    """Pre-fix: the return paths announced the transition from inside ``transition_job``, before the projection:
    the history observer was told QUEUED while the queue still held a RUNNING job with no heap entry."""

    _claimed(stack)
    seen: list[tuple[str, str, bool, bool]] = []

    def _observer(entry) -> None:
        live = stack.queue.get_job(entry.job_id)
        in_heap = any(item[2] == entry.job_id for item in stack.queue._queue)  # noqa: SLF001
        seen.append((entry.status.value, live.status.value, in_heap, stack.lock.locked()))

    stack.repository.register_callback(_observer)
    assert _return(stack.queue, path) is not None

    assert seen == [("queued", "queued", True, False)]


def test_an_observer_may_re_enter_the_queue_and_sees_the_returned_job(stack):
    """Pre-fix: an observer that claimed the announced job found it still RUNNING and got nothing."""

    live = _claimed(stack)
    reclaimed: list[Job | None] = []

    def _observer(entry) -> None:
        if entry.status is JobStatus.QUEUED and not reclaimed:
            reclaimed.append(stack.queue.claim_next_job())

    stack.repository.register_callback(_observer)
    assert _return(stack.queue, "outage") is live

    assert reclaimed == [live]
    assert_three_way_agreement(stack.repository, stack.queue, JOB)
    assert stack.repository.get_job_model(JOB).status is JobStatus.RUNNING


# --- other writers of the live projection ---------------------------------------------------------------------------


def test_cancelling_a_queued_job_through_the_execution_controller_is_a_guarded_transition(stack):
    """Pre-fix: ``Job.mark_status`` edited the live job only. SQLite stayed QUEUED, so the cancel was not durable and a
    restart brought the cancelled job back."""

    stack.queue.submit(make_queue_job(JOB))

    JobExecutionController.cancel_job(SimpleNamespace(_queue=stack.queue), JOB)  # noqa: SLF001

    assert stack.repository.get_job_model(JOB).status is JobStatus.CANCELLED
    assert_three_way_agreement(stack.repository, stack.queue, JOB)


def test_the_execution_controller_leaves_a_claimed_job_alone(stack):
    live = _claimed(stack)

    JobExecutionController.cancel_job(SimpleNamespace(_queue=stack.queue), JOB)

    assert live.status is JobStatus.RUNNING
    assert_three_way_agreement(stack.repository, stack.queue, JOB)


# --- restart ----------------------------------------------------------------------------------------------------


def test_a_running_job_is_never_replayed_by_a_restart(tmp_path):
    """Guard: a job RUNNING when the process died is FAILED / action-required and is not runnable again."""

    path = tmp_path / "jobs.sqlite3"
    first = JobRepository(path)
    queue = JobQueue(repository=first)
    queue.submit(make_queue_job(JOB))
    queue.claim_next_job()
    first.close()

    second = JobRepository(path)
    restarted = JobQueue(repository=second)
    try:
        row = second.get_job_model(JOB)
        assert row.status is JobStatus.FAILED
        assert row.error_envelope.error_type == "INTERRUPTED_RESTART_ACTION_REQUIRED"
        assert row.error_envelope.context["automatic_replay"] is False
        assert row.execution_metadata.return_to_queue_count == 0
        assert restarted.claim_next_job() is None and restarted.list_jobs() == []
    finally:
        second.close()


def test_a_committed_return_survives_a_restart_as_a_queued_job(tmp_path):
    """Guard: a return that committed before the process died is QUEUED (not interrupted) after the restart."""

    path = tmp_path / "jobs.sqlite3"
    first = JobRepository(path)
    queue = JobQueue(repository=first)
    queue.submit(make_queue_job(JOB))
    running = queue.claim_next_job()
    running.execution_metadata.return_to_queue_count = 1
    first.transition_job(
        running, JobStatus.QUEUED, expected_status=JobStatus.RUNNING
    )  # committed, never projected
    first.close()

    second = JobRepository(path)
    restarted = JobQueue(repository=second)
    try:
        assert [job.job_id for job in restarted.list_jobs()] == [JOB]
        assert restarted.claim_next_job().job_id == JOB
    finally:
        second.close()
