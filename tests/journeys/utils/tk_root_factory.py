"""Shared Tkinter root factory for journey tests.

This centralizes the slightly-finicky Windows/Tcl initialization logic
so we can skip journey tests cleanly when Tk cannot be brought up,
rather than hard-failing the entire test run.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

import pytest


def _is_valid_tcl_dir(path: str | os.PathLike[str] | None) -> bool:
    if not path:
        return False
    return Path(path).joinpath("init.tcl").is_file()


def _is_valid_tk_dir(path: str | os.PathLike[str] | None) -> bool:
    if not path:
        return False
    return Path(path).joinpath("tk.tcl").is_file()


def _configure_windows_tk_environment(tk_module) -> None:
    current_tcl = os.environ.get("TCL_LIBRARY")
    current_tk = os.environ.get("TK_LIBRARY")
    if _is_valid_tcl_dir(current_tcl) and _is_valid_tk_dir(current_tk):
        return

    module_path = Path(tk_module.__file__).resolve()
    candidate_roots = [
        module_path.parents[2],
        Path(sys.executable).resolve().parent,
        Path(sys.base_prefix),
        Path(sys.exec_prefix),
    ]
    seen: set[tuple[str, str]] = set()
    for root in candidate_roots:
        tcl_dir = root / "tcl" / "tcl8.6"
        tk_dir = root / "tcl" / "tk8.6"
        key = (str(tcl_dir), str(tk_dir))
        if key in seen:
            continue
        seen.add(key)
        if _is_valid_tcl_dir(tcl_dir) and _is_valid_tk_dir(tk_dir):
            os.environ["TCL_LIBRARY"] = str(tcl_dir)
            os.environ["TK_LIBRARY"] = str(tk_dir)
            return


def create_root():
    """Create a Tk root window suitable for headless journey tests.

    On Windows, this function will attempt to infer and set the
    TCL_LIBRARY / TK_LIBRARY environment variables based on the
    installed tkinter package. If Tk still cannot be initialized, the
    calling test is skipped instead of failing.
    """
    try:
        import tkinter as tk  # Local import to avoid hard dependency at import time
    except Exception as exc:  # pragma: no cover - environment-specific
        pytest.skip(f"Tkinter import failed for journey test: {exc}")

    if sys.platform.startswith("win"):
        _configure_windows_tk_environment(tk)

    try:
        root = tk.Tk()  # noqa: F841 - referenced by tk variable after import
        root.withdraw()
        return root
    except Exception as exc:  # pragma: no cover - environment-specific
        pytest.skip(f"Tkinter unavailable for journey test: {exc}")
