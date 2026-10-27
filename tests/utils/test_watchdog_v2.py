"""Unit tests for the JobWatchdog helper."""

from __future__ import annotations

from collections.abc import Callable
from threading import Event
from types import SimpleNamespace

import pytest

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


@pytest.mark.parametrize("test_environment", [False, True])
def test_watchdog_run_enforces_threshold_in_both_environments(monkeypatch, test_environment):
    for name in ("PYTEST_CURRENT_TEST", "STABLENEW_TEST_MODE"):
        if test_environment:
            monkeypatch.setenv(name, "1")
        else:
            monkeypatch.delenv(name, raising=False)
    clock = Clock()
    callbacks = []
    waits = []
    watchdog = JobWatchdog(
        "threshold-job",
        JobExecutionMetadata(),
        WatchdogConfig(interval_sec=1.0, max_job_runtime_sec=2.0),
        lambda *args: callbacks.append(args),
        time_provider=clock,
        process_provider=lambda _pid: pytest.fail("no external process was registered"),
    )

    def wait(interval):
        waits.append(interval)
        assert len(waits) <= 3, "watchdog failed to enforce its configured threshold"
        clock.advance(interval)
        return False

    # Replace only this watchdog's wait; no global time/threading changes.
    monkeypatch.setattr(watchdog._stop_event, "wait", wait)
    watchdog.run()

    assert waits == [1.0, 1.0, 1.0]  # equality is permitted; strictly greater violates
    assert len(callbacks) == 1
    job_id, envelope = callbacks[0]
    assert job_id == "threshold-job"
    assert envelope.context == {
        "watchdog_reason": "TIMEOUT",
        "runtime_sec": 3.0,
        "threshold_sec": 2.0,
    }


@pytest.mark.parametrize("test_environment", [False, True])
def test_watchdog_explicit_disable_never_waits_or_inspects(monkeypatch, test_environment):
    for name in ("PYTEST_CURRENT_TEST", "STABLENEW_TEST_MODE"):
        if test_environment:
            monkeypatch.setenv(name, "1")
        else:
            monkeypatch.delenv(name, raising=False)
    watchdog = JobWatchdog(
        "disabled-job",
        JobExecutionMetadata(external_pids=[123]),
        WatchdogConfig(enabled=False),
        lambda *_a: pytest.fail("disabled watchdog delivered a violation"),
        time_provider=Clock(),
        process_provider=lambda _pid: pytest.fail("disabled watchdog inspected a process"),
    )
    monkeypatch.setattr(
        watchdog._stop_event, "wait", lambda _interval: pytest.fail("disabled watchdog waited")
    )
    watchdog.run()


def test_watchdog_stop_quiesces_owned_thread_without_late_callbacks(monkeypatch):
    clock = Clock()
    entered = Event()
    inspected = Event()
    callbacks = []
    watchdog = JobWatchdog(
        "stopped-job",
        JobExecutionMetadata(),
        WatchdogConfig(interval_sec=30.0),
        lambda *args: callbacks.append(args),
        time_provider=clock,
    )
    real_wait = watchdog._stop_event.wait

    def wait(interval):
        assert interval == 30.0
        entered.set()
        return real_wait()  # released by stop(), never thirty real seconds

    monkeypatch.setattr(watchdog._stop_event, "wait", wait)
    monkeypatch.setattr(watchdog, "inspect", lambda: inspected.set())
    watchdog.start()
    try:
        assert entered.wait(2.0), "owned watchdog did not reach its controlled wait"
    finally:
        watchdog.stop()
        watchdog.join(2.0)
    assert not watchdog.is_alive()
    assert not inspected.is_set()
    assert callbacks == []


@pytest.mark.parametrize("reason", ["MEMORY", "IDLE"])
def test_watchdog_run_enforces_fake_process_caps_with_virtual_time(monkeypatch, reason):
    clock = Clock()
    callbacks = []
    waits = []
    proc = FakeProcess(99, rss_mb=2.0, cpu_time=1.0)
    config = WatchdogConfig(
        interval_sec=1.0,
        max_process_memory_mb=1.0 if reason == "MEMORY" else 0,
        max_process_idle_sec=2.0 if reason == "IDLE" else None,
    )
    watchdog = JobWatchdog(
        "resource-job",
        JobExecutionMetadata(external_pids=[99]),
        config,
        lambda *args: callbacks.append(args),
        process_provider=_process_provider({99: proc}),
        time_provider=clock,
    )

    def wait(interval):
        waits.append(interval)
        assert len(waits) <= 4, "process-cap enforcement failed"
        clock.advance(interval)
        return False

    monkeypatch.setattr(watchdog._stop_event, "wait", wait)
    watchdog.run()
    assert waits == [1.0] * (1 if reason == "MEMORY" else 4)
    assert len(callbacks) == 1
    assert callbacks[0][1].context["watchdog_reason"] == reason
    assert callbacks[0][1].context["pid"] == 99
