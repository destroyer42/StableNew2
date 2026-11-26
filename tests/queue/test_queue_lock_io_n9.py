"""PR-QUEUE-LOCK-IO-N9: queue/History projection work never waits for the disk.

Two defects made one slow read stall the queue worker, the queue projection and any GUI-thread queue read together
(``QUEUE_DISPATCH_SLOW`` claims of 2-63 s with an equal ``Queue projection timing`` on the adjacent log line):

1. the History refresh after every completion (``list_recent_jobs`` for COMPLETED/FAILED) sorted every terminal row of
   the 4.9 GB repository by ``created_at``, reading each row's overflow chain under the shared repository lock
   (1.4 s warm, 19 s cold on the workstation copy);
2. ``JobQueue._lock``, which every projection reader needs, was held across the repository commit, so a claim waiting
   for that read (or for a slow fsync) parked every reader behind it.

Each regression test records how it failed against ``dbdfa2a3`` (the base of this work). The remaining tests pin
behaviour that must not change: the query results, the status-index plan for non-terminal filters, writer
serialization behind a claim in flight (``_lock`` gave that before the split, ``_transition_lock`` gives it now) and
a failed claim leaving nothing to undo.
"""

from __future__ import annotations

import threading
from pathlib import Path
from types import SimpleNamespace

import pytest

from src.queue.job_model import Job, JobStatus
from src.queue.job_queue import JobQueue
from src.queue.job_repository import JobRepository
from tests.helpers.njr_factory import make_queue_job
from tests.helpers.queue_choreography import (
    Gate,
    GatedRepository,
    ObservableLock,
    Worker,
    assert_three_way_agreement,
    once,
)

TERMINAL = {JobStatus.COMPLETED, JobStatus.FAILED}


# --- 1. the History read is index-ordered and bounded ----------------------------------------------------------------


def _captured_selects(repository: JobRepository, call) -> list[str]:
    statements: list[str] = []
    repository._connection.set_trace_callback(statements.append)  # noqa: SLF001 - observe the SQL actually run
    try:
        call()
    finally:
        repository._connection.set_trace_callback(None)  # noqa: SLF001
    return [sql for sql in statements if sql.lstrip().upper().startswith("SELECT")]


def _plan(repository: JobRepository, sql: str) -> str:
    rows = repository._connection.execute("EXPLAIN QUERY PLAN " + sql).fetchall()  # noqa: SLF001
    return " | ".join(str(row["detail"]) for row in rows)


def _seed(repository: JobRepository, terminal: int, queued: int) -> list[str]:
    """``terminal`` finished jobs, then ``queued`` newer QUEUED ones; returns the terminal ids newest first."""

    finished: list[str] = []
    for index in range(terminal):
        job = make_queue_job(f"done-{index:03d}")
        repository.record_job_submission(job)
        repository.transition_job(job, JobStatus.RUNNING)
        status = JobStatus.FAILED if index % 3 == 0 else JobStatus.COMPLETED
        repository.transition_job(
            job, status, error_message="x" if status is JobStatus.FAILED else None
        )
        finished.append(job.job_id)
    for index in range(queued):
        repository.record_job_submission(make_queue_job(f"wait-{index:03d}"))
    return list(reversed(finished))


def test_recent_terminal_history_walks_the_created_at_index(tmp_path: Path):
    """Pre-fix: the inner newest-first query used ``idx_jobs_terminal (status=?)`` plus a temp B-tree sort of every
    terminal row (``SEARCH jobs USING INDEX idx_jobs_terminal``), i.e. O(table) reads per History refresh."""

    repository = JobRepository(tmp_path / "jobs.sqlite3")
    _seed(repository, terminal=6, queued=2)

    selects = _captured_selects(
        repository, lambda: repository.list_recent_jobs(statuses=TERMINAL, limit=3)
    )

    assert len(selects) == 1
    plan = _plan(repository, selects[0])
    assert "idx_jobs_created_at" in plan, plan
    assert "idx_jobs_terminal" not in plan and "idx_jobs_runnable" not in plan, plan
    repository.close()


