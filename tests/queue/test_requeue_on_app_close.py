"""Re-queue on close (owner decision 2026-11-27: "Re-queue on restart").

Real temporary ``JobRepository`` + ``JobQueue`` + ``JobService`` + ``SingleNodeJobRunner`` and real worker threads;
only ``run_callable`` is a synchronized fake. "Close" is what application shutdown does to the queue: the admission
fence, then ``cancel_current()``.
"""

from __future__ import annotations

import sqlite3
import threading
from pathlib import Path

import pytest

from src.controller.job_service import JobService
from src.pipeline.replay_engine import ReplayEngine
from src.queue.job_model import JobStatus, StageCheckpoint
from src.queue.job_queue import JobQueue
from src.queue.job_repository import JobRepository
from src.queue.single_node_runner import SingleNodeJobRunner
from tests.queue.test_shutdown_admission_fence_140 import DEADLINE, Stack, _wait_until

ACTION = "interrupted_by_app_close"


def _close_app(service: JobService) -> None:
    service.begin_shutdown()
    service.cancel_current()


def _run_first(stack: Stack, *, auto_run: bool = True) -> None:
    stack.service.auto_run_enabled = auto_run
    assert stack.service.run_next_now() is True
    assert stack.started["A"].wait(DEADLINE)


def _settle(stack: Stack) -> None:
    assert stack.service.stop(timeout=DEADLINE) is True


def _queued_after_restart(path: Path) -> list[str]:
    repository = JobRepository(path)
    try:
        return [job.job_id for job in JobQueue(repository=repository).list_active_jobs_ordered()]
    finally:
        repository.close()


@pytest.fixture
def stack(tmp_path: Path):
    built = Stack(tmp_path)
    yield built
    built.close()


# --- characterization: unchanged by this package ------------------------------------------------


def test_a_user_cancel_is_still_final(stack: Stack) -> None:
    _run_first(stack, auto_run=False)

    stack.service.cancel_current()
    _wait_until(lambda: stack.runner.is_quiescent())

    assert stack.status("A") is JobStatus.CANCELLED
    assert [job.job_id for job in stack.queue.list_jobs(JobStatus.QUEUED)] == ["B", "C"]


def test_a_user_cancel_followed_by_a_close_stays_cancelled(stack: Stack) -> None:
    stack.ignore_cancel = True  # the backend has not returned yet when the window is closed
    _run_first(stack, auto_run=False)

    stack.service.cancel_current()
    _close_app(stack.service)
    stack.release["A"].set()
    _settle(stack)

    assert stack.status("A") is JobStatus.CANCELLED
    stack.repository.close()
    assert _queued_after_restart(stack.path) == ["B", "C"]


def test_a_process_that_dies_without_closing_is_still_never_replayed(stack: Stack) -> None:
    stack.ignore_cancel = True
    _run_first(stack, auto_run=False)
    snapshot = stack.path.with_name("after-crash.sqlite3")  # what the next start finds on disk
    with sqlite3.connect(stack.path) as source, sqlite3.connect(snapshot) as target:
        source.backup(target)

    assert _queued_after_restart(snapshot) == ["B", "C"]

    repository = JobRepository(snapshot)
    recovered = repository.get_job_model("A")
    repository.close()
    assert recovered.status is JobStatus.FAILED
    assert recovered.execution_metadata.last_control_action == "restart_interrupted_action_required"


# --- the new behaviour ---------------------------------------------------------------------------


def test_closing_puts_the_running_job_back_at_the_front_of_the_queue(stack: Stack) -> None:
    _run_first(stack)

    _close_app(stack.service)
    _settle(stack)

    job = stack.repository.get_job_model("A")
    assert job.status is JobStatus.QUEUED
    assert job.execution_metadata.last_control_action == ACTION
    assert job.execution_metadata.return_to_queue_count == 1
    assert job.started_at is None and job.completed_at is None
    assert job.result is None and job.error_message is None
    assert stack.calls == ["A"]
    assert stack.repository.count() == 3, "re-queueing must not add a job"
    stack.repository.close()
    assert _queued_after_restart(stack.path) == ["A", "B", "C"]


