"""PR-RUNTIME-SHUTDOWN-140: the shutdown admission fence at the queue/runner/service seam.

Real temporary ``JobRepository`` + ``JobQueue`` + ``JobService`` + ``SingleNodeJobRunner`` and real worker threads;
only ``run_callable`` is a synchronized fake. The race is closed with ``threading.Event``/barriers (no sleeps as
synchronization): each test pins the worker at the exact dangerous instruction, fires the fence, then lets it go.

Contract under test: once ``JobService.begin_shutdown()`` returns, no QUEUED job can newly acquire RUNNING ownership
(``claim_next_job``, the one-shot ``mark_running`` handoff, or any later start), pending jobs stay durably QUEUED,
the user's auto-run preference is untouched, and ``stop()`` reports whether every worker has definitively quiesced.
"""

from __future__ import annotations

import threading
import time
from collections.abc import Callable
from pathlib import Path

import pytest

from src.controller.job_service import JobService
from src.queue.job_model import JobStatus
from src.queue.job_queue import JobQueue
from src.queue.job_repository import JobRepository
from src.queue.single_node_runner import SingleNodeJobRunner
from tests.helpers.njr_factory import make_queue_job

DEADLINE = 10.0


def _wait_until(predicate: Callable[[], bool], *, timeout: float = DEADLINE) -> None:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if predicate():
            return
        time.sleep(0.005)
    assert predicate(), "condition did not settle before the deadline"


def _begin_shutdown(service: JobService) -> None:
    """The shutdown admission fence (absent before PR-RUNTIME-SHUTDOWN-140: then nothing fences anything)."""

    fence = getattr(service, "begin_shutdown", None)
    if callable(fence):
        fence()


def _stop(service: JobService, timeout: float) -> bool | None:
    try:
        return service.stop(timeout=timeout)
    except TypeError:  # pre-fix signature: a fixed 10 s join and no result
        return service.stop()


class Stack:
    """A real service stack whose jobs block on per-job events and observe cancellation cooperatively."""

    def __init__(self, tmp_path: Path, *, job_ids: tuple[str, ...] = ("A", "B", "C"), ignore_cancel: bool = False):
        self.path = tmp_path / "jobs.sqlite3"
        self.repository = JobRepository(self.path)
        self.queue = JobQueue(repository=self.repository)
        self.started = {job_id: threading.Event() for job_id in job_ids}
        self.release = {job_id: threading.Event() for job_id in job_ids}
        self.calls: list[str] = []
        self.ignore_cancel = ignore_cancel
        self.runner = SingleNodeJobRunner(self.queue, self._execute, poll_interval=0.005)
        self.service = JobService(self.queue, runner=self.runner, require_normalized_records=True)
        for job_id in job_ids:
            self.service.submit_queued(make_queue_job(job_id), emit_queue_updated=False)

    def _execute(self, job):
        self.calls.append(job.job_id)
        self.started[job.job_id].set()
        token = getattr(job, "_cancel_token", None)
        deadline = time.monotonic() + DEADLINE
        while time.monotonic() < deadline and not self.release[job.job_id].is_set():
            if not self.ignore_cancel and token is not None and token.is_cancelled():
                break
            time.sleep(0.002)
        return {"success": True, "variants": []}

    def status(self, job_id: str) -> JobStatus:
        return self.repository.get_job_model(job_id).status

    def close(self) -> None:
        for event in self.release.values():
            event.set()
        try:
            self.runner.stop()
            self.service.stop()
        finally:
            try:
                self.repository.close()
            except Exception:
                pass


@pytest.fixture
def stack(tmp_path: Path):
    built = Stack(tmp_path)
    yield built
    built.close()


# --- Reproduction 1: the post-shutdown claim -----------------------------------------------------


