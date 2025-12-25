from __future__ import annotations

import os
import threading
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

try:
    import psutil  # type: ignore[import]
except ImportError:  # pragma: no cover - optional dependency
    psutil = None  # type: ignore[assignment]

from src.queue.job_model import JobExecutionMetadata
from src.utils.error_envelope_v2 import UnifiedErrorEnvelope, wrap_exception
from src.utils.exceptions_v2 import WatchdogViolationError


def _is_test_mode() -> bool:
    # pytest sets this environment variable while tests run
    if os.environ.get("PYTEST_CURRENT_TEST"):
        return True
    # explicit override
    if os.environ.get("STABLENEW_TEST_MODE") == "1":
        return True
    return False


WATCHDOG_LOG_PREFIX = "[WATCHDOG]"


@dataclass
class WatchdogConfig:
    enabled: bool = True
    interval_sec: float = 5.0
    max_process_memory_mb: float = 4096.0
    max_job_runtime_sec: float | None = None
    max_process_idle_sec: float | None = None


@dataclass
class WatchdogViolation:
    reason: str
    pid: int | None = None
    info: dict[str, Any] = field(default_factory=dict)


class JobWatchdog(threading.Thread):
    """Daemon thread that enforces resource caps for a job's external processes."""

    def __init__(
        self,
        job_id: str,
        metadata: JobExecutionMetadata,
        config: WatchdogConfig,
        violation_callback: Callable[[str, str, dict[str, Any]], None],
        *,
        process_provider: Callable[[int], Any] | None = None,
        time_provider: Callable[[], float] | None = None,
    ) -> None:
        # PR-THREAD-001: Changed daemon=True to daemon=False
        super().__init__(daemon=False)
        self.job_id = job_id
        self._metadata = metadata
        self._config = config
        self._violation_callback = violation_callback
        self._process_provider = process_provider or self._default_process_provider
        self._time_provider = time_provider or time.monotonic
        self._stop_event = threading.Event()
        self._start_time = self._current_time()
        self._cpu_times: dict[int, float] = {}
        self._idle_since: dict[int, float] = {}

    def run(self) -> None:
        if _is_test_mode():
            return
        while not self._stop_event.wait(max(0.1, self._config.interval_sec)):
            violation = self.inspect()
            if violation is not None:
                envelope = self._build_violation_envelope(violation)
                self._violation_callback(self.job_id, envelope)
                break

    def stop(self) -> None:
        self._stop_event.set()

    def inspect(self) -> WatchdogViolation | None:
        return self._check_once()

    def _check_once(self) -> WatchdogViolation | None:
        now = self._current_time()
        violation = self._check_runtime(now)
        if violation is not None:
            return violation
        return self._check_processes(now)

    def _check_runtime(self, now: float) -> WatchdogViolation | None:
        limit = self._config.max_job_runtime_sec
        if limit is None:
            return None
        if now - self._start_time > limit:
            return WatchdogViolation(
                reason="TIMEOUT",
                info={
                    "runtime_sec": now - self._start_time,
                    "threshold_sec": limit,
                },
            )
        return None

    def _check_processes(self, now: float) -> WatchdogViolation | None:
        memory_limit = self._config.max_process_memory_mb
        idle_limit = self._config.max_process_idle_sec
        for pid in list(self._metadata.external_pids):
            proc = self._safe_process(pid)
            if proc is None:
                continue
            if memory_limit and self._check_memory(pid, proc, memory_limit):
                rss_mb = self._current_rss(proc)
                return WatchdogViolation(
                    reason="MEMORY",
                    pid=pid,
                    info={"rss_mb": rss_mb, "threshold_mb": memory_limit},
                )
            if idle_limit is not None:
                violation = self._check_idle(pid, proc, idle_limit, now)
                if violation is not None:
                    return violation
        return None

    def _check_memory(self, pid: int, proc: Any, limit_mb: float) -> bool:
        rss_mb = self._current_rss(proc)
        return rss_mb > limit_mb if limit_mb else False

    def _check_idle(
        self, pid: int, proc: Any, limit_sec: float, now: float
    ) -> WatchdogViolation | None:
        cpu_time = self._current_cpu_time(proc)
        last_cpu = self._cpu_times.get(pid)
        if last_cpu is None:
            self._cpu_times[pid] = cpu_time
            self._idle_since[pid] = now
            return None
        if cpu_time > last_cpu:
            self._idle_since[pid] = now
        else:
            idle_since = self._idle_since.get(pid, self._start_time)
            if now - idle_since > limit_sec:
                return WatchdogViolation(
                    reason="IDLE",
                    pid=pid,
                    info={"idle_sec": now - idle_since, "threshold_sec": limit_sec},
                )
        self._cpu_times[pid] = cpu_time
        return None

    def _safe_process(self, pid: int) -> Any | None:
        try:
            proc = self._process_provider(pid)
            if proc is None:
                return None
            is_running = getattr(proc, "is_running", lambda: True)()
            if not is_running:
                return None
            return proc
        except Exception:
            return None

    def _current_rss(self, proc: Any) -> float:
        try:
            info = proc.memory_info()
            return float(getattr(info, "rss", 0)) / (1024.0 * 1024.0)
        except Exception:
            return 0.0

    def _current_cpu_time(self, proc: Any) -> float:
        try:
            times = proc.cpu_times()
            return float(
                sum(
                    getattr(times, attr, 0.0)
                    for attr in ("user", "system")
                    if isinstance(getattr(times, attr, 0.0), (int, float))
                )
            )
        except Exception:
            return 0.0

    def _current_time(self) -> float:
        return float(self._time_provider())

    @staticmethod
    def _default_process_provider(pid: int) -> Any | None:
        if psutil is None:
            return None
        try:
            return psutil.Process(pid)  # type: ignore[attr-defined]
        except Exception:
            return None

    def _build_violation_envelope(self, violation: WatchdogViolation) -> UnifiedErrorEnvelope:
        exc = WatchdogViolationError(f"Watchdog violation: {violation.reason}")
        context = {"watchdog_reason": violation.reason, **(violation.info or {})}
        if violation.pid is not None:
            context.setdefault("pid", violation.pid)
        return wrap_exception(
            exc,
            subsystem="watchdog",
            job_id=self.job_id,
            context=context,
        )
