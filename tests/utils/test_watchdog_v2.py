"""Unit tests for the JobWatchdog helper."""

from __future__ import annotations

from types import SimpleNamespace
from typing import Callable

from src.queue.job_model import JobExecutionMetadata
from src.utils.watchdog_v2 import JobWatchdog, WatchdogConfig, WatchdogViolation


class Clock:
    def __init__(self) -> None:
        self.value = 0.0

    def __call__(self) -> float:
        return self.value

    def advance(self, amount: float) -> None:
        self.value += amount


class FakeProcess:
    def __init__(self, pid: int, rss_mb: float, cpu_time: float) -> None:
        self.pid = pid
        self._rss_bytes = int(rss_mb * 1024 * 1024)
        self._cpu_time = cpu_time

    def memory_info(self) -> SimpleNamespace:
        return SimpleNamespace(rss=self._rss_bytes)

    def cpu_times(self) -> SimpleNamespace:
        return SimpleNamespace(user=self._cpu_time, system=0.0)

    def is_running(self) -> bool:
        return True


def _process_provider(pid_to_proc: dict[int, FakeProcess]) -> Callable[[int], FakeProcess | None]:
    return lambda pid: pid_to_proc.get(pid)


def test_watchdog_detects_memory_violation() -> None:
    metadata = JobExecutionMetadata(external_pids=[99])
    config = WatchdogConfig(max_process_memory_mb=1.0, interval_sec=1.0)
    proc = FakeProcess(99, rss_mb=8.0, cpu_time=0.1)
    clock = Clock()

    watchdog = JobWatchdog(
        job_id="job-memory",
        metadata=metadata,
        config=config,
        violation_callback=lambda *_: None,
        process_provider=_process_provider({99: proc}),
        time_provider=clock,
    )

    violation = watchdog.inspect()

    assert isinstance(violation, WatchdogViolation)
    assert violation.reason == "MEMORY"
    assert violation.pid == 99


def test_watchdog_detects_runtime_violation() -> None:
    metadata = JobExecutionMetadata(external_pids=[])
    config = WatchdogConfig(max_job_runtime_sec=2.0, interval_sec=0.5)
    clock = Clock()

    watchdog = JobWatchdog(
        job_id="job-runtime",
        metadata=metadata,
        config=config,
        violation_callback=lambda *_: None,
        process_provider=lambda _: None,
        time_provider=clock,
    )

    clock.advance(3.0)
    violation = watchdog.inspect()

    assert isinstance(violation, WatchdogViolation)
    assert violation.reason == "TIMEOUT"
    assert violation.pid is None


def test_watchdog_detects_idle_violation() -> None:
    metadata = JobExecutionMetadata(external_pids=[42])
    config = WatchdogConfig(max_process_idle_sec=2.0, interval_sec=0.5)
    proc = FakeProcess(42, rss_mb=0.2, cpu_time=1.0)
    clock = Clock()

    watchdog = JobWatchdog(
        job_id="job-idle",
        metadata=metadata,
        config=config,
        violation_callback=lambda *_: None,
        process_provider=_process_provider({42: proc}),
        time_provider=clock,
    )

    # Prime the idle tracker
    watchdog.inspect()
    clock.advance(3.0)

    violation = watchdog.inspect()

    assert isinstance(violation, WatchdogViolation)
    assert violation.reason == "IDLE"
    assert violation.pid == 42
