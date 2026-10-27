"""Tests for JobService watchdog wiring (Phase 3)."""

from __future__ import annotations

from typing import Any

from src.controller import job_service as job_service_module
from src.controller.job_service import JobService
from src.queue.job_model import Job
from src.queue.job_queue import JobQueue
from src.queue.job_repository import JobRepository
from src.utils.error_envelope_v2 import wrap_exception
from src.utils.exceptions_v2 import WatchdogViolationError
from src.utils.watchdog_v2 import WatchdogConfig
from tests.helpers.njr_factory import make_queue_job


class DummyRunner:
    def __init__(self) -> None:
        self.current_job: Any = None

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


class FakeWatchdog:
    def __init__(
        self, job_id: str, metadata: Any, config: WatchdogConfig, violation_callback: Any
    ) -> None:
        self.job_id = job_id
        self.metadata = metadata
        self.config = config
        self.violation_callback = violation_callback

    def start(self) -> None:
        exc = WatchdogViolationError("Watchdog memory violation")
        envelope = wrap_exception(
            exc,
            subsystem="watchdog",
            job_id=self.job_id,
            context={"watchdog_reason": "MEMORY", "pid": 1},
        )
        self.violation_callback(self.job_id, envelope)

    def stop(self) -> None:
        pass


def test_watchdog_violation_triggers_cancel(monkeypatch) -> None:
    job_queue = JobQueue()
    runner = DummyRunner()
    config = WatchdogConfig(enabled=True, interval_sec=0.1)
    service = JobService(job_queue, runner, watchdog_config=config)
    job = make_queue_job("job-watchdog")
    job_queue.submit(job)

    cancellation: list[tuple[str, str | None]] = []

    def fake_cancel(job_id: str, *, reason: str | None = None) -> None:
        cancellation.append((job_id, reason))

    monkeypatch.setattr(job_service_module, "JobWatchdog", FakeWatchdog)
    service.cancel_job = fake_cancel  # type: ignore[assignment]

    job_queue.mark_running(job.job_id)

    assert cancellation == [("job-watchdog", "watchdog_memory")]


def test_real_watchdog_threshold_cancels_only_its_isolated_job(monkeypatch, tmp_path):
    """Real enforcement -> real JobService cancellation -> temporary SQLite readback."""
    from src.queue.job_model import JobStatus
    from src.utils.watchdog_v2 import JobWatchdog

    elapsed = [0.0]
    watchdogs = []
    repository = JobRepository(tmp_path / "jobs.sqlite3")
    queue = JobQueue(repository=repository)
    service = JobService(
        queue,
        DummyRunner(),
        watchdog_config=WatchdogConfig(max_job_runtime_sec=2.0, interval_sec=1.0),
    )

    def build_watchdog(**kwargs):
        watchdog = JobWatchdog(
            **kwargs, time_provider=lambda: elapsed[0], process_provider=lambda _pid: None
        )
        waits = []

        def wait(interval):
            waits.append(interval)
            assert len(waits) <= 3
            elapsed[0] += interval
            return False

        monkeypatch.setattr(watchdog._stop_event, "wait", wait)
        # Synchronous start drives the real run loop with no scheduling dependency.
        monkeypatch.setattr(watchdog, "start", watchdog.run)
        watchdogs.append(watchdog)
        return watchdog

    monkeypatch.setattr(job_service_module, "JobWatchdog", build_watchdog)
    try:
        queue.submit(make_queue_job("threshold-job"))
        queue.submit(make_queue_job("neighbor-job"))
        queue.mark_running("threshold-job")
        assert repository.get_job_model("threshold-job").status is JobStatus.CANCELLED
        assert repository.get_job_model("neighbor-job").status is JobStatus.QUEUED
        assert len(service._watchdog_event_history) == 1
        assert service._watchdog_event_history[0]["reason"] == "TIMEOUT"
        assert service._active_watchdogs == {}
        assert len(watchdogs) == 1
        assert watchdogs[0]._stop_event.is_set()
    finally:
        service.stop()
        repository.close()
