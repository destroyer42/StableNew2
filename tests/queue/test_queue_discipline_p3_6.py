"""Queue lock, observer and idle-wait discipline (audit B10, P3-6)."""

from __future__ import annotations

import threading
import time
from pathlib import Path

import pytest

from src.pipeline.cli_njr_builder import build_cli_njr
from src.queue.dispatch_evidence import NEVER_INVOKED
from src.queue.job_model import Job, JobStatus
from src.queue.job_queue import JobQueue
from src.queue.job_repository import JobRepository, JobStatusChanged
from src.queue.single_node_runner import SingleNodeJobRunner


def _job(job_id: str) -> Job:
    record = build_cli_njr(
        prompt=f"prompt {job_id}",
        batch_size=1,
        run_name=job_id,
        config={
            "txt2img": {
                "model": "test.safetensors",
                "steps": 4,
                "cfg_scale": 5.0,
                "width": 64,
                "height": 64,
            }
        },
    )
    job = Job(job_id=record.job_id, snapshot={"normalized_job": record.to_dict()})
    job._normalized_record = record  # type: ignore[attr-defined]
    return job


@pytest.fixture
def stack(tmp_path: Path):
    repository = JobRepository(tmp_path / "jobs.sqlite3")
    queue = JobQueue(repository=repository)
    yield repository, queue
    repository.close()


def _within(seconds: float, fn) -> bool:
    """Run ``fn`` on a thread; True if it finished (did not deadlock) within ``seconds``."""

    done = threading.Event()
    errors: list[BaseException] = []

    def _run() -> None:
        try:
            fn()
        except BaseException as exc:  # noqa: BLE001 - surfaced below
            errors.append(exc)
        finally:
            done.set()

    threading.Thread(target=_run, daemon=True).start()
    finished = done.wait(seconds)
    if errors:
        raise errors[0]
    return finished


# --- observers run after the queue lock is released --------------------------------------------------


def test_a_repository_observer_that_reads_the_queue_does_not_deadlock_a_claim(stack) -> None:
    repository, queue = stack
    seen: list[str] = []
    repository.register_callback(
        lambda entry: seen.append(f"{entry.job_id}:{len(queue.list_jobs())}")
    )
    queue.submit(_job("claim-me"))

    def _claim_and_finish() -> None:
        claimed = queue.claim_next_job()
        assert claimed is not None
        queue.mark_completed(claimed.job_id, {"ok": True})

    assert _within(10, _claim_and_finish), "an observer reading the queue deadlocked the queue lock"
    assert any(item.startswith("claim-me:") for item in seen)


def test_observers_are_notified_only_after_the_queue_lock_is_released(stack) -> None:
    repository, queue = stack
    lock_held_during_observer: list[bool] = []

    def _observer(entry) -> None:
        lock_held_during_observer.append(queue._lock.locked())  # noqa: SLF001

    queue.submit(_job("ordering"))
    repository.register_callback(_observer)
    claimed = queue.claim_next_job()
    queue.mark_completed(claimed.job_id, {})
    assert lock_held_during_observer, "the transitions should have been announced"
    assert not any(lock_held_during_observer)


def test_deferred_emissions_flush_in_order_once_and_survive_an_exception(stack) -> None:
    repository, _queue = stack
    announced: list[str] = []
    repository.register_callback(lambda entry: announced.append(entry.job_id))

    class _Entry:
        def __init__(self, job_id: str) -> None:
            self.job_id = job_id

    with pytest.raises(RuntimeError):
        with repository.defer_emissions():
            repository._emit(_Entry("a"))  # noqa: SLF001
            with repository.defer_emissions():  # re-entrant: the inner exit must not flush
                repository._emit(_Entry("b"))  # noqa: SLF001
            assert announced == []
            raise RuntimeError("boom")
    assert announced == [
        "a",
        "b",
    ]  # a transition that committed before the failure is still announced
    repository._emit(_Entry("c"))  # noqa: SLF001
    assert announced == ["a", "b", "c"]  # outside a deferral, emission is immediate again


# --- every state change is a guarded transition -------------------------------------------------------