def test_the_job_is_already_queued_while_the_backend_has_not_returned(stack: Stack) -> None:
    """A crash, a hung backend or the shutdown watchdog after this point leaves the job runnable."""

    stack.ignore_cancel = True
    _run_first(stack)

    _close_app(stack.service)

    assert stack.status("A") is JobStatus.QUEUED
    assert _queued_after_restart(stack.path) == ["A", "B", "C"]
    stack.release["A"].set()  # the late result is discarded
    _settle(stack)
    assert stack.status("A") is JobStatus.QUEUED
    assert stack.repository.get_job_model("A").result is None


def test_closing_twice_re_queues_once(stack: Stack) -> None:
    _run_first(stack)

    _close_app(stack.service)
    _close_app(stack.service)
    _settle(stack)

    assert stack.repository.get_job_model("A").execution_metadata.return_to_queue_count == 1
    assert [job.job_id for job in stack.queue.list_active_jobs_ordered()] == ["A", "B", "C"]


def test_the_interrupted_job_leads_a_queue_the_operator_had_reordered(stack: Stack) -> None:
    _run_first(stack)
    assert (
        stack.queue.move_to_front("C") is True
    )  # renumbers the queued rows around the running one

    _close_app(stack.service)
    _settle(stack)

    assert [job.job_id for job in stack.queue.list_active_jobs_ordered()] == ["A", "C", "B"]
    stack.repository.close()
    assert _queued_after_restart(stack.path) == ["A", "C", "B"]


def test_finished_stage_checkpoints_are_dropped_so_the_job_runs_whole_again(stack: Stack) -> None:
    _run_first(stack)
    live = stack.queue.get_job("A")
    live.execution_metadata.stage_checkpoints = [
        StageCheckpoint(stage_name="txt2img", output_paths=["x.png"])
    ]
    stack.queue.persist_runtime_state(live)

    _close_app(stack.service)
    _settle(stack)

    assert stack.repository.get_job_model("A").execution_metadata.stage_checkpoints == []


def test_a_job_claimed_but_not_started_at_close_is_re_queued_and_never_runs(stack: Stack) -> None:
    at_notify, proceed = threading.Event(), threading.Event()
    real_notify = stack.runner._notify  # noqa: SLF001

    def pinned(job, status):
        if status is JobStatus.RUNNING:
            at_notify.set()
            assert proceed.wait(DEADLINE)
        return real_notify(job, status)

    stack.runner._notify = pinned  # type: ignore[method-assign]  # noqa: SLF001
    stack.service.auto_run_enabled = True
    assert stack.service.run_next_now() is True
    assert at_notify.wait(DEADLINE)

    stack.service.begin_shutdown()  # no cancel_current: the worker alone must settle it
    proceed.set()
    _wait_until(lambda: stack.runner.is_quiescent())

    assert stack.calls == []
    assert stack.status("A") is JobStatus.QUEUED
    assert stack.repository.get_job_model("A").execution_metadata.last_control_action == ACTION


def test_the_next_start_runs_the_interrupted_job_first(stack: Stack) -> None:
    _run_first(stack)
    _close_app(stack.service)
    _settle(stack)
    stack.repository.close()

    repository = JobRepository(stack.path)
    queue = JobQueue(repository=repository)
    ran: list[str] = []
    runner = SingleNodeJobRunner(
        queue,
        lambda job: ran.append(job.job_id) or {"success": True, "variants": []},
        poll_interval=0.005,
    )
    service = JobService(queue, runner=runner, require_normalized_records=True)
    try:
        service.set_auto_run_enabled(True, start_if_ready=True)
        _wait_until(lambda: repository.get_job_model("C").status is JobStatus.COMPLETED)
        assert ran == ["A", "B", "C"]
        finished = repository.get_job_model("A")
        assert finished.status is JobStatus.COMPLETED
        assert (
            finished.execution_metadata.last_control_action == ACTION
        )  # the interruption stays on record
    finally:
        runner.stop()
        service.stop()
        repository.close()


def test_a_stage_that_returns_after_the_close_leaves_no_checkpoint(stack: Stack) -> None:
    _run_first(stack)
    live = stack.queue.get_job("A")
    late: list = []

    class LateRunner:
        def run_njr(self, record, cancel_token=None, run_plan=None, checkpoint_callback=None):
            late.append(checkpoint_callback)

    ReplayEngine(LateRunner()).replay_njr(live._normalized_record, job=live)  # noqa: SLF001
    _close_app(stack.service)
    _settle(stack)

    late[0]("txt2img", ["late.png"])

    assert stack.repository.get_job_model("A").execution_metadata.stage_checkpoints == []
