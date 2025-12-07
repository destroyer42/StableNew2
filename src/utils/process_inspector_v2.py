"""Utilities for inspecting and describing Python processes."""

from __future__ import annotations

import time
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Iterator

from src.utils.logging_helpers_v2 import PROCESS_LOG_PREFIX, format_cmdline

try:
    import psutil  # type: ignore[import]
except ImportError:  # pragma: no cover - pip install required by Phase 0
    psutil = None  # type: ignore[assignment]

REPO_ROOT = Path(__file__).resolve().parents[2]
_PYTHON_EXECUTABLES = {
    "python",
    "python.exe",
    "pythonw.exe",
    "py.exe",
    "python3",
    "python3.exe",
}
_KNOWN_SCRIPT_NAMES = {"a1111_upscale_folder.py", "gui_run_packs.py", "launch_webui.py"}
_ENV_PREFIX = "STABLENEW_"


@dataclass(frozen=True)
class ProcessInfo:
    pid: int
    name: str | None
    cmdline: tuple[str, ...]
    cwd: str | None
    create_time: float | None
    env_markers: tuple[str, ...]


def iter_python_processes() -> Iterator[ProcessInfo]:
    """Yield lightweight info for every Python process psutil can observe."""

    if psutil is None:
        return

    attrs = ("pid", "name", "cmdline", "cwd", "create_time", "environ")
    for proc in psutil.process_iter(attrs=attrs):
        try:
            info = proc.info
        except (psutil.NoSuchProcess, psutil.ZombieProcess, psutil.AccessDenied):  # type: ignore[attr-defined]
            continue
        except Exception:  # pragma: no cover - defensive fallback
            continue

        name = (info.get("name") or "").lower()
        if name not in _PYTHON_EXECUTABLES:
            continue

        raw_cmd = info.get("cmdline") or []
        cmdline = tuple(str(part) for part in raw_cmd if part)
        if not cmdline:
            continue

        env_markers = _collect_env_markers(info.get("environ"))
        yield ProcessInfo(
            pid=int(info.get("pid") or 0),
            name=info.get("name"),
            cmdline=cmdline,
            cwd=str(info.get("cwd")) if info.get("cwd") else None,
            create_time=_safe_float(info.get("create_time")),
            env_markers=env_markers,
        )


def iter_stablenew_like_processes() -> Iterator[ProcessInfo]:
    """Return Python processes that look like they belong to StableNew."""

    for process in iter_python_processes():
        if _shares_repo_path(process.cwd):
            yield process
            continue
        if _matches_known_script(process.cmdline):
            yield process
            continue
        if process.env_markers:
            yield process


def format_process_brief(process: ProcessInfo) -> str:
    """Render a short informational string for the GUI log."""

    segments = [PROCESS_LOG_PREFIX, "inspector", f"pid={process.pid}"]
    if process.name:
        segments.append(f"name={process.name}")
    segments.append(f'cmd="{format_cmdline(process.cmdline)}"')
    if process.cwd:
        segments.append(f'cwd="{process.cwd}"')
    if process.create_time:
        uptime = max(0.0, time.time() - process.create_time)
        segments.append(f"uptime={int(uptime)}s")
    if process.env_markers:
        segments.append(f"env={','.join(process.env_markers)}")
    return " ".join(segments)


def _collect_env_markers(env: Mapping[str, str] | None) -> tuple[str, ...]:
    if not env:
        return ()
    markers = [f"{key}={value}" for key, value in env.items() if key.startswith(_ENV_PREFIX)]
    return tuple(markers)


def _matches_known_script(cmdline: Sequence[str]) -> bool:
    lowered = {part.lower() for part in cmdline}
    for script in _KNOWN_SCRIPT_NAMES:
        if any(script in part for part in lowered):
            return True
    return False


def _shares_repo_path(cwd: str | None) -> bool:
    if not cwd:
        return False
    try:
        cwd_path = Path(cwd).resolve()
    except Exception:
        return False
    return REPO_ROOT == cwd_path or REPO_ROOT in cwd_path.parents


def _safe_float(value: object | None) -> float | None:
    try:
        if value is None:
            return None
        return float(value)
    except (TypeError, ValueError):
        return None
