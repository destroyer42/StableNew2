from __future__ import annotations

import logging
import os
import signal
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)
CGROUP_ROOT = Path("/sys/fs/cgroup/stablenew")


class LinuxCGroupV2:
    def __init__(
        self,
        job_id: str,
        *,
        memory_limit_mb: float | None = None,
        cpu_limit_percent: float | None = None,
        max_processes: int | None = None,
    ) -> None:
        if os.name != "posix":
            raise RuntimeError("Linux cgroup v2 container requires Linux/Posix platform.")
        if not CGROUP_ROOT.exists():
            raise RuntimeError(f"CGroup v2 root not found at {CGROUP_ROOT}")
        self._path = CGROUP_ROOT / f"stablenew-{job_id}"
        self._path.mkdir(parents=True, exist_ok=True)
        self._configure_limits(memory_limit_mb, cpu_limit_percent, max_processes)
        self._memory_limit_mb = memory_limit_mb
        self._cpu_limit_percent = cpu_limit_percent
        self._max_processes = max_processes

    def _configure_limits(self, memory_mb: float | None, cpu_percent: float | None, max_processes: int | None) -> None:
        if memory_mb is not None:
            self._write("memory.max", str(int(memory_mb * 1024 * 1024)))
        if cpu_percent is not None:
            period = 100_000
            quota = max(int(period * (cpu_percent / 100.0)), 1)
            self._write("cpu.max", f"{quota} {period}")
        if max_processes is not None:
            self._write("pids.max", str(max_processes))

    def _write(self, filename: str, value: str) -> None:
        try:
            (self._path / filename).write_text(value)
        except Exception as exc:
            logger.debug("Failed to write to %s: %s", filename, exc)

    def add_pid(self, pid: int) -> None:
        try:
            with (self._path / "cgroup.procs").open("a") as handle:
                handle.write(f"{pid}\n")
        except Exception as exc:
            logger.debug("Failed to join pid %s to cgroup: %s", pid, exc)

    def kill_all(self) -> None:
        kill_path = self._path / "cgroup.kill"
        if kill_path.exists():
            try:
                kill_path.write_text("1")
                return
            except Exception as exc:
                logger.debug("Failed to write to cgroup.kill: %s", exc)
        for pid in self._read_pids():
            try:
                os.kill(pid, signal.SIGKILL)
            except Exception:
                continue

    def _read_pids(self) -> list[int]:
        try:
            text = (self._path / "cgroup.procs").read_text()
            return [int(line) for line in text.split() if line.strip()]
        except Exception:
            return []

    def teardown(self) -> None:
        try:
            self.kill_all()
        except Exception:
            pass
        try:
            for entry in self._path.iterdir():
                entry.unlink(missing_ok=True)
            self._path.rmdir()
        except Exception as exc:
            logger.debug("Failed to remove cgroup path %s: %s", self._path, exc)

    def inspect(self) -> dict[str, Any]:
        return {
            "path": str(self._path),
            "memory_limit_mb": self._memory_limit_mb,
            "cpu_limit_percent": self._cpu_limit_percent,
            "max_processes": self._max_processes,
        }
