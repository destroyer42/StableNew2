"""Shared Tk utilities for GUI tests.

On Windows, Tk can only be initialized once per process. This module provides
a single shared Tk root that all GUI test modules can use.
"""

import tkinter as tk

# Single process-wide Tk root
_tk_root: tk.Tk | None = None


def get_shared_tk_root() -> tk.Tk | None:
    """Get or create the shared Tk root for all GUI tests.
    
    Returns:
        The shared Tk root, or None if Tk is unavailable.
    """
    global _tk_root
    
    if _tk_root is None:
        try:
            _tk_root = tk.Tk()
            _tk_root.withdraw()
        except Exception:
            _tk_root = None
    
    return _tk_root
