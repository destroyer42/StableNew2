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


def test_reenabling_auto_run_restarts_retired_worker_and_drains_remaining_jobs(tmp_path: Path) -> None:
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
