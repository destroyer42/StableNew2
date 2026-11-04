"""Read-only host observation shared by the physical plan and the readiness report.

Every probe observes; none starts, stops, adopts or configures anything.  ``HostProbes`` is injectable so tests (and the
plan digest comparison) never depend on this machine.
"""

from __future__ import annotations

import json
import os
import platform
import shutil
import subprocess
import sys
import urllib.error
import urllib.request
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from tools.operator_journey.golden.media import sha256_file
from tools.operator_journey.workspace import REPO_ROOT, repo_sha

# Process image names that identify a generation runtime or trainer (observed, never signalled).
RUNTIME_PROCESS_HINTS = ("webui", "forge", "comfy", "launch.py", "main.py")


def _nvidia_smi(query: str) -> list[list[str]] | None:
    try:
        out = subprocess.check_output(
            ["nvidia-smi", f"--query-gpu={query}", "--format=csv,noheader,nounits"],
            text=True,
            timeout=10,
            stderr=subprocess.DEVNULL,
        )
    except (OSError, subprocess.SubprocessError):
        return None
    rows = [
        [cell.strip() for cell in line.split(",")]
        for line in out.strip().splitlines()
        if line.strip()
    ]
    return rows or None


def probe_gpu() -> dict[str, Any] | None:
    rows = _nvidia_smi("name,driver_version,memory.total,memory.used,memory.free,uuid")
    if not rows:
        return None
    try:
        name, driver, total, used, free, uuid = rows[0]
        return {
            "name": name,
            "driver": driver,
            "total_mib": float(total),
            "used_mib": float(used),
            "free_mib": float(free),
            "uuid": uuid,
        }
    except ValueError:
        return None


def probe_memory() -> dict[str, Any] | None:
    try:
        import psutil

        virtual = psutil.virtual_memory()
        result: dict[str, Any] = {
            "available_gb": virtual.available / 1e9,
            "total_gb": virtual.total / 1e9,
        }
        swap = psutil.swap_memory()
        # On Windows psutil's swap figures are the page file, so used+physical is the commit charge.
        result["commit_used_gb"] = (virtual.total - virtual.available + swap.used) / 1e9
        result["commit_limit_gb"] = (virtual.total + swap.total) / 1e9
        return result
    except Exception:  # noqa: BLE001
        return None


def probe_disk_free_gb(path: Path) -> float | None:
    try:
        probe = Path(path)
        while not probe.exists() and probe != probe.parent:
            probe = probe.parent
        return shutil.disk_usage(probe).free / 1e9
    except OSError:
        return None


def _get_json(url: str, timeout: float) -> Any:
    with urllib.request.urlopen(url, timeout=timeout) as response:  # noqa: S310 - configured loopback endpoint
        return json.loads(response.read().decode("utf-8"))


def probe_endpoint(base_url: str, kind: str, *, timeout: float = 2.0) -> dict[str, Any]:
    """GET-only: ``state`` is ``free`` (nothing answers), ``healthy`` (the expected API answers) or ``occupied``."""

    base = base_url.rstrip("/")
    try:
        if kind == "comfy":
            stats = _get_json(f"{base}/system_stats", timeout)
            queue = _get_json(f"{base}/queue", timeout)
            busy = len(queue.get("queue_running") or []) + len(queue.get("queue_pending") or [])
            return {
                "state": "healthy",
                "busy_jobs": busy,
                "version": (stats.get("system") or {}).get("comfyui_version"),
            }
        progress = _get_json(f"{base}/sdapi/v1/progress?skip_current_image=true", timeout)
        return {
            "state": "healthy",
            "busy_jobs": int((progress.get("state") or {}).get("job_count") or 0),
        }
    except urllib.error.HTTPError:
        return {"state": "occupied", "busy_jobs": 0}
    except (urllib.error.URLError, OSError, ValueError):
        return {"state": "free", "busy_jobs": 0}


def probe_processes() -> list[dict[str, Any]]:
    try:
        import psutil
    except ImportError:
        return []
    found: list[dict[str, Any]] = []
    for process in psutil.process_iter(["pid", "name", "cmdline"]):
        try:
            cmd = " ".join(process.info.get("cmdline") or [])
            lowered = cmd.lower()
            if (
                any(hint in lowered for hint in RUNTIME_PROCESS_HINTS)
                and "python" in (process.info.get("name") or "").lower()
            ):
                if "operator_journey" in lowered:
                    continue
                found.append(
                    {"pid": process.info["pid"], "name": process.info["name"], "cmdline": cmd[:300]}
                )
        except Exception:  # noqa: BLE001 - a vanished process is not a finding
            continue
    return found


def probe_display() -> dict[str, Any]:
    """Resolution and scaling as the process sees them (empty off Windows)."""

    if sys.platform != "win32":
        return {}
    import ctypes

    user32 = ctypes.windll.user32
    info: dict[str, Any] = {
        "width": user32.GetSystemMetrics(0),
        "height": user32.GetSystemMetrics(1),
    }
    try:
        info["dpi"] = int(user32.GetDpiForSystem())
        info["scaling_percent"] = round(info["dpi"] / 96 * 100)
    except (AttributeError, OSError):
        pass
    return info


@dataclass
class HostProbes:
    repo_sha: Callable[[], str] = repo_sha
    gpu: Callable[[], dict[str, Any] | None] = probe_gpu
    memory: Callable[[], dict[str, Any] | None] = probe_memory
    disk_free_gb: Callable[[Path], float | None] = probe_disk_free_gb
    endpoint: Callable[[str, str], dict[str, Any]] = probe_endpoint
    processes: Callable[[], list[dict[str, Any]]] = probe_processes
    file_sha256: Callable[[Path], str] = sha256_file
    env: dict[str, str] = field(default_factory=lambda: dict(os.environ))
    python: Callable[[], str] = lambda: platform.python_version()
    hostname: Callable[[], str] = platform.node
    os_name: Callable[[], str] = (
        lambda: f"{platform.system()} {platform.release()} {platform.version()}"
    )

    def working_tree_dirty(self) -> list[str]:
        try:
            out = subprocess.check_output(
                ["git", "status", "--porcelain", "--untracked-files=no"],
                cwd=REPO_ROOT,
                text=True,
                timeout=30,
            )
        except (OSError, subprocess.SubprocessError):
            return ["git status unavailable"]
        return [line[3:] for line in out.splitlines() if line.strip()]