def test_recent_terminal_history_returns_the_newest_terminal_jobs_only(tmp_path: Path):
    """The plan change keeps the result: newest first, terminal only, newer queued rows skipped, limit honoured."""

    repository = JobRepository(tmp_path / "jobs.sqlite3")
    newest_first = _seed(repository, terminal=7, queued=3)

    entries = repository.list_recent_jobs(statuses=TERMINAL, limit=4)

    assert [entry.job_id for entry in entries] == newest_first[:4]
    assert all(entry.status in TERMINAL for entry in entries)
    assert [entry.job_id for entry in repository.list_jobs(status=JobStatus.FAILED, limit=10)] == [
        job_id for job_id in newest_first if int(job_id.split("-")[1]) % 3 == 0
    ]
    repository.close()


def test_a_non_terminal_filter_keeps_the_status_index(tmp_path: Path):
    """QUEUED/RUNNING match few rows of a large repository, so they keep the status index (no newest-first walk)."""

    repository = JobRepository(tmp_path / "jobs.sqlite3")
    _seed(repository, terminal=4, queued=2)

    selects = _captured_selects(
        repository, lambda: repository.list_jobs(status=JobStatus.QUEUED, limit=5)
    )

    assert len(selects) == 1
    plan = _plan(repository, selects[0])
    assert "idx_jobs_runnable" in plan or "idx_jobs_terminal" in plan, plan
    assert [entry.job_id for entry in repository.list_jobs(status=JobStatus.QUEUED, limit=5)] == [
        "wait-001",
        "wait-000",
    ]
    repository.close()


# --- 2. projection readers are never parked behind repository I/O ---------------------------------------------------


class _ProgressGatedRepository(GatedRepository):
    def __init__(self, path: Path) -> None:
        super().__init__(path)
        self.before_progress = None

    def update_progress(self, job_id: str, progress: float, eta_seconds: float | None) -> bool:
        if self.before_progress is not None:
            self.before_progress()
        return super().update_progress(job_id, progress, eta_seconds)


@pytest.fixture
def stack(tmp_path: Path):
    repository = _ProgressGatedRepository(tmp_path / "jobs.sqlite3")
    queue = JobQueue(repository=repository)
    transition = ObservableLock()
    queue._transition_lock = transition  # noqa: SLF001 - see writers parked behind the commit in flight
    yield SimpleNamespace(repository=repository, queue=queue, transition=transition)
    repository.close()


def _read_projection(queue: JobQueue, job_id: str) -> dict[str, object]:
    """Everything the queue projection, the runner's idle checks and GUI-thread readers take ``_lock`` for."""

    active = queue.list_active_jobs_ordered()
    return {
        "active": [(job.job_id, job.status) for job in active],
        "status": queue.get_job(job_id).status,
        "listed": len(queue.list_jobs()),
        "paused": queue.is_paused(),
        "held": queue.is_webui_held() or queue.is_job_held(job_id),
        "summary": queue.dispatch_summary()["queued"],
        "peek": getattr(queue.peek_next_dispatch_candidate(), "job_id", None),
    }


def _gate_transition(stack, status: JobStatus) -> Gate:
    gate = Gate()
    stack.repository.before_commit = once(
        lambda _job, target: target is status, lambda *_: gate.pause()
    )
    return gate