def test_a_claim_that_already_passed_the_dispatch_policy_cannot_start_a_job_after_the_fence(stack: Stack) -> None:
    """The worker is pinned between the dispatch-permission check and ``claim_next_job`` while shutdown fences."""

    service, runner = stack.service, stack.runner
    service.auto_run_enabled = True
    at_check, proceed = threading.Event(), threading.Event()
    armed = threading.Event()

    def pinned_policy() -> bool:
        if armed.is_set():  # only the check that follows A's completion is pinned
            at_check.set()
            assert proceed.wait(DEADLINE)
        return service.auto_run_enabled

    runner.set_continuous_dispatch_allowed(pinned_policy)
    assert service.run_next_now() is True
    assert stack.started["A"].wait(DEADLINE)
    armed.set()
    stack.release["A"].set()
    assert at_check.wait(DEADLINE), "A finished; the worker is at the permission check with B still QUEUED"

    _begin_shutdown(service)  # shutdown becomes authoritative exactly at the A -> B boundary
    proceed.set()
    _wait_until(lambda: stack.started["B"].is_set() or not runner.is_running())

    assert stack.started["B"].is_set() is False, "B acquired RUNNING after shutdown had begun"
    assert stack.status("B") is JobStatus.QUEUED
    assert stack.status("C") is JobStatus.QUEUED
    assert stack.status("A") is JobStatus.COMPLETED
    assert stack.calls == ["A"]


def test_the_active_job_is_cancelled_with_existing_semantics_and_the_next_job_never_starts(stack: Stack) -> None:
    """Shutdown cancels the RUNNING job (existing path); the cancellation unwind must not hand off to B."""

    service, runner = stack.service, stack.runner
    service.auto_run_enabled = True
    assert service.run_next_now() is True
    assert stack.started["A"].wait(DEADLINE)

    _begin_shutdown(service)
    service.cancel_current()  # what application shutdown does to the active job (unchanged behavior)
    _wait_until(lambda: stack.status("A") is JobStatus.CANCELLED)
    _wait_until(lambda: stack.started["B"].is_set() or not runner.is_running())

    assert stack.started["B"].is_set() is False, "the cancellation unwind claimed the next job"
    assert [stack.status(j) for j in ("B", "C")] == [JobStatus.QUEUED, JobStatus.QUEUED]


def test_without_the_fence_a_normal_cancel_still_lets_the_next_job_run(stack: Stack) -> None:
    """Characterization (unchanged): cancelling the active job in normal operation hands off to the next job."""

    service = stack.service
    service.auto_run_enabled = True
    assert service.run_next_now() is True
    assert stack.started["A"].wait(DEADLINE)

    service.cancel_current()

    assert stack.started["B"].wait(DEADLINE)
    stack.release["B"].set()
    stack.release["C"].set()
    _wait_until(lambda: stack.status("C") is JobStatus.COMPLETED)


def test_the_one_shot_handoff_cannot_mark_a_job_running_after_the_fence(stack: Stack) -> None:
    """Run Now: the worker is pinned just before ``mark_running``; the fence must win and the job stays QUEUED."""

    service = stack.service
    service.auto_run_enabled = False
    at_mark, proceed = threading.Event(), threading.Event()
    real_mark_running = stack.queue.mark_running

    def pinned_mark_running(job_id: str):
        at_mark.set()
        assert proceed.wait(DEADLINE)
        return real_mark_running(job_id)

    stack.queue.mark_running = pinned_mark_running  # type: ignore[method-assign]
    assert service.run_next_now() is True
    assert at_mark.wait(DEADLINE)

    _begin_shutdown(service)
    proceed.set()
    _wait_until(lambda: not stack.runner.is_running() and stack.runner.is_quiescent())

    assert stack.started["A"].is_set() is False
    assert stack.status("A") is JobStatus.QUEUED
    assert stack.calls == []


# --- the fence is race-safe, not a flag ---------------------------------------------------------


def test_jobs_submitted_after_the_fence_are_durable_but_never_started(stack: Stack, tmp_path: Path) -> None:
    service = stack.service
    service.auto_run_enabled = True
    _begin_shutdown(service)

    service.submit_queued(make_queue_job("LATE"), emit_queue_updated=False)

    assert stack.status("LATE") is JobStatus.QUEUED
    assert stack.runner.is_running() is False
    assert service.run_next_now() is False
    assert stack.calls == []
    assert [stack.status(j) for j in ("A", "B", "C")] == [JobStatus.QUEUED] * 3


