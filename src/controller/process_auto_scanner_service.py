"""Background scanner and cleaner for stray Python processes."""

from __future__ import annotations

import logging
import os
import threading
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Iterable, List

try:
    import psutil  # type: ignore[import]
except ImportError:  # pragma: no cover - optional dependency
    psutil = None  # type: ignore[assignment]

logger = logging.getLogger(__name__)
REPO_ROOT = Path(__file__).resolve().parents[2]


@dataclass
class ProcessAutoScannerConfig:
    enabled: bool = True
    scan_interval_sec: float = 30.0
    idle_threshold_sec: float = 120.0
    memory_threshold_mb: float = 1024.0
    kill_timeout: float = 3.0


@dataclass
class ProcessAutoScannerSummary:
    timestamp: float | None = None
    scanned: int = 0
    killed: list[dict[str, Any]] = field(default_factory=list)


def _is_test_mode() -> bool:
    import os
    return bool(os.environ.get("PYTEST_CURRENT_TEST")) or os.environ.get("STABLENEW_TEST_MODE") == "1"

class ProcessAutoScannerService:
    def __init__(
        self,
        *,
        config: ProcessAutoScannerConfig | None = None,
        protected_pids: Callable[[], Iterable[int]] | None = None,
        start_thread: bool = True,
    ) -> None:
        self._config = config or ProcessAutoScannerConfig()
        self._protected_pids = protected_pids or (lambda: ())
        self._psutil = psutil
        self._stop_event = threading.Event()
        self._summary_lock = threading.Lock()
        self._last_summary = ProcessAutoScannerSummary()
        self._thread: threading.Thread | None = None
        if start_thread and not _is_test_mode():
            self._thread = threading.Thread(target=self._run_loop, daemon=True, name="ProcessAutoScanner")
            self._thread.start()
        elif start_thread and _is_test_mode():
            # In test mode, do not start background thread; service is a no-op
            self._thread = None

    def _run_loop(self) -> None:
        # Only run if not in test mode
        if _is_test_mode():
            return
        while not self._stop_event.wait(self.scan_interval):
            if not self.enabled:
                continue
            self.scan_once()

    @property
    def enabled(self) -> bool:
        return bool(self._config.enabled)

    @property
    def scan_interval(self) -> float:
        return max(1.0, float(self._config.scan_interval_sec))

    @property
    def summary(self) -> ProcessAutoScannerSummary:
        with self._summary_lock:
            return ProcessAutoScannerSummary(
                timestamp=self._last_summary.timestamp,
                scanned=self._last_summary.scanned,
                killed=list(self._last_summary.killed),
            )

    def set_enabled(self, value: bool) -> None:
        self._config.enabled = bool(value)

    def set_scan_interval(self, seconds: float) -> None:
        self._config.scan_interval_sec = max(1.0, float(seconds))

    def set_idle_threshold(self, seconds: float) -> None:
        self._config.idle_threshold_sec = max(0.0, float(seconds))

    def set_memory_threshold(self, mb: float) -> None:
        self._config.memory_threshold_mb = max(0.0, float(mb))

    def stop(self) -> None:
        self._stop_event.set()
        if self._thread and self._thread.is_alive():
            self._thread.join(timeout=1.0)

    def scan_once(self) -> ProcessAutoScannerSummary:
        summary = ProcessAutoScannerSummary(timestamp=time.time())
        if self._psutil is None:
            with self._summary_lock:
                self._last_summary = summary
            return summary

        protected = set(int(pid) for pid in self._protected_pids() if isinstance(pid, int))
        scanned = 0
        killed_details: list[dict[str, Any]] = []
        for proc in self._psutil.process_iter(attrs=("pid", "name", "cwd", "memory_info", "create_time")):
            if self._stop_event.is_set():
                break
            pid = getattr(proc, "pid", None)
            if pid is None or pid in protected or pid == os.getpid():
                continue
            try:
                name = proc.name().lower()
            except Exception:
                continue
            if "python" not in name:
                continue
            scanned += 1
            try:
                create_time = proc.create_time()
            except Exception:
                create_time = time.time()
            idle = time.time() - create_time
            try:
                rss = proc.memory_info().rss / (1024**2)
            except Exception:
                rss = 0.0
            if idle < self._config.idle_threshold_sec and rss < self._config.memory_threshold_mb:
                continue
            if self._is_repo_process(proc):
                continue
            killed = self._terminate_process(proc)
            if killed:
                killed_details.append(
                    {
                        "pid": pid,
                        "name": name,
                        "memory_mb": round(rss, 1),
                        "idle_sec": round(idle, 1),
                        "reason": "idle/memory",
                    }
                )
        summary.scanned = scanned
        summary.killed = killed_details
        with self._summary_lock:
            self._last_summary = summary
        return summary

    def get_status_text(self) -> str:
        summary = self.summary
        if summary.timestamp is None:
            return "Auto-scanner idle"
        killed = len(summary.killed)
        return f"Last scan: {time.strftime('%H:%M:%S', time.localtime(summary.timestamp))} scanned={summary.scanned} killed={killed}"

    def _is_repo_process(self, proc: Any) -> bool:
        try:
            cwd = proc.cwd()
            if not cwd:
                return False
            return REPO_ROOT in Path(cwd).resolve().parents or Path(cwd).resolve() == REPO_ROOT
        except Exception:
            return False

    def _terminate_process(self, proc: Any) -> bool:
        try:
            proc.terminate()
            proc.wait(timeout=self._config.kill_timeout)
            return True
        except Exception:
            try:
                proc.kill()
                proc.wait(timeout=self._config.kill_timeout)
                return True
            except Exception:
                logger.debug("Failed to kill stray process %s", getattr(proc, "pid", "unknown"), exc_info=True)
                return False
