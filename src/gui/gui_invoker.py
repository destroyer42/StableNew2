from __future__ import annotations

import threading
import tkinter as tk
from collections.abc import Callable


class GuiInvoker:
    """Thread-safe invoker that schedules work on the Tk main loop."""

    def __init__(self, root: tk.Misc) -> None:
        self._root = root
        self._disposed = False
        self._lock = threading.Lock()

    def invoke(self, fn: Callable[[], None]) -> None:
        """Schedule a callable to run on the Tk main loop."""
        with self._lock:
            if self._disposed:
                return
            try:
                self._root.after(0, fn)
            except tk.TclError:
                # Root is likely destroyed; ignore late scheduling.
                pass

    def dispose(self) -> None:
        """Prevent any further scheduling."""
        with self._lock:
            self._disposed = True