def test_projection_readers_are_not_parked_behind_a_claim_commit(stack):
    """Pre-fix: the claim held ``_lock`` across ``transition_job``; the reader blocked until the gate opened and the
    worker never finished (``worker hung``)."""

    stack.queue.submit(make_queue_job("job-1"))
    gate = _gate_transition(stack, JobStatus.RUNNING)
    claiming = Worker(stack.queue.claim_next_job)
    gate.wait_arrived()  # the claim is inside its commit (a slow fsync, a long read on the shared connection)

    reader = Worker(lambda: _read_projection(stack.queue, "job-1"))
    reader.join()  # completes while the commit is still in flight

    assert reader.error is None
    assert reader.result == {
        "active": [
            ("job-1", JobStatus.QUEUED)
        ],  # the state before the transition, never a half-applied one
        "status": JobStatus.QUEUED,
        "listed": 1,
        "paused": False,
        "held": False,
        "summary": 1,
        "peek": "job-1",
    }
    gate.release()
    claiming.join()
    assert claiming.error is None and claiming.result.job_id == "job-1"
    assert stack.queue.list_active_jobs_ordered()[0].status is JobStatus.RUNNING
    assert_three_way_agreement(stack.repository, stack.queue, "job-1")


def test_projection_readers_are_not_parked_behind_a_completion_commit(stack):
    """Pre-fix: ``mark_completed`` held ``_lock`` across the commit of the (large) result; readers blocked."""

    stack.queue.submit(make_queue_job("job-1"))
    claimed = stack.queue.claim_next_job()
    gate = _gate_transition(stack, JobStatus.COMPLETED)
    completing = Worker(lambda: stack.queue.mark_completed(claimed.job_id, {"success": True}))
    gate.wait_arrived()

    reader = Worker(
        lambda: [(job.job_id, job.status) for job in stack.queue.list_active_jobs_ordered()]
    )
    reader.join()

    assert reader.result == [("job-1", JobStatus.RUNNING)]
    gate.release()
    completing.join()
    assert completing.error is None
    assert stack.queue.list_active_jobs_ordered() == []
    assert_three_way_agreement(stack.repository, stack.queue, "job-1")


def test_projection_readers_are_not_parked_behind_a_progress_commit(stack):
    """Pre-fix: ``record_progress`` held ``_lock`` across its UPDATE/COMMIT (every 0.5 s while a job runs)."""

    stack.queue.submit(make_queue_job("job-1"))
    stack.queue.claim_next_job()
    gate = Gate()
    stack.repository.before_progress = gate.pause
    reporting = Worker(lambda: stack.queue.record_progress("job-1", 0.5, 3.0))
    gate.wait_arrived()

    reader = Worker(lambda: stack.queue.get_job("job-1").status)
    reader.join()

    assert reader.result is JobStatus.RUNNING
    gate.release()
    reporting.join()
    assert reporting.result is not None and reporting.result.progress == 0.5
    assert stack.repository.get_job_model("job-1").progress == 0.5


def test_projection_readers_are_not_parked_behind_a_reorder_commit(stack, monkeypatch):
    """Pre-fix: a reorder held ``_lock`` across ``update_queue_order``."""

    for job_id in ("job-1", "job-2"):
        stack.queue.submit(make_queue_job(job_id))
    gate = Gate()
    original = stack.repository.update_queue_order

    def gated(order):
        gate.pause()
        return original(order)

    monkeypatch.setattr(stack.repository, "update_queue_order", gated)
    moving = Worker(lambda: stack.queue.move_to_front("job-2"))
    gate.wait_arrived()

    reader = Worker(lambda: [job.job_id for job in stack.queue.list_active_jobs_ordered()])
    reader.join()

    assert reader.result == ["job-1", "job-2"]  # unchanged until the durable order is written
    gate.release()
    moving.join()
    assert moving.result is True
    assert [job.job_id for job in stack.queue.list_active_jobs_ordered()] == ["job-2", "job-1"]


# --- the writer serialization (the claim lock) is unchanged ----------------------------------------------------------


