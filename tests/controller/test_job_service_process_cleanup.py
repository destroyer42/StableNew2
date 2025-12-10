"""Unit tests for the JobService external process cleanup hooks."""

from __future__ import annotations

from typing import List, Tuple

import pytest

from src.controller import job_service as job_service_module
from src.controller.job_service import JobService
from src.queue.job_model import Job
from src.queue.job_queue import JobQueue


class DummyRunner:
    def __init__(self) -> None:
        self.current_job = None

    def start(self) -> None:
        pass

    def stop(self) -> None:
        pass

    def is_running(self) -> bool:
        return False

    def run_once(self, job: Job) -> dict[str, object]:
        self.current_job = job
        return {}

    def cancel_current(self) -> None:
        self.current_job = None


def test_cleanup_external_processes_terminates_pids(monkeypatch) -> None:
    job_queue = JobQueue()
    runner = DummyRunner()
    service = JobService(job_queue, runner)
    job = Job(job_id="job-123")
    job_queue.submit(job)
    service.register_external_process(job.job_id, 42)

    calls: List[Tuple[str, int]] = []

    class FakeProcess:
        def __init__(self, pid: int) -> None:
            self.pid = pid

        def children(self, recursive: bool = False) -> list["FakeProcess"]:
            return []

        def terminate(self) -> None:
            calls.append(("terminate", self.pid))

        def wait(self, timeout: float | None = None) -> None:
            calls.append(("wait", self.pid))

        def kill(self) -> None:
            calls.append(("kill", self.pid))


    class FakePsutil:
        class NoSuchProcess(Exception):
            pass

        class ZombieProcess(Exception):
            pass

        class TimeoutExpired(Exception):
            pass

        @staticmethod
        def Process(pid: int) -> FakeProcess:
            return FakeProcess(pid)

    monkeypatch.setattr(job_service_module, "psutil", FakePsutil)

    service.cleanup_external_processes(job.job_id)
    assert ("terminate", 42) in calls
    assert ("wait", 42) in calls

    previous_calls = list(calls)
    service.cleanup_external_processes(job.job_id)
    assert calls == previous_calls


def test_register_external_process_records_job_metadata() -> None:
    job_queue = JobQueue()
    runner = DummyRunner()
    service = JobService(job_queue, runner)
    job = Job(job_id="job-meta")
    job_queue.submit(job)

    service.register_external_process(job.job_id, 99)

    assert job.execution_metadata.external_pids == [99]


def test_cancel_current_uses_queue_running_job(monkeypatch) -> None:
    job_queue = JobQueue()
    runner = DummyRunner()
    service = JobService(job_queue, runner)
    job = Job(job_id="job-run")
    job_queue.submit(job)
    job_queue.mark_running(job.job_id)
    registered: list[tuple[str, str]] = []

    def fake_cancel_job(job_id: str, *, reason: str | None = None) -> None:
        registered.append((job_id, reason or ""))

    service.cancel_job = fake_cancel_job  # type: ignore[assignment]

    cancelled_job = service.cancel_current()

    assert cancelled_job is not None
    assert registered == [("job-run", "cancel_requested")]
