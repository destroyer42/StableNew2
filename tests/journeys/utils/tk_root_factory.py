"""Shared Tkinter root factory for journey tests.

This centralizes the slightly-finicky Windows/Tcl initialization logic
so we can skip journey tests cleanly when Tk cannot be brought up,
rather than hard-failing the entire test run.
"""

from __future__ import annotations

import os
import sys

import pytest


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
        tcl_library = os.environ.get("TCL_LIBRARY")
        tk_library = os.environ.get("TK_LIBRARY")
        if not tcl_library or not tk_library:
            base_dir = os.path.dirname(os.path.abspath(tk.__file__))
            candidate_tcl = os.path.join(base_dir, "tcl", "tcl8.6")
            candidate_tk = os.path.join(base_dir, "tcl", "tk8.6")
            if os.path.isdir(candidate_tcl):
                os.environ.setdefault("TCL_LIBRARY", candidate_tcl)
            if os.path.isdir(candidate_tk):
                os.environ.setdefault("TK_LIBRARY", candidate_tk)

    try:
        root = tk.Tk()  # noqa: F841 - referenced by tk variable after import
        root.withdraw()
        return root
    except Exception as exc:  # pragma: no cover - environment-specific
        pytest.skip(f"Tkinter unavailable for journey test: {exc}")
