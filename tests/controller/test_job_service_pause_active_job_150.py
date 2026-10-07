"""PR-RUNTIME-QUEUE-150: pausing the queue never waits on, cancels, or strands around an active job.

``JobQueue`` refuses new claims atomically while paused, so ``JobService.pause()`` only has to retire an *idle*
worker. Joining a worker that is mid-job blocks the GUI thread for the whole stop timeout, and leaves a stop request
that a quick Resume cannot cancel (the queue then stalls with Auto-run ON). Real temporary SQLite stack; only the
job callable is a gated fake.
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
from tests.helpers.njr_factory import make_queue_job

DEADLINE = 10.0
PROMPT_SECONDS = 3.0  # far below the 10 s worker-join timeout the old behavior waited out


def _wait_until(predicate: Callable[[], bool], *, timeout: float = DEADLINE) -> None:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline and not predicate():
        time.sleep(0.01)
    assert predicate(), "condition did not settle before the deadline"


class _GatedStack:
    def __init__(self, tmp_path: Path) -> None:
        self.repository = JobRepository(tmp_path / "jobs.sqlite3")
        self.queue = JobQueue(repository=self.repository)
        self.executed: list[str] = []
        self.started = {"job-a": threading.Event(), "job-b": threading.Event()}
        self.release_a = threading.Event()

        def execute(job):
            self.executed.append(job.job_id)
            self.started[job.job_id].set()
            if job.job_id == "job-a":
                assert self.release_a.wait(timeout=30.0)
            return {"success": True, "variants": []}

        self.service = JobService(self.queue, run_callable=execute, require_normalized_records=True)
        self.service.auto_run_enabled = True

    def status(self, job_id: str) -> JobStatus:
        entry = self.repository.get_job(job_id)
        assert entry is not None
        return entry.status

    def start_job_a_running(self) -> None:
        self.service.enqueue(make_queue_job("job-a"))
        self.service.run_next_now()  # Auto-run ON: starts the continuous worker
        assert self.started["job-a"].wait(timeout=DEADLINE)

    def close(self) -> None:
        self.release_a.set()
        self.service.stop()
        self.repository.close()


@pytest.fixture
def stack(tmp_path):
    built = _GatedStack(tmp_path)
    yield built
    built.close()


def test_pause_during_an_active_job_returns_promptly_and_leaves_the_job_alone(stack: _GatedStack) -> None:
    stack.start_job_a_running()

    started_at = time.monotonic()
    stack.service.pause()
    elapsed = time.monotonic() - started_at

    assert elapsed < PROMPT_SECONDS
    assert stack.queue.is_paused() is True
    assert stack.repository.get_setting("queue_paused", False) is True
    assert stack.status("job-a") is JobStatus.RUNNING  # pause never cancels the active job
    assert stack.service.runner.is_running() is True

    stack.service.enqueue(make_queue_job("job-b"))
    stack.release_a.set()
    _wait_until(lambda: stack.status("job-a") is JobStatus.COMPLETED)
    time.sleep(0.3)  # give a (wrongly) unpaused worker every chance to claim job-b
    assert stack.executed == ["job-a"]
    assert stack.status("job-b") is JobStatus.QUEUED


def test_resume_while_the_paused_job_is_still_running_does_not_strand_the_queue(stack: _GatedStack) -> None:
    stack.start_job_a_running()
    stack.service.enqueue(make_queue_job("job-b"))

    stack.service.pause()
    stack.service.resume()  # Auto-run ON, worker still busy with job-a
    stack.release_a.set()

    assert stack.started["job-b"].wait(timeout=DEADLINE), "queue stranded after pause/resume around an active job"
    _wait_until(lambda: stack.status("job-b") is JobStatus.COMPLETED)
    assert stack.executed == ["job-a", "job-b"]


def test_pause_of_an_idle_worker_still_retires_it_and_resume_restarts_it(stack: _GatedStack) -> None:
    stack.release_a.set()
    stack.service.enqueue(make_queue_job("job-a"))
    stack.service.run_next_now()
    _wait_until(lambda: stack.status("job-a") is JobStatus.COMPLETED)
    stack.service.enqueue(make_queue_job("job-b"))
    _wait_until(lambda: stack.status("job-b") is JobStatus.COMPLETED)
    _wait_until(lambda: stack.service.runner.is_running())  # idle continuous worker polling an empty queue

    stack.service.pause()

    assert stack.service.runner.is_running() is False  # idle worker retired (existing lifecycle preserved)
    stack.service.resume()
    assert stack.service.runner.is_running() is True
