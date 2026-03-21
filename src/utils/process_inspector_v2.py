"""Utilities for inspecting and describing Python processes."""

from __future__ import annotations

import shutil
import subprocess
import time
from collections.abc import Iterator, Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path

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
    parent_pid: int | None
    name: str | None
    cmdline: tuple[str, ...]
    cwd: str | None
    create_time: float | None
    rss_mb: float | None
    env_markers: tuple[str, ...]


def iter_python_processes() -> Iterator[ProcessInfo]:
    """Yield lightweight info for every Python process psutil can observe."""
    if psutil is None:
        return

    # Keep attrs minimal/safe. Do NOT include "cmdline" or "environ" here.
    safe_attrs = ("pid", "ppid", "name", "cwd", "create_time")

    for proc in psutil.process_iter(attrs=safe_attrs):
        try:
            info = proc.info
        except (psutil.NoSuchProcess, psutil.ZombieProcess, psutil.AccessDenied):  # type: ignore[attr-defined]
            continue
        except Exception:
            continue

        # Name check (best-effort)
        raw_name = info.get("name") or ""
        name_lower = raw_name.lower()
        if name_lower not in _PYTHON_EXECUTABLES:
            continue

        pid = int(info.get("pid") or 0)
        parent_pid = _safe_int(info.get("ppid"))

        # cmdline (guarded; may throw WinError 87 / AccessDenied)
        cmdline: tuple[str, ...]
        try:
            raw_cmd = proc.cmdline()
            cmdline = tuple(str(part) for part in (raw_cmd or []) if part)
        except (psutil.NoSuchProcess, psutil.ZombieProcess, psutil.AccessDenied, OSError):  # type: ignore[attr-defined]
            continue
        except Exception:
            continue

        if not cmdline:
            continue

        # cwd/create_time from safe info (guarded conversion)
        cwd_val = info.get("cwd")
        cwd = str(cwd_val) if cwd_val else None
        create_time = _safe_float(info.get("create_time"))
        rss_mb = None
        try:
            memory_info = proc.memory_info()
            rss_mb = round(float(getattr(memory_info, "rss", 0.0) or 0.0) / (1024 * 1024), 1)
        except (psutil.NoSuchProcess, psutil.ZombieProcess, psutil.AccessDenied, OSError):  # type: ignore[attr-defined]
            rss_mb = None
        except Exception:
            rss_mb = None

        # Decide whether to attempt environ().
        # Only do this if cwd/cmdline already looks like it might be ours.
        env_markers: tuple[str, ...] = ()
        looks_stablenew = _shares_repo_path(cwd) or _matches_known_script(cmdline)
        if looks_stablenew:
            try:
                env = proc.environ()
            except (psutil.NoSuchProcess, psutil.ZombieProcess, psutil.AccessDenied, OSError):  # type: ignore[attr-defined]
                env = None
            except Exception:
                env = None
            env_markers = _collect_env_markers(env)

        yield ProcessInfo(
            pid=pid,
            parent_pid=parent_pid,
            name=raw_name or None,
            cmdline=cmdline,
            cwd=cwd,
            create_time=create_time,
            rss_mb=rss_mb,
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
    if process.parent_pid:
        segments.append(f"ppid={process.parent_pid}")
    if process.name:
        segments.append(f"name={process.name}")
    segments.append(f'cmd="{format_cmdline(process.cmdline)}"')
    if process.cwd:
        segments.append(f'cwd="{process.cwd}"')
    if process.create_time:
        uptime = max(0.0, time.time() - process.create_time)
        segments.append(f"uptime={int(uptime)}s")
    if process.rss_mb is not None:
        segments.append(f"rss_mb={process.rss_mb:.1f}")
    if process.env_markers:
        segments.append(f"env={','.join(process.env_markers)}")
    return " ".join(segments)


def collect_gpu_snapshot() -> dict[str, object] | None:
    """Best-effort GPU snapshot via nvidia-smi when available."""

    nvidia_smi = shutil.which("nvidia-smi")
    if not nvidia_smi:
        return None
    command = [
        nvidia_smi,
        "--query-gpu=index,name,utilization.gpu,memory.total,memory.used,memory.free,temperature.gpu",
        "--format=csv,noheader,nounits",
    ]
    try:
        result = subprocess.run(
            command,
            capture_output=True,
            text=True,
            timeout=5.0,
            check=False,
        )
    except Exception:
        return None
    if result.returncode != 0 or not result.stdout.strip():
        return None

    devices: list[dict[str, object]] = []
    for line in result.stdout.splitlines():
        parts = [part.strip() for part in line.split(",")]
        if len(parts) < 7:
            continue
        try:
            devices.append(
                {
                    "index": int(parts[0]),
                    "name": parts[1],
                    "utilization_gpu_pct": float(parts[2]),
                    "memory_total_mb": float(parts[3]),
                    "memory_used_mb": float(parts[4]),
                    "memory_free_mb": float(parts[5]),
                    "temperature_c": float(parts[6]),
                }
            )
        except Exception:
            continue
    if not devices:
        return None
    return {"provider": "nvidia-smi", "devices": devices}


def collect_process_risk_snapshot(
    *,
    rss_mb_threshold: float = 512.0,
    age_s_threshold: float = 300.0,
) -> dict[str, object]:
    """Summarize suspicious StableNew-adjacent Python process state."""

    processes = list(iter_stablenew_like_processes())
    now = time.time()
    main_processes = [proc for proc in processes if _is_stablenew_main_process(proc.cmdline)]
    webui_processes = [proc for proc in processes if _is_webui_process(proc.cmdline, proc.cwd)]

    suspicious: list[dict[str, object]] = []
    for proc in processes:
        reasons: list[str] = []
        age_s = max(0.0, now - proc.create_time) if proc.create_time else None
        if proc.rss_mb is not None and proc.rss_mb >= rss_mb_threshold:
            reasons.append(f"high_rss_{int(rss_mb_threshold)}mb_plus")
        if age_s is not None and age_s >= age_s_threshold and _is_pytest_process(proc.cmdline):
            reasons.append("stale_pytest_process")
        if len(main_processes) > 1 and _is_stablenew_main_process(proc.cmdline):
            reasons.append("duplicate_stablenew_main")
        if len(webui_processes) > 1 and _is_webui_process(proc.cmdline, proc.cwd):
            reasons.append("duplicate_webui_process")
        if not reasons:
            continue
        suspicious.append(
            {
                "pid": proc.pid,
                "parent_pid": proc.parent_pid,
                "rss_mb": proc.rss_mb,
                "age_s": round(age_s, 1) if age_s is not None else None,
                "cmd": format_cmdline(proc.cmdline),
                "cwd": proc.cwd,
                "reasons": reasons,
            }
        )

    status = "normal"
    if suspicious:
        status = "warning"
    if len(main_processes) > 1 or len(webui_processes) > 1:
        status = "critical"

    return {
        "status": status,
        "stablenew_like_count": len(processes),
        "main_process_count": len(main_processes),
        "webui_process_count": len(webui_processes),
        "suspicious_processes": suspicious,
    }


def _collect_env_markers(env: Mapping[str, str] | None) -> tuple[str, ...]:
    if not env:
        return ()
    markers: list[str] = []
    for key, value in env.items():
        try:
            if str(key).startswith(_ENV_PREFIX):
                markers.append(f"{key}={value}")
        except Exception:
            continue
    return tuple(markers)


def _matches_known_script(cmdline: Sequence[str]) -> bool:
    lowered = {part.lower() for part in cmdline}
    for script in _KNOWN_SCRIPT_NAMES:
        if any(script in part for part in lowered):
            return True
    return False


def _is_stablenew_main_process(cmdline: Sequence[str]) -> bool:
    rendered = " ".join(part.lower() for part in cmdline)
    return "-m src.main" in rendered or "\\src\\main.py" in rendered or "/src/main.py" in rendered


def _is_webui_process(cmdline: Sequence[str], cwd: str | None) -> bool:
    rendered = " ".join(part.lower() for part in cmdline)
    return (
        "stable-diffusion-webui" in rendered
        or " launch.py" in rendered
        or (cwd or "").lower().find("stable-diffusion-webui") >= 0
    )


def _is_pytest_process(cmdline: Sequence[str]) -> bool:
    rendered = " ".join(part.lower() for part in cmdline)
    return "pytest" in rendered


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


def _safe_int(value: object | None) -> int | None:
    try:
        if value is None:
            return None
        return int(value)
    except (TypeError, ValueError):
        return None
