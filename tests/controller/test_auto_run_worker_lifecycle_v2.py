from __future__ import annotations

import threading
import time
from collections.abc import Callable
from pathlib import Path

from src.controller.job_service import JobService
from src.queue.job_model import JobStatus
from src.queue.job_queue import JobQueue
from src.queue.job_repository import JobRepository
from src.queue.single_node_runner import SingleNodeJobRunner
from tests.helpers.njr_factory import make_queue_job


def _wait_until(predicate: Callable[[], bool], *, timeout: float = 2.0) -> None:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if predicate():
            return
        time.sleep(0.01)
    assert predicate(), "condition did not settle before timeout"


def _make_service(tmp_path: Path):
    repository = JobRepository(tmp_path / "jobs.sqlite3")
    queue = JobQueue(repository=repository)
    started: dict[str, threading.Event] = {job_id: threading.Event() for job_id in ("A", "B", "C")}
    release_a = threading.Event()
    calls: list[str] = []

    def execute(job):
        calls.append(job.job_id)
        started[job.job_id].set()
        if job.job_id == "A":
            assert release_a.wait(timeout=2.0)
        return {"success": True, "variants": []}

    runner = SingleNodeJobRunner(queue, execute, poll_interval=0.005)
    service = JobService(queue, runner=runner, require_normalized_records=True)
    for job_id in ("A", "B", "C"):
        service.submit_queued(make_queue_job(job_id), emit_queue_updated=False)
    return service, queue, runner, repository, started, release_a, calls


def test_manual_send_runs_one_job_and_reenables_manual_dispatch(tmp_path: Path) -> None:
    service, queue, runner, repository, started, release_a, calls = _make_service(tmp_path)
    service.auto_run_enabled = False
    try:
        assert service.run_next_now() is True
        assert started["A"].wait(timeout=2.0)
        release_a.set()
        _wait_until(lambda: repository.get_job_model("A").status is JobStatus.COMPLETED)
        _wait_until(lambda: not runner.is_running())

        assert calls == ["A"]
        assert [job.job_id for job in queue.list_jobs(JobStatus.QUEUED)] == ["B", "C"]
        assert service.run_next_now() is True
        assert started["B"].wait(timeout=2.0)
        _wait_until(lambda: repository.get_job_model("B").status is JobStatus.COMPLETED)
        assert calls == ["A", "B"]
    finally:
        release_a.set()
        runner.stop()
        service.stop()
        repository.close()


def test_auto_run_drains_continuously(tmp_path: Path) -> None:
    service, _queue, runner, repository, started, release_a, calls = _make_service(tmp_path)
    service.auto_run_enabled = True
    try:
        assert service.run_next_now() is True
        assert started["A"].wait(timeout=2.0)
        release_a.set()
        _wait_until(
            lambda: all(
                repository.get_job_model(job_id).status is JobStatus.COMPLETED
                for job_id in ("A", "B", "C")
            )
        )
        assert calls == ["A", "B", "C"]
    finally:
        release_a.set()
        runner.stop()
        service.stop()
        repository.close()


def test_disabling_auto_run_during_running_job_retires_before_next_claim(tmp_path: Path) -> None:
    service, queue, runner, repository, started, release_a, calls = _make_service(tmp_path)
    service.auto_run_enabled = True
    try:
        assert service.run_next_now() is True
        assert started["A"].wait(timeout=2.0)
        service.auto_run_enabled = False
        assert repository.get_job_model("A").status is JobStatus.RUNNING

        release_a.set()
        _wait_until(lambda: repository.get_job_model("A").status is JobStatus.COMPLETED)
        _wait_until(lambda: not runner.is_running())

        assert calls == ["A"]
        assert [job.job_id for job in queue.list_jobs(JobStatus.QUEUED)] == ["B", "C"]
    finally:
        release_a.set()
        runner.stop()
        service.stop()
        repository.close()


def test_reenabling_auto_run_restarts_retired_worker_and_drains_remaining_jobs(
    tmp_path: Path,
) -> None:
    service, _queue, runner, repository, started, release_a, calls = _make_service(tmp_path)
    service.auto_run_enabled = True
    try:
        assert service.run_next_now() is True
        assert started["A"].wait(timeout=2.0)
        service.auto_run_enabled = False
        release_a.set()
        _wait_until(lambda: repository.get_job_model("A").status is JobStatus.COMPLETED)
        _wait_until(lambda: not runner.is_running())

        service.auto_run_enabled = True
        assert service.run_next_now() is True
        _wait_until(
            lambda: all(
                repository.get_job_model(job_id).status is JobStatus.COMPLETED
                for job_id in ("B", "C")
            )
        )
        assert calls == ["A", "B", "C"]
    finally:
        release_a.set()
        runner.stop()
        service.stop()
        repository.close()


