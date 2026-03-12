from __future__ import annotations

import logging
import threading
import tkinter as tk
from collections.abc import Callable
from collections import deque

logger = logging.getLogger(__name__)

class GuiInvoker:
    """Thread-safe invoker that schedules work on the Tk main loop."""

    def __init__(self, root: tk.Misc) -> None:
        self._root = root
        self._disposed = False
        self._lock = threading.Lock()
        self._pending: deque[Callable[[], None]] = deque()
        self._pump_interval_ms = 15
        self._pump_scheduled = False
        self._schedule_pump()

    def invoke(self, fn: Callable[[], None]) -> None:
        """Queue a callable to run on the Tk main loop pump."""
        with self._lock:
            if self._disposed:
                return
            self._pending.append(fn)

    def _schedule_pump(self) -> None:
        with self._lock:
            if self._disposed or self._pump_scheduled:
                return
            self._pump_scheduled = True
        try:
            self._root.after(self._pump_interval_ms, self._pump)
        except tk.TclError:
            with self._lock:
                self._disposed = True
                self._pump_scheduled = False

    def _pump(self) -> None:
        callbacks: list[Callable[[], None]] = []
        with self._lock:
            if self._disposed:
                self._pump_scheduled = False
                return
            callbacks = list(self._pending)
            self._pending.clear()
            self._pump_scheduled = False

        for callback in callbacks:
            try:
                callback()
            except Exception:
                logger.exception("GuiInvoker callback failed")

        self._schedule_pump()

    def dispose(self) -> None:
        """Prevent any further scheduling."""
        with self._lock:
            self._disposed = True
            self._pending.clear()