@pytest.mark.parametrize(
    "racer",
    [
        lambda queue: queue.cancel_if_queued("job-1", "operator"),
        lambda queue: queue.hold_webui_dispatch(reason="outage"),
        lambda queue: queue.quarantine_gpu_dispatch({"incident_id": "gpu-1"}),
        lambda queue: queue.pause(),
        lambda queue: queue.move_to_back("job-1"),
    ],
    ids=["queued-cancel", "webui-hold", "gpu-quarantine", "pause", "reorder"],
)
def test_writers_and_dispatch_holds_still_wait_for_the_claim_in_flight(stack, racer):
    """A writer or hold that races a claim is parked until the claim has committed and projected, so it acts on
    the claimed job, never on a decision the claim already made (the guarantee ``_lock`` gave before the split)."""

    for job_id in ("job-1", "job-0"):
        stack.queue.submit(make_queue_job(job_id))
    gate = _gate_transition(stack, JobStatus.RUNNING)
    claiming = Worker(stack.queue.claim_next_job, stack.transition)
    gate.wait_arrived()

    racing = Worker(lambda: racer(stack.queue), stack.transition)
    racing.settled()
    assert not racing.finished  # parked behind the claim in flight

    gate.release()
    claiming.join()
    racing.join()
    assert claiming.result.job_id == "job-1"
    assert stack.repository.get_job_model("job-1").status is JobStatus.RUNNING
    assert_three_way_agreement(stack.repository, stack.queue, "job-1")


def test_a_failed_claim_commit_leaves_the_job_queued_in_its_place(stack):
    """The claim decides without popping, so a refused or failed commit has nothing to undo."""

    for job_id in ("job-1", "job-2"):
        stack.queue.submit(make_queue_job(job_id))

    def _fail(_job: Job, _status: JobStatus) -> None:
        raise RuntimeError("disk full")

    stack.repository.before_commit = once(lambda _job, status: status is JobStatus.RUNNING, _fail)
    with pytest.raises(RuntimeError, match="disk full"):
        stack.queue.claim_next_job()

    assert [job.job_id for job in stack.queue.list_active_jobs_ordered()] == ["job-1", "job-2"]
    assert_three_way_agreement(stack.repository, stack.queue, "job-1")
    assert stack.queue.claim_next_job().job_id == "job-1"
    assert_three_way_agreement(stack.repository, stack.queue, "job-1")


def test_no_repository_call_is_made_while_the_projection_lock_is_held(stack, monkeypatch):
    """Instrumented end to end: every repository entry point asserts ``_lock`` is free."""

    violations: list[str] = []
    queue_lock = stack.queue._lock  # noqa: SLF001
    owner: list[int | None] = [None]
    original_acquire, original_release = queue_lock.acquire, queue_lock.release

    def acquire(*args, **kwargs):
        acquired = original_acquire(*args, **kwargs)
        if acquired:
            owner[0] = threading.get_ident()
        return acquired

    def release():
        owner[0] = None
        original_release()

    monkeypatch.setattr(queue_lock, "acquire", acquire)
    monkeypatch.setattr(queue_lock, "release", release)
    for name in (
        "transition_job",
        "update_progress",
        "persist_runtime_state",
        "update_queue_order",
        "get_job_model",
        "set_setting",
        "record_job_submissions",
    ):
        original = getattr(stack.repository, name)

        def checked(*args, _original=original, _name=name, **kwargs):
            if owner[0] == threading.get_ident():
                violations.append(_name)
            return _original(*args, **kwargs)

        monkeypatch.setattr(stack.repository, name, checked)

    for job_id in ("job-1", "job-2", "job-3"):
        stack.queue.submit(make_queue_job(job_id))
    stack.queue.move_to_back("job-1")
    stack.queue.move_up("job-3")
    job = stack.queue.claim_next_job()
    stack.queue.record_progress(job.job_id, 0.4, 2.0)
    stack.queue.persist_runtime_state(job)
    stack.queue.mark_completed(job.job_id, {"success": True})
    stack.queue.quarantine_gpu_dispatch({"incident_id": "gpu-1"})
    stack.queue.release_gpu_quarantine("gpu-1")
    stack.queue.pause()
    stack.queue.resume()
    stack.queue.cancel_if_queued("job-1")
    stack.queue.claim_next_job()
    stack.queue.cancel_running_job()

    assert violations == []