def test_pause_resume_preserves_manual_or_auto_dispatch_policy(tmp_path: Path) -> None:
    service, queue, runner, repository, started, release_a, calls = _make_service(tmp_path)
    service.auto_run_enabled = False
    try:
        service.pause()
        assert service.run_next_now() is False
        assert calls == []
        service.resume()
        assert calls == []
        assert service.run_next_now() is True
        assert started["A"].wait(timeout=2.0)
        release_a.set()
        _wait_until(lambda: repository.get_job_model("A").status is JobStatus.COMPLETED)
        assert calls == ["A"]

        service.auto_run_enabled = True
        service.pause()
        assert [job.job_id for job in queue.list_jobs(JobStatus.QUEUED)] == ["B", "C"]
        service.resume()
        _wait_until(
            lambda: all(
                repository.get_job_model(job_id).status is JobStatus.COMPLETED
                for job_id in ("B", "C")
            )
        )
        assert calls == ["A", "B", "C"]
    finally:
        release_a.set()
        runner.stop()
        service.stop()
        repository.close()


def _make_boundary_service(tmp_path: Path):
    """Service whose one-shot worker blocks *after* job A is durably COMPLETED.

    The ``COMPLETED`` status callback runs on the QueueWorkerOnce thread after the
    result is published, so holding it open reproduces the boundary where the job is
    durably terminal but the one-shot thread has not retired yet.
    """

    repository = JobRepository(tmp_path / "jobs.sqlite3")
    queue = JobQueue(repository=repository)
    at_boundary = threading.Event()
    proceed = threading.Event()
    calls: list[str] = []

    def execute(job):
        calls.append(job.job_id)
        return {"success": True, "variants": []}

    def on_status(job, status):
        if job.job_id == "A" and status is JobStatus.COMPLETED:
            at_boundary.set()
            assert proceed.wait(timeout=5.0), "boundary was never released"

    runner = SingleNodeJobRunner(queue, execute, poll_interval=0.005, on_status_change=on_status)
    service = JobService(queue, runner=runner, require_normalized_records=True)
    service.auto_run_enabled = False
    for job_id in ("A", "B", "C"):
        service.submit_queued(make_queue_job(job_id), emit_queue_updated=False)
    return service, queue, runner, repository, at_boundary, proceed, calls


def test_auto_run_enabled_after_durable_completion_before_one_shot_retires_drains_queue(
    tmp_path: Path,
) -> None:
    service, queue, runner, repository, at_boundary, proceed, calls = _make_boundary_service(
        tmp_path
    )
    try:
        assert service.run_next_now() is True
        assert at_boundary.wait(timeout=5.0)
        # Boundary: A is durably terminal, but its one-shot thread is still alive.
        assert repository.get_job_model("A").status is JobStatus.COMPLETED
        assert runner._worker is not None and runner._worker.is_alive()
        assert runner._worker.name == "QueueWorkerOnce"

        service.set_auto_run_enabled(True, start_if_ready=True)
        proceed.set()

        _wait_until(
            lambda: all(
                repository.get_job_model(job_id).status is JobStatus.COMPLETED
                for job_id in ("B", "C")
            ),
            timeout=5.0,
        )
        assert calls == ["A", "B", "C"]  # drained, each job claimed exactly once
        assert queue.list_jobs(JobStatus.QUEUED) == []
    finally:
        proceed.set()
        runner.stop()
        service.stop()
        repository.close()


def test_resume_after_durable_completion_before_one_shot_retires_drains_queue(
    tmp_path: Path,
) -> None:
    service, queue, runner, repository, at_boundary, proceed, calls = _make_boundary_service(
        tmp_path
    )
    try:
        assert service.run_next_now() is True
        assert at_boundary.wait(timeout=5.0)
        service.auto_run_enabled = True
        service.resume()  # the path that previously skipped the continuous worker
        proceed.set()

        _wait_until(
            lambda: all(
                repository.get_job_model(job_id).status is JobStatus.COMPLETED
                for job_id in ("B", "C")
            ),
            timeout=5.0,
        )
        assert calls == ["A", "B", "C"]
    finally:
        proceed.set()
        runner.stop()
        service.stop()
        repository.close()


def test_manual_one_shot_without_auto_run_still_executes_exactly_one_job(tmp_path: Path) -> None:
    service, queue, runner, repository, at_boundary, proceed, calls = _make_boundary_service(
        tmp_path
    )
    try:
        assert service.run_next_now() is True
        assert at_boundary.wait(timeout=5.0)
        proceed.set()
        _wait_until(lambda: not runner.is_running())

        assert calls == ["A"]
        assert [job.job_id for job in queue.list_jobs(JobStatus.QUEUED)] == ["B", "C"]
    finally:
        proceed.set()
        runner.stop()
        service.stop()
        repository.close()


def test_auto_run_reenabled_after_continuous_worker_commits_to_retire_restarts_drain(
    tmp_path: Path,
) -> None:
    service, queue, runner, repository, started, release_a, calls = _make_service(tmp_path)
    service.auto_run_enabled = True
    try:
        assert service.run_next_now() is True
        assert started["A"].wait(timeout=2.0)
        service.auto_run_enabled = False
        release_a.set()
        _wait_until(lambda: repository.get_job_model("A").status is JobStatus.COMPLETED)
        # The worker has committed to retiring (it may still be unwinding).
        _wait_until(lambda: runner._worker_retiring)

        service.set_auto_run_enabled(True, start_if_ready=True)

        _wait_until(
            lambda: all(
                repository.get_job_model(job_id).status is JobStatus.COMPLETED
                for job_id in ("B", "C")
            ),
            timeout=5.0,
        )
        assert calls == ["A", "B", "C"]
    finally:
        release_a.set()
        runner.stop()
        service.stop()
        repository.close()
