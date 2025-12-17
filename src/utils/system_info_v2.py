from __future__ import annotations

import getpass
import os
import platform
import shutil
import socket
import sys
from datetime import datetime
from pathlib import Path
from typing import Any

try:
    import psutil  # type: ignore[import]
except ImportError:  # pragma: no cover - optional dependency
    psutil = None  # type: ignore[assignment]


def collect_system_snapshot() -> dict[str, Any]:
    """Gather lightweight system information for diagnostic bundles."""

    memory = None
    cpu = None
    if psutil:
        try:
            virt = psutil.virtual_memory()
            memory = {
                "total_mb": float(virt.total) / (1024**2),
                "available_mb": float(virt.available) / (1024**2),
                "used_mb": float(virt.used) / (1024**2),
                "percent": getattr(virt, "percent", 0.0),
            }
        except Exception:
            memory = None
        try:
            cpu = {
                "percent": psutil.cpu_percent(interval=None),
                "count_logical": psutil.cpu_count(),
                "count_physical": psutil.cpu_count(logical=False),
            }
        except Exception:
            cpu = None
    disk = None
    try:
        disk_usage = (
            shutil.disk_usage("/") if os.name == "posix" else shutil.disk_usage(os.getcwd())
        )
        disk = {
            "total_mb": float(disk_usage.total) / (1024**2),
            "used_mb": float(disk_usage.used) / (1024**2),
            "free_mb": float(disk_usage.free) / (1024**2),
        }
    except Exception:
        disk = None

    return {
        "timestamp": datetime.utcnow().isoformat() + "Z",
        "hostname": socket.gethostname(),
        "platform": {
            "system": platform.system(),
            "release": platform.release(),
            "version": platform.version(),
            "machine": platform.machine(),
            "processor": platform.processor(),
        },
        "python": {
            "implementation": platform.python_implementation(),
            "version": platform.python_version(),
            "executable": sys.executable,
        },
        "user": getpass.getuser(),
        "cwd": os.getcwd(),
        "repo_root": str(Path(__file__).resolve().parents[2]),
        "memory": memory,
        "cpu": cpu,
        "disk": disk,
    }