def test_resume_after_the_fence_does_not_restart_dispatch(stack: Stack) -> None:
    service = stack.service
    service.auto_run_enabled = True
    service.pause()
    _begin_shutdown(service)

    service.resume()

    assert stack.runner.is_running() is False
    assert stack.calls == []


def test_begin_shutdown_does_not_change_the_users_auto_run_preference(stack: Stack) -> None:
    stack.service.auto_run_enabled = True

    _begin_shutdown(stack.service)

    assert stack.service.auto_run_enabled is True
    assert stack.queue.is_paused() is False  # the persisted pause setting is not used as the fence
    assert stack.repository.get_setting("queue_paused", False) is False


def test_fencing_twice_and_stopping_an_idle_service_is_safe(tmp_path: Path) -> None:
    built = Stack(tmp_path, job_ids=())
    try:
        _begin_shutdown(built.service)
        _begin_shutdown(built.service)

        assert _stop(built.service, 1.0) in (True, None)
        assert _stop(built.service, 1.0) in (True, None)
    finally:
        built.close()


# --- Reproduction 3: pending jobs survive the restart ---------------------------------------------


def test_fenced_pending_jobs_stay_queued_and_resume_under_the_existing_startup_policy(tmp_path: Path) -> None:
    built = Stack(tmp_path)
    service = built.service
    service.auto_run_enabled = True
    assert service.run_next_now() is True
    assert built.started["A"].wait(DEADLINE)

    _begin_shutdown(service)
    service.cancel_current()
    _wait_until(lambda: built.status("A") is JobStatus.CANCELLED)
    # Application shutdown spends real time between cancelling the active job and stopping the queue (runtime
    # teardown); model that window deterministically: the cancelled worker has fully unwound before stop().
    _wait_until(lambda: built.started["B"].is_set() or not built.runner.is_running())
    built.release["B"].set()
    assert _stop(service, DEADLINE) in (True, None)
    assert [built.status(j) for j in ("B", "C")] == [JobStatus.QUEUED, JobStatus.QUEUED]
    built.repository.close()

    # next application start: the existing recovery + startup auto-run policy, nothing new
    repository = JobRepository(built.path)
    queue = JobQueue(repository=repository)
    ran: list[str] = []
    runner = SingleNodeJobRunner(queue, lambda job: ran.append(job.job_id) or {"success": True, "variants": []}, poll_interval=0.005)
    restarted = JobService(queue, runner=runner, require_normalized_records=True)
    try:
        assert [job.job_id for job in queue.list_jobs(JobStatus.QUEUED)] == ["B", "C"]
        restarted.set_auto_run_enabled(True, start_if_ready=True)
        _wait_until(lambda: ran == ["B", "C"])
        _wait_until(lambda: repository.get_job_model("C").status is JobStatus.COMPLETED)
    finally:
        runner.stop()
        restarted.stop()
        repository.close()


# --- Reproduction 2 (service seam): quiescence is a result, not a join that happened to return ----


def test_stop_reports_that_a_wedged_worker_has_not_quiesced_and_later_that_it_has(tmp_path: Path) -> None:
    built = Stack(tmp_path, ignore_cancel=True)
    try:
        built.service.auto_run_enabled = True
        assert built.service.run_next_now() is True
        assert built.started["A"].wait(DEADLINE)
        _begin_shutdown(built.service)
        built.service.cancel_current()  # the backend never honors it: the worker stays inside run_callable

        first = _stop(built.service, 0.3)

        assert first is False, "stop() must not claim quiescence while the worker is still inside a job"
        assert built.runner.is_running() or built.runner.is_quiescent() is False
        built.release["A"].set()
        _wait_until(lambda: built.runner.is_quiescent())
        assert _stop(built.service, DEADLINE) is True
        assert built.status("B") is JobStatus.QUEUED  # never claimed while the worker unwound
    finally:
        built.close()
