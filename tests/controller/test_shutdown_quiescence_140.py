"""PR-RUNTIME-SHUTDOWN-140: the real ``AppController.shutdown_app`` path over a real queue stack.

Real temporary ``JobRepository`` + ``JobQueue`` + ``JobService`` + ``SingleNodeJobRunner`` worker threads; only the
job callable and the WebUI manager are fakes. This is the reproduced production sequence: active A + queued B, A is
cancelled by shutdown, runtime teardown takes real time, then the repository is closed. Before the repair B was
claimed as RUNNING after shutdown began and the repository could be closed underneath a live worker.
"""

from __future__ import annotations

import importlib
import logging
import threading
import time
from collections.abc import Callable
from pathlib import Path

import pytest

from src.api.webui_process_manager import clear_global_webui_process_manager
from src.controller.app_controller import AppController
from src.controller.job_service import JobService
from src.gui.app_state_v2 import AppStateV2
from src.queue.job_model import JobStatus
from src.queue.job_queue import JobQueue
from src.queue.job_repository import JobRepository
from src.queue.single_node_runner import SingleNodeJobRunner
from tests.helpers.njr_factory import make_queue_job

DEADLINE = 15.0


def _wait_until(predicate: Callable[[], bool], *, timeout: float = DEADLINE) -> None:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if predicate():
            return
        time.sleep(0.005)
    assert predicate(), "condition did not settle before the deadline"


def _quiescent(runner: SingleNodeJobRunner) -> bool:
    """True when no queue worker thread of ``runner`` is alive (works before and after the repair)."""

    query = getattr(runner, "is_quiescent", None)
    if callable(query):
        return bool(query())
    worker = runner._worker
    return worker is None or not worker.is_alive()


class RecordingRepository(JobRepository):
    """A real SQLite repository that records when it is closed and whether a queue worker was still alive."""

    def __init__(self, path: Path) -> None:
        super().__init__(path)
        self.events: list[str] = []
        self.close_calls = 0
        self.worker_alive_at_close: bool | None = None
        self.worker_probe: Callable[[], bool] = lambda: False

    def close(self) -> None:
        self.close_calls += 1
        self.worker_alive_at_close = bool(self.worker_probe())
        self.events.append("repository.close")
        super().close()


class RecordingWebUI:
    """Runtime teardown takes real time: it returns once the cancelled worker has unwound (as in production)."""

    def __init__(self, events: list[str], unwound: Callable[[], bool]) -> None:
        self._events = events
        self._unwound = unwound

    def stop_webui(self, *args, **kwargs) -> bool:
        self._events.append("webui.stop")
        deadline = time.monotonic() + 3.0
        while time.monotonic() < deadline and not self._unwound():
            time.sleep(0.005)
        return True


class Harness:
    def __init__(self, tmp_path: Path, *, ignore_cancel: bool = False, job_ids=("A", "B", "C")) -> None:
        self.path = tmp_path / "jobs.sqlite3"
        self.repository = RecordingRepository(self.path)
        self.queue = JobQueue(repository=self.repository)
        self.started = {job_id: threading.Event() for job_id in job_ids}
        self.release = {job_id: threading.Event() for job_id in job_ids}
        self.ignore_cancel = ignore_cancel
        self.runner = SingleNodeJobRunner(self.queue, self._execute, poll_interval=0.005)
        self.service = JobService(self.queue, runner=self.runner, require_normalized_records=True)
        self.repository.worker_probe = lambda: not _quiescent(self.runner)
        for job_id in job_ids:
            self.service.submit_queued(make_queue_job(job_id), emit_queue_updated=False)
        self.service.auto_run_enabled = True
        clear_global_webui_process_manager()
        self.webui = RecordingWebUI(
            self.repository.events,
            lambda: self.started["B"].is_set() or _quiescent(self.runner) or self.ignore_cancel,
        )
        self.controller = AppController(
            None, threaded=False, job_service=self.service, webui_process_manager=self.webui
        )
        self.controller.app_state = AppStateV2()
        # wrap the two lifecycle entry points so their order relative to the WebUI teardown is observable
        real_cancel = self.service.cancel_current
        self.service.cancel_current = self._recording("service.cancel_current", real_cancel)  # type: ignore[method-assign]
        fence = getattr(self.service, "begin_shutdown", None)
        if callable(fence):
            self.service.begin_shutdown = self._recording("service.begin_shutdown", fence)  # type: ignore[method-assign]

    def _recording(self, label: str, fn: Callable):
        def wrapper(*args, **kwargs):
            self.repository.events.append(label)
            return fn(*args, **kwargs)

        return wrapper

    def _execute(self, job):
        self.started[job.job_id].set()
        token = getattr(job, "_cancel_token", None)
        deadline = time.monotonic() + DEADLINE
        while time.monotonic() < deadline and not self.release[job.job_id].is_set():
            if not self.ignore_cancel and token is not None and token.is_cancelled():
                break
            time.sleep(0.002)
        return {"success": True, "variants": []}

    def status(self, job_id: str) -> JobStatus:
        """Durable status through a fresh connection (shutdown legitimately closes the shared repository)."""

        reader = JobRepository(self.path)
        try:
            return reader.get_job_model(job_id).status
        finally:
            reader.close()

    def cleanup(self) -> None:
        for event in self.release.values():
            event.set()
        _wait_until(lambda: _quiescent(self.runner), timeout=DEADLINE)
        if self.repository.close_calls == 0:
            self.repository.close()


