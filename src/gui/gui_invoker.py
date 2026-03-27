from __future__ import annotations

import logging
import threading
import time
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
        self._pending_ids: set[int] = set()
        self._pump_interval_ms = 15
        self._max_callbacks_per_pump = 32
        self._max_pump_duration_ms = 8.0
        self._pump_scheduled = False
        self._schedule_pump()

    def invoke(self, fn: Callable[[], None]) -> None:
        """Queue a callable to run on the Tk main loop pump."""
        with self._lock:
            if self._disposed:
                return
            key = id(fn)
            if key in self._pending_ids:
                return
            self._pending.append(fn)
            self._pending_ids.add(key)

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
            while self._pending and len(callbacks) < self._max_callbacks_per_pump:
                callbacks.append(self._pending.popleft())
            self._pump_scheduled = False

        started = time.monotonic()
        executed_count = 0
        for callback in callbacks:
            try:
                callback()
            except Exception:
                logger.exception("GuiInvoker callback failed")
            finally:
                with self._lock:
                    self._pending_ids.discard(id(callback))
            executed_count += 1
            elapsed_ms = (time.monotonic() - started) * 1000.0
            if elapsed_ms >= self._max_pump_duration_ms:
                break

        leftovers = callbacks[executed_count:]
        if leftovers:
            with self._lock:
                for pending_cb in reversed(leftovers):
                    self._pending.appendleft(pending_cb)

        self._schedule_pump()

    def dispose(self) -> None:
        """Prevent any further scheduling."""
        with self._lock:
            self._disposed = True
            self._pending.clear()
            self._pending_ids.clear()
