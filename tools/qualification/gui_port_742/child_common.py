"""Helpers used only inside the GUI-PORT-742 child processes (never imported by ordinary CI beyond pure parts)."""

from __future__ import annotations

import argparse
import ctypes
import importlib.abc
import sys
from typing import Any

FORBIDDEN_FOR_TK = ("PySide6", "shiboken6")


class ForbidModules(importlib.abc.MetaPathFinder):
    """Refuses an import outright (not a post-hoc grep); the child fails if anything tries."""

    def __init__(self, prefixes: tuple[str, ...]) -> None:
        self.prefixes = prefixes

    def find_spec(self, fullname, path=None, target=None):
        if any(fullname == p or fullname.startswith(p + ".") for p in self.prefixes):
            raise ImportError(f"GUI-PORT-742 forbids importing {fullname} in this process")
        return None


def forbid(prefixes: tuple[str, ...]) -> None:
    assert not any(m == p or m.startswith(p + ".") for m in sys.modules for p in prefixes)
    sys.meta_path.insert(0, ForbidModules(prefixes))


def parse_viewport(text: str) -> tuple[int | None, int | None]:
    if text == "max":
        return None, None
    width, height = text.lower().split("x")
    return int(width), int(height)


def build_parser(description: str) -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=description)
    parser.add_argument("--mode", choices=("matrix", "benchmark", "a11y"), required=True)
    parser.add_argument("--viewport", default="1366x768")
    parser.add_argument("--rows", type=int, default=500)
    parser.add_argument("--sim-scale", type=float, default=1.0)
    parser.add_argument("--requested-dpi", default="actual-100")
    parser.add_argument("--screenshot")
    parser.add_argument("--hold-file")
    parser.add_argument("--dispatcher", choices=("native", "matched"), default="native")
    return parser


def validate_args(parser: argparse.ArgumentParser, args: argparse.Namespace) -> None:
    if not 64 <= args.rows <= 2000:
        parser.error("bounded proof inputs required")
    if not 1.0 <= args.sim_scale <= 3.0:
        parser.error("simulated scale must be between 1.0 and 3.0")
    if args.mode == "a11y" and not args.hold_file:
        parser.error("--hold-file is required for a11y mode")


# ----- Windows DPI / activation / capture ---------------------------------------------------------------------------
def _user32():
    return ctypes.windll.user32 if sys.platform == "win32" else None


def dpi_record(
    hwnd: int, *, simulated_factor: float | None, requested: str, toolkit_scale: float
) -> dict[str, Any]:
    user32 = _user32()
    if user32 is None:
        return {"requested": requested, "awareness": "unsupported_platform"}
    user32.GetThreadDpiAwarenessContext.restype = ctypes.c_void_p
    user32.AreDpiAwarenessContextsEqual.argtypes = [ctypes.c_void_p, ctypes.c_void_p]
    context = user32.GetThreadDpiAwarenessContext()
    per_monitor_v2 = bool(user32.AreDpiAwarenessContextsEqual(context, ctypes.c_void_p(-4)))
    user32.GetDpiForWindow.argtypes = [ctypes.c_void_p]
    user32.GetDpiForWindow.restype = ctypes.c_uint
    window_dpi = int(user32.GetDpiForWindow(ctypes.c_void_p(hwnd)))
    user32.MonitorFromWindow.argtypes = [ctypes.c_void_p, ctypes.c_uint]
    user32.MonitorFromWindow.restype = ctypes.c_void_p
    monitor = user32.MonitorFromWindow(ctypes.c_void_p(hwnd), 2)
    dpi_x, dpi_y = ctypes.c_uint(), ctypes.c_uint()
    ctypes.windll.shcore.GetDpiForMonitor.argtypes = [
        ctypes.c_void_p,
        ctypes.c_int,
        ctypes.POINTER(ctypes.c_uint),
        ctypes.POINTER(ctypes.c_uint),
    ]
    ctypes.windll.shcore.GetDpiForMonitor(monitor, 0, ctypes.byref(dpi_x), ctypes.byref(dpi_y))
    return {
        "requested": requested,
        "awareness": "per_monitor_v2" if per_monitor_v2 else "other",
        "window_dpi": window_dpi,
        "monitor_dpi": int(dpi_x.value),
        "toolkit_scale": toolkit_scale,
        "simulated_factor": simulated_factor,
    }


def work_area() -> list[int]:
    user32 = _user32()
    if user32 is None:
        return []

    class Rect(ctypes.Structure):
        _fields_ = [
            ("l", ctypes.c_long),
            ("t", ctypes.c_long),
            ("r", ctypes.c_long),
            ("b", ctypes.c_long),
        ]

    rect = Rect()
    user32.SystemParametersInfoW(
        0x0030, 0, ctypes.byref(rect), 0
    )  # SPI_GETWORKAREA, read-only query
    return [rect.l, rect.t, rect.r, rect.b]


def activate(hwnd: int) -> bool:
    """Ask Windows to foreground our own window (it may decline); returns the resulting state, never forces it."""

    user32 = _user32()
    if user32 is None:
        return False
    user32.GetAncestor.argtypes = [ctypes.c_void_p, ctypes.c_uint]
    user32.GetAncestor.restype = ctypes.c_void_p
    root = user32.GetAncestor(ctypes.c_void_p(hwnd), 2)
    user32.SetForegroundWindow.argtypes = [ctypes.c_void_p]
    user32.SetForegroundWindow(ctypes.c_void_p(root))
    return foreground_matches(hwnd)


def foreground_matches(hwnd: int) -> bool:
    user32 = _user32()
    if user32 is None:
        return False
    user32.GetAncestor.argtypes = [ctypes.c_void_p, ctypes.c_uint]
    user32.GetAncestor.restype = ctypes.c_void_p
    user32.GetForegroundWindow.restype = ctypes.c_void_p
    return user32.GetForegroundWindow() == user32.GetAncestor(ctypes.c_void_p(hwnd), 2)


def screen_capture(box: tuple[int, int, int, int]):
    from PIL import ImageGrab

    return ImageGrab.grab(bbox=box, all_screens=True).convert("RGB")
