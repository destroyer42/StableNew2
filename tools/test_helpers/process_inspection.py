"""Ownership-scoped process inspection for release journey tests.

Process names, working directories, and repository keywords are not ownership
proof. Journey subprocesses therefore carry an explicit owner marker and
managed backend children carry a separate backend marker.
"""

from __future__ import annotations

import os
import subprocess
from dataclasses import dataclass
from subprocess import Popen
from typing import Any

try:
    import psutil  # type: ignore[import]
except ImportError:  # pragma: no cover
    psutil = None

STABLENEW_OWNER_ENV = "STABLENEW_TEST_OWNER_PID"
STABLENEW_RUN_ENV = "STABLENEW_TEST_RUN_ID"
MANAGED_BACKEND_ENV = "STABLENEW_TEST_MANAGED_BACKEND"
_OWNED_PROCESS_PIDS: set[int] = set()


@dataclass(frozen=True)
class _ProcessSnapshot:
    pid: int
    parent_pid: int | None
    name: str
    cmdline: str
    cwd: str
    environ: dict[str, str]


def _as_snapshot(proc: Any) -> _ProcessSnapshot | None:
    try:
        info = getattr(proc, "info", None)
        if isinstance(info, dict):
            pid = int(info.get("pid"))
            parent_pid = info.get("ppid")
            name = str(info.get("name") or "")
            cmdline = " ".join(str(item) for item in info.get("cmdline") or [])
            cwd = str(info.get("cwd") or "")
            environ = {
                str(key): str(value)
                for key, value in (info.get("environ") or {}).items()
            }
            return _ProcessSnapshot(
                pid=pid,
                parent_pid=int(parent_pid) if parent_pid is not None else None,
                name=name,
                cmdline=cmdline,
                cwd=cwd,
                environ=environ,
            )
        pid = int(proc.pid)
        parent = proc.ppid() if hasattr(proc, "ppid") else None
        name = str(proc.name() if hasattr(proc, "name") else "")
        cmdline = " ".join(
            str(item) for item in (proc.cmdline() if hasattr(proc, "cmdline") else [])
        )
        cwd = str(proc.cwd() if hasattr(proc, "cwd") else "")
        environ = dict(proc.environ()) if hasattr(proc, "environ") else {}
        return _ProcessSnapshot(
            pid,
            int(parent) if parent is not None else None,
            name,
            cmdline,
            cwd,
            environ,
        )
    except (AttributeError, OSError, TypeError, ValueError):
        return None


def _owned_by_test(snapshot: _ProcessSnapshot, *, owner_pid: int) -> bool:
    marker = snapshot.environ.get(STABLENEW_OWNER_ENV)
    if marker and marker == str(owner_pid):
        return True
    return snapshot.parent_pid == owner_pid


def _is_stablenew(snapshot: _ProcessSnapshot, *, owner_pid: int) -> bool:
    if snapshot.pid == os.getpid():
        return False
    if "python" not in snapshot.name.lower() and "python" not in snapshot.cmdline.lower():
        return False
    command = snapshot.cmdline.lower().replace("\\", "/")
    explicit_run = bool(snapshot.environ.get(STABLENEW_RUN_ENV))
    canonical_command = "-m src.main" in command or "src/main.py" in command
    return (explicit_run or canonical_command) and _owned_by_test(snapshot, owner_pid=owner_pid)


def _is_managed_backend(snapshot: _ProcessSnapshot, *, owner_pid: int) -> bool:
    if not _owned_by_test(snapshot, owner_pid=owner_pid):
        return False
    marker = snapshot.environ.get(MANAGED_BACKEND_ENV, "").lower()
    return marker in {"1", "true", "yes", "on"}


def _collect_snapshots() -> list[_ProcessSnapshot]:
    if psutil is None:
        return []
    snapshots: list[_ProcessSnapshot] = []
    try:
        iterator = psutil.process_iter(
            attrs=["pid", "ppid", "name", "cmdline", "cwd", "environ"]
        )
        for proc in iterator:
            snapshot = _as_snapshot(proc)
            if snapshot is not None:
                snapshots.append(snapshot)
    except (OSError, RuntimeError):
        return snapshots
    return snapshots


def list_stablenew_processes(*, owner_pid: int | None = None) -> list[str]:
    """Return only test-owned StableNew process candidates."""
    owner = os.getpid() if owner_pid is None else int(owner_pid)
    return [
        f"{item.pid}:{item.name}:{item.cmdline}"
        for item in _collect_snapshots()
        if _is_stablenew(item, owner_pid=owner)
    ]


def list_managed_backend_processes(*, owner_pid: int | None = None) -> list[str]:
    """Return only explicitly test-owned managed backend children."""
    owner = os.getpid() if owner_pid is None else int(owner_pid)
    return [
        f"{item.pid}:{item.name}:{item.cmdline}"
        for item in _collect_snapshots()
        if _is_managed_backend(item, owner_pid=owner)
    ]


def assert_no_stable_new_processes() -> None:
    matches = list_stablenew_processes()
    if matches:
        raise AssertionError(f"Test-owned StableNew processes still running: {matches}")


def register_test_owned_process(proc: Popen[Any]) -> None:
    """Register a subprocess so cleanup can never target an arbitrary PID."""
    pid = getattr(proc, "pid", None)
    if pid is not None:
        _OWNED_PROCESS_PIDS.add(int(pid))


def request_clean_shutdown(proc: Popen[Any]) -> None:
    pid = getattr(proc, "pid", None)
    if pid is None or int(pid) not in _OWNED_PROCESS_PIDS:
        return
    try:
        if os.name == "nt":
            proc.send_signal(subprocess.CTRL_BREAK_EVENT)
        else:
            proc.terminate()
        try:
            proc.wait(timeout=10)
        except subprocess.TimeoutExpired:
            proc.kill()
            proc.wait(timeout=5)
    finally:
        _OWNED_PROCESS_PIDS.discard(int(pid))


def assert_no_webui_processes() -> None:
    matches = list_managed_backend_processes()
    if matches:
        raise AssertionError(f"Test-owned managed backend processes still running: {matches}")
