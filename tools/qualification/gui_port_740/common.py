"""Shared deterministic inputs and evidence helpers; importing this starts nothing."""

from __future__ import annotations

import ctypes
import hashlib
import importlib.abc
import json
import os
import platform
import statistics
import sys
import time
import traceback
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]


class ForbidTk(importlib.abc.MetaPathFinder):
    def find_spec(self, fullname, path=None, target=None):
        if fullname == "tkinter" or fullname.startswith("tkinter."):
            raise ImportError("GUI-PORT-740 forbids tkinter in this process")
        return None


def forbid_tk():
    assert not any(name == "tkinter" or name.startswith("tkinter.") for name in sys.modules)
    sys.meta_path.insert(0, ForbidTk())


def rows(count: int, revision: int = 0) -> tuple[tuple[str, str, str], ...]:
    offset = min(10, count // 4) if revision else 0
    return tuple(
        (
            f"synthetic-{i:05d}",
            ("queued", "running", "completed")[(i + revision) % 3],
            f"Synthetic projection {i}",
        )
        for i in range(offset, count + offset)
    )


def summary(values):
    ordered = sorted(values)
    return {
        "n": len(values),
        "min": min(values),
        "median": statistics.median(values),
        "p95": ordered[min(len(ordered) - 1, int(len(ordered) * 0.95))],
        "max": max(values),
    }


def source_identity():
    folder = Path(__file__).parent
    return {
        path.name: hashlib.sha256(path.read_bytes()).hexdigest()
        for path in sorted(folder.iterdir())
        if path.is_file() and path.suffix == ".py"
    }


def process_dpi_setup():
    if sys.platform == "win32":
        ctypes.windll.user32.SetProcessDpiAwarenessContext(ctypes.c_void_p(-4))


def window_dpi(hwnd):
    if sys.platform != "win32":
        return None
    api = ctypes.windll.user32.GetDpiForWindow
    api.argtypes = [ctypes.c_void_p]
    api.restype = ctypes.c_uint
    return api(int(hwnd))


def memory():
    import psutil

    info = psutil.Process().memory_info()
    return {
        "working_set": info.rss,
        "peak_working_set": getattr(info, "peak_wset", info.rss),
        "native_threads": psutil.Process().num_threads(),
    }


def import_probe(module: str):
    import importlib

    try:
        imported = importlib.import_module(module)
        return {"status": "PASS", "module": imported.__name__}
    except ImportError:
        return {"status": "BLOCKED", "traceback": traceback.format_exc()}


def emit(event, **values):
    print(json.dumps({"event": event, "clock_ns": time.perf_counter_ns(), **values}), flush=True)


def runtime():
    import sysconfig

    return {
        "pid": os.getpid(),
        "python": sys.version,
        "executable": sys.executable,
        "prefix": sys.prefix,
        "base_prefix": sys.base_prefix,
        "platform": platform.platform(),
        "machine": platform.machine(),
        "gil_enabled": sys._is_gil_enabled(),
        "gil_disabled_build": sysconfig.get_config_var("Py_GIL_DISABLED"),
    }


def visible_render_evidence(first, result):
    """Fail closed on a timestamp that precedes mapping or warm rendering."""
    return bool(
        first
        and first.get("visible") is True
        and result
        and result.get("warm_visible_rendered") is True
        and (result.get("toolkit") != "qt" or first.get("exposed") is True)
    )


def isolation_guard():
    """No Python network, subprocess or database operation is needed by either child."""

    def audit(event, _args):
        if event in {
            "socket.connect",
            "socket.bind",
            "socket.getaddrinfo",
            "subprocess.Popen",
            "os.system",
            "sqlite3.connect",
        }:
            raise RuntimeError("Operation forbidden in synthetic GUI child: " + event)

    sys.addaudithook(audit)
