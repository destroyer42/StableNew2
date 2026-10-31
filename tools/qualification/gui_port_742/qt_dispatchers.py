"""Proof-only Qt dispatcher that reproduces the production Tk scheduling policy (H1 control). Qt children only.

``TkInvoker`` polls a queue every 15 ms and runs at most 32 callbacks or 8 ms per pump; ``invoke_later`` uses a
``threading.Timer`` that then queues. This class applies exactly that policy on a ``QTimer`` so the only remaining
differences between the two toolkits are the framework's own event loop, timers and widgets. The native
queued-signal dispatcher stays ``tools.qualification.gui_port_740.qt_dispatcher.QtUiDispatcher``.
"""

from __future__ import annotations

import threading
import time
from collections import deque

from PySide6.QtCore import QCoreApplication, Qt, QThread, QTimer


class TkPolicyQtDispatcher:
    PUMP_INTERVAL_MS = 15
    MAX_CALLBACKS = 32
    MAX_PUMP_MS = 8.0

    def __init__(self, parent) -> None:
        if QThread.currentThread() != parent.thread():
            raise RuntimeError("dispatcher must be constructed on its owner's GUI thread")
        self._thread = threading.get_ident()
        self._lock = threading.Lock()
        self._pending: deque = deque()
        self._ids: set[int] = set()
        self._timers: set[threading.Timer] = set()
        self._disposed = False
        self.errors: list[dict[str, str]] = []
        self.delivered = 0
        self.canceled = 0
        self.peak_backlog = 0
        self._timer = QTimer(parent)
        self._timer.setSingleShot(True)
        self._timer.setTimerType(Qt.TimerType.PreciseTimer)
        self._timer.timeout.connect(self._pump)
        self._timer.start(self.PUMP_INTERVAL_MS)
        parent.destroyed.connect(self.dispose)
        QCoreApplication.instance().aboutToQuit.connect(self.dispose)

    @property
    def _closed(self) -> bool:  # same name the native proof dispatcher exposes
        return self._disposed

    def invoke(self, fn) -> None:
        with self._lock:
            if self._disposed:
                return
            key = id(fn)
            if key in self._ids:
                return
            self._pending.append(fn)
            self._ids.add(key)
            self.peak_backlog = max(self.peak_backlog, len(self._pending))

    def schedule(self, fn) -> None:
        self.invoke(fn)

    def run_on_ui_thread(self, fn) -> None:
        if threading.get_ident() == self._thread:
            if self._disposed:
                return
            fn()
            return
        self.invoke(fn)

    def invoke_later(self, delay_ms: int, fn) -> None:
        delay = max(0.0, float(delay_ms) / 1000.0)
        if delay <= 0:
            self.invoke(fn)
            return

        def fire() -> None:
            with self._lock:
                self._timers.discard(timer)
                if self._disposed:
                    return
            self.invoke(fn)

        timer = threading.Timer(delay, fire)
        timer.daemon = True
        with self._lock:
            if self._disposed:
                return
            self._timers.add(timer)
        timer.start()

    def _pump(self) -> None:
        batch = []
        with self._lock:
            if self._disposed:
                return
            while self._pending and len(batch) < self.MAX_CALLBACKS:
                batch.append(self._pending.popleft())
        started = time.monotonic()
        done = 0
        for callback in batch:
            try:
                callback()
                self.delivered += 1
            except Exception as exc:  # noqa: BLE001 - report synthetic callback faults
                self.errors.append({"type": type(exc).__name__, "message": str(exc)})
            finally:
                with self._lock:
                    self._ids.discard(id(callback))
            done += 1
            if (time.monotonic() - started) * 1000.0 >= self.MAX_PUMP_MS:
                break
        leftovers = batch[done:]
        if leftovers:
            with self._lock:
                for callback in reversed(leftovers):
                    self._pending.appendleft(callback)
        if not self._disposed:
            self._timer.start(self.PUMP_INTERVAL_MS)

    def dispose(self, *_args) -> None:
        with self._lock:
            if self._disposed:
                return
            self._disposed = True
            self.canceled += len(self._pending)
            self._pending.clear()
            self._ids.clear()
            timers = list(self._timers)
            self._timers.clear()
        for timer in timers:
            timer.cancel()
        self._timer.stop()