def _shorten_quiesce_timeout(monkeypatch: pytest.MonkeyPatch, seconds: float) -> None:
    try:
        module = importlib.import_module("src.controller.app_controller_services.shutdown_coordinator")
    except ImportError:  # before the repair there is no bounded quiescence step at all
        return
    monkeypatch.setattr(module, "QUEUE_QUIESCE_TIMEOUT_SECONDS", seconds, raising=True)


@pytest.fixture
def thread_errors(monkeypatch: pytest.MonkeyPatch) -> list[str]:
    errors: list[str] = []
    monkeypatch.setattr(
        threading,
        "excepthook",
        lambda args: errors.append(f"{args.thread.name if args.thread else '?'}: {args.exc_type.__name__}: {args.exc_value}"),
    )
    return errors


@pytest.fixture
def harness(tmp_path: Path):
    built = Harness(tmp_path)
    yield built
    built.cleanup()


def _start_active_job(harness: Harness) -> None:
    assert harness.service.run_next_now() is True
    assert harness.started["A"].wait(DEADLINE)


# --- the reproduced sequence ---------------------------------------------------------------------


def test_shutdown_never_starts_the_queued_job_and_closes_the_repository_only_after_quiescence(
    harness: Harness, thread_errors: list[str]
) -> None:
    _start_active_job(harness)

    harness.controller.shutdown_app("race-140")

    assert harness.started["B"].is_set() is False, "B acquired RUNNING after shutdown began"
    assert [harness.status(j) for j in ("B", "C")] == [JobStatus.QUEUED, JobStatus.QUEUED]
    assert harness.status("A") is JobStatus.CANCELLED  # the active job follows the existing cancellation semantics
    assert harness.repository.close_calls == 1
    assert harness.repository.worker_alive_at_close is False, "the repository was closed under a live queue worker"
    assert thread_errors == [], thread_errors


def test_the_admission_fence_precedes_cancellation_and_runtime_teardown(harness: Harness) -> None:
    _start_active_job(harness)

    harness.controller.shutdown_app("order-140")

    events = [e for e in harness.repository.events if e != "repository.close"]
    assert "service.begin_shutdown" in events, "shutdown never fenced queue admission"
    fence = events.index("service.begin_shutdown")
    assert fence < events.index("service.cancel_current")
    assert fence < events.index("webui.stop")
    assert harness.repository.events[-1] == "repository.close"


def test_a_worker_that_cannot_quiesce_keeps_the_repository_open_and_is_reported(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture, thread_errors: list[str]
) -> None:
    built = Harness(tmp_path, ignore_cancel=True)
    _shorten_quiesce_timeout(monkeypatch, 0.3)
    try:
        _start_active_job(built)
        with caplog.at_level(logging.ERROR):
            built.controller.shutdown_app("wedged-140")

        assert built.repository.close_calls == 0, "SQLite was closed underneath a live queue worker"
        text = "\n".join(record.getMessage() for record in caplog.records)
        assert "did not quiesce" in text
        assert "Job repository closed" not in text  # no normal success line
        assert built.started["B"].is_set() is False

        built.release["A"].set()  # the stuck backend finally returns: the worker must unwind with the repository open
        _wait_until(lambda: _quiescent(built.runner))
        assert built.status("A") in {JobStatus.CANCELLED, JobStatus.COMPLETED}
        assert built.status("B") is JobStatus.QUEUED
        assert thread_errors == [], thread_errors
    finally:
        built.cleanup()


def test_idle_shutdown_and_repeated_shutdown_are_safe(tmp_path: Path, thread_errors: list[str]) -> None:
    built = Harness(tmp_path, job_ids=())
    try:
        built.controller.shutdown_app("idle-140")
        built.controller.shutdown_app("again-140")

        assert built.repository.close_calls == 1
        assert built.repository.worker_alive_at_close is False
        assert thread_errors == []
    finally:
        built.cleanup()