def test_a_claim_loses_cleanly_to_a_durable_cancel(stack) -> None:
    repository, queue = stack
    job = _job("cancelled-first")
    queue.submit(job)
    repository.transition_job(
        job, JobStatus.CANCELLED
    )  # durable state moved on behind the queue's back
    with pytest.raises(JobStatusChanged):
        queue.claim_next_job()
    assert queue.get_job("cancelled-first").status is not JobStatus.RUNNING


def test_returning_a_job_that_already_finished_is_a_noop_not_an_overwrite(stack) -> None:
    repository, queue = stack
    queue.submit(_job("finished-first"))
    running = queue.claim_next_job()
    assert running is not None
    repository.transition_job(
        running, JobStatus.COMPLETED
    )  # it finished before the return was applied
    assert queue.cancel_running_job(return_to_queue=True, assessment=NEVER_INVOKED) is None
    assert repository.get_job("finished-first").status is JobStatus.COMPLETED


def test_an_undispatched_return_of_a_job_that_moved_on_is_skipped(stack) -> None:
    repository, queue = stack
    queue.submit(_job("moved-on"))
    running = queue.claim_next_job()
    assert running is not None
    repository.transition_job(running, JobStatus.FAILED)
    assert (
        queue.return_undispatched_to_queue("moved-on", reason="test", assessment=NEVER_INVOKED)
        is None
    )
    assert repository.get_job("moved-on").status is JobStatus.FAILED


def test_the_ordinary_return_to_queue_still_works(stack) -> None:
    repository, queue = stack
    queue.submit(_job("back-to-queue"))
    queue.claim_next_job()
    assert queue.cancel_running_job(return_to_queue=True, assessment=NEVER_INVOKED) is not None
    assert repository.get_job("back-to-queue").status is JobStatus.QUEUED
    assert queue.claim_next_job().job_id == "back-to-queue"


# --- the runner idles on an event, not a 20 Hz poll ----------------------------------------------------


class _CountingQueue:
    """Delegates to the real queue and counts how often the idle worker asked for work."""

    def __init__(self, queue: JobQueue) -> None:
        self._queue = queue
        self.claims = 0

    def __getattr__(self, name: str):
        return getattr(self._queue, name)

    def claim_next_job(self):
        self.claims += 1
        return self._queue.claim_next_job()


def test_an_idle_runner_does_not_poll(stack) -> None:
    _repository, queue = stack
    counting = _CountingQueue(queue)
    runner = SingleNodeJobRunner(counting, run_callable=lambda job: {}, poll_interval=0.01)
    runner.start()
    try:
        time.sleep(0.6)
        # Polling at poll_interval would be ~60 claims; one initial claim plus at most a heartbeat is event-driven.
        assert counting.claims <= 3
    finally:
        runner.stop()


def test_an_idle_runner_picks_up_a_new_job_immediately(stack) -> None:
    _repository, queue = stack
    ran = threading.Event()

    def _run(job: Job) -> dict:
        ran.set()
        return {}

    runner = SingleNodeJobRunner(queue, run_callable=_run, poll_interval=0.01)
    runner.start()
    try:
        time.sleep(0.2)  # let it go idle
        started = time.monotonic()
        queue.submit(_job("woken"))
        assert ran.wait(3.0)
        assert time.monotonic() - started < 0.5  # far below the 1 s heartbeat: the submit woke it
    finally:
        runner.stop()


def test_stop_wakes_an_idle_runner_without_waiting_out_the_heartbeat(stack) -> None:
    _repository, queue = stack
    runner = SingleNodeJobRunner(queue, run_callable=lambda job: {}, poll_interval=0.01)
    runner.start()
    time.sleep(0.2)
    started = time.monotonic()
    assert runner.stop(timeout=5.0) is True
    assert time.monotonic() - started < 0.5


def test_setting_the_stop_flag_directly_also_wakes_the_idle_wait(stack) -> None:
    _repository, queue = stack
    runner = SingleNodeJobRunner(queue, run_callable=lambda job: {}, poll_interval=0.01)
    runner.start()
    time.sleep(0.2)
    runner._stop_event.set()  # noqa: SLF001
    deadline = time.monotonic() + 0.5
    while runner.is_running() and time.monotonic() < deadline:
        time.sleep(0.01)
    assert runner.is_quiescent()
