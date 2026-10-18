"""Deterministic interleavings for queue/repository transition tests (PR-RUNTIME-QUEUE-TRANSITION-ATOMICITY).

Nothing here sleeps or polls on elapsed time. A second thread is steered with events and a condition variable that the
queue lock itself signals, so every test observes the same interleaving on every run:

* ``GatedRepository`` is the real SQLite repository with a seam immediately before and immediately after the durable
  commit of ``transition_job`` (the linearization point).
* ``ObservableLock`` replaces ``JobQueue._lock`` and reports when another thread is parked on it, so a test can wait
  for "the racing call has either finished or is blocked behind the transition in flight" without guessing.
* ``assert_three_way_agreement`` is the contract: SQLite row, live job and runnable heap describe the same job.
"""

from __future__ import annotations

import threading
from collections.abc import Callable
from typing import Any

from src.queue.job_model import Job, JobStatus
from src.queue.job_queue import JobQueue
from src.queue.job_repository import JobRepository

#: Only ever a hang guard: every wait in this module is released by an event, never by elapsed time.
PATIENCE = 20.0


class ObservableLock:
    """A non-reentrant lock that tells waiters apart from holders (drop-in for ``JobQueue._lock``)."""

    def __init__(self) -> None:
        self._inner = threading.Lock()
        self._changed = threading.Condition()
        self.waiting = 0

    def acquire(self, blocking: bool = True, timeout: float = -1) -> bool:
        if self._inner.acquire(False):
            return True
        if not blocking:
            return False
        with self._changed:
            self.waiting += 1
            self._changed.notify_all()
        try:
            return self._inner.acquire(True, timeout)
        finally:
            with self._changed:
                self.waiting -= 1
                self._changed.notify_all()

    def release(self) -> None:
        self._inner.release()

    def locked(self) -> bool:
        return self._inner.locked()

    def __enter__(self) -> ObservableLock:
        self.acquire()
        return self

    def __exit__(self, *_: Any) -> bool:
        self.release()
        return False

    def poke(self) -> None:
        with self._changed:
            self._changed.notify_all()

    def wait_until(self, predicate: Callable[[], bool]) -> bool:
        with self._changed:
            return self._changed.wait_for(predicate, PATIENCE)


class Gate:
    """A one-shot pause point: the paused thread reports that it arrived; the test decides when it continues."""

    def __init__(self) -> None:
        self._arrived = threading.Event()
        self._proceed = threading.Event()

    def pause(self) -> None:
        self._arrived.set()
        assert self._proceed.wait(PATIENCE), "a paused transition was never released"

    def wait_arrived(self) -> None:
        assert self._arrived.wait(PATIENCE), (
            "the transition under test never reached its pause point"
        )

    def release(self) -> None:
        self._proceed.set()


class Worker:
    """Runs ``fn`` on its own thread and keeps its outcome."""

    def __init__(self, fn: Callable[[], Any], lock: ObservableLock | None = None) -> None:
        self.result: Any = None
        self.error: BaseException | None = None
        self.finished = False
        self._lock = lock
        self._thread = threading.Thread(target=self._run, args=(fn,), daemon=True)
        self._thread.start()

    def _run(self, fn: Callable[[], Any]) -> None:
        try:
            self.result = fn()
        except BaseException as exc:  # noqa: BLE001 - surfaced to the test as data
            self.error = exc
        finally:
            self.finished = True
            if self._lock is not None:
                self._lock.poke()

    def settled(self) -> None:
        """Wait until the call finished or is parked behind the queue lock (the transition in flight holds it)."""

        assert self._lock is not None
        assert self._lock.wait_until(lambda: self.finished or self._lock.waiting > 0), (
            "worker never settled"
        )

    def join(self) -> None:
        self._thread.join(PATIENCE)
        assert not self._thread.is_alive(), "worker hung"


class GatedRepository(JobRepository):
    """The real repository with seams around the durable commit of ``transition_job``."""

    def __init__(self, path: Any) -> None:
        super().__init__(path)
        self.before_commit: Callable[[Job, JobStatus], None] | None = None
        self.after_commit: Callable[[Job, JobStatus], None] | None = None
        self.after_progress: Callable[[str, bool], None] | None = None

    def transition_job(self, job: Job, status: JobStatus, **kwargs: Any) -> Job:
        if self.before_commit is not None:
            self.before_commit(job, status)
        persisted = super().transition_job(job, status, **kwargs)
        if self.after_commit is not None:
            self.after_commit(job, status)
        return persisted

    def update_progress(self, job_id: str, progress: float, eta_seconds: float | None) -> bool:
        applied = super().update_progress(job_id, progress, eta_seconds)
        if self.after_progress is not None:
            self.after_progress(job_id, applied)
        return applied


def once(predicate: Callable[[Job, JobStatus], bool], action: Callable[[Job, JobStatus], None]):
    """A repository hook that acts only on the first call ``predicate`` accepts."""

    fired: list[bool] = []

    def hook(job: Job, status: JobStatus) -> None:
        if not fired and predicate(job, status):
            fired.append(True)
            action(job, status)

    return hook


def assert_heap_invariant(queue: JobQueue) -> None:
    heap = queue._queue  # noqa: SLF001
    for index in range(1, len(heap)):
        assert heap[(index - 1) // 2] <= heap[index], "runnable heap invariant broken"


def assert_three_way_agreement(repository: JobRepository, queue: JobQueue, job_id: str) -> None:
    """SQLite row, live job and runnable heap describe the same lifecycle state of ``job_id``."""

    row = repository.get_job_model(job_id)
    live = queue.get_job(job_id)
    assert row is not None and live is not None
    assert live.status is row.status, (
        f"live job is {live.status.value}, durable row is {row.status.value}"
    )
    entries = [item for item in queue._queue if item[2] == job_id]  # noqa: SLF001
    projected = job_id in queue._jobs  # noqa: SLF001
    if row.status is JobStatus.QUEUED:
        assert projected and len(entries) == 1, (
            "a QUEUED job must be projected with exactly one heap entry"
        )
    else:
        assert not entries, f"a {row.status.value} job still has a runnable heap entry"
        assert projected == (row.status is JobStatus.RUNNING), (
            "projection membership disagrees with the row"
        )
    assert_heap_invariant(queue)
    for name in ("progress", "eta_seconds", "error_message", "result"):
        assert getattr(live, name) == getattr(row, name), (
            f"{name}: live {getattr(live, name)!r} != row"
        )
    live_meta, row_meta = live.execution_metadata, row.execution_metadata
    assert live_meta.last_control_action == row_meta.last_control_action
    assert live_meta.return_to_queue_count == row_meta.return_to_queue_count
