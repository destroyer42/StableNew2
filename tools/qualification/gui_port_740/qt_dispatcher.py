"""Proof-only bounded Qt scheduler. Only an explicit Qt child imports this module."""

from __future__ import annotations

import threading
import time
from collections import deque

from PySide6.QtCore import QCoreApplication, QObject, Qt, QThread, QTimer, Signal, Slot


class _Bridge(QObject):
    wake = Signal()

    def __init__(self, parent, owner):
        super().__init__(parent)
        self.owner = owner
        self.wake.connect(self.drain, Qt.ConnectionType.QueuedConnection)

    @Slot()
    def drain(self):
        self.owner._drain()


class QtUiDispatcher:
    """GUI-owned bridge; worker callers touch Python state and emit a queued signal only.

    Accepted work is delivered once or canceled by dispose/owner destruction/app exit.
    Queue capacity 4096; delayed reservations 128; saturation raises at submission.
    Each activation yields after 64 requests or 5 ms, allowing other Qt events.
    Callback failures are reported in errors and never stop later delivery.
    """

    def __init__(self, parent, *, capacity=4096, timer_capacity=128):
        if QThread.currentThread() != parent.thread():
            raise RuntimeError("dispatcher must be constructed on its owner's GUI thread")
        self._thread = threading.get_ident()
        self._lock = threading.RLock()
        self._pending = deque()
        self._timers = {}
        self._next = 0
        self._delayed = 0
        self._closed = False
        self._capacity = capacity
        self._timer_capacity = timer_capacity
        self.peak_backlog = 0
        self.errors = []
        self.delivered = 0
        self.canceled = 0
        self._bridge = _Bridge(parent, self)
        self._bridge.destroyed.connect(self._bridge_destroyed)
        parent.destroyed.connect(self.dispose)
        QCoreApplication.instance().aboutToQuit.connect(self.dispose)

    def _bridge_destroyed(self, *_args):
        with self._lock:
            self._closed = True
            self.canceled += len(self._pending) + len(self._timers)
            self._pending.clear()
            self._timers.clear()
            self._delayed = 0

    def _signal(self):
        try:
            self._bridge.wake.emit()
        except RuntimeError:
            # The GUI may destroy the owner between a worker's admission and emit.
            self.dispose()

    def _enqueue(self, fn, delay=None):
        if not callable(fn):
            raise TypeError("callback must be callable")
        with self._lock:
            if self._closed:
                return
            if len(self._pending) >= self._capacity:
                raise RuntimeError("proof dispatcher queue capacity exceeded")
            if delay is not None:
                if self._delayed >= self._timer_capacity:
                    raise RuntimeError("proof dispatcher timer capacity exceeded")
                self._delayed += 1
            self._pending.append(
                (fn, None if delay is None else time.perf_counter() + max(0, delay) / 1000)
            )
            self.peak_backlog = max(self.peak_backlog, len(self._pending))
        self._signal()

    def schedule(self, fn):
        self._enqueue(fn)

    def invoke_later(self, delay_ms, fn):
        self._enqueue(fn, int(delay_ms))

    def run_on_ui_thread(self, fn):
        with self._lock:
            if self._closed:
                return
        if threading.get_ident() == self._thread:
            self._call(fn)
        else:
            self.schedule(fn)

    def _call(self, fn):
        assert threading.get_ident() == self._thread
        with self._lock:
            if self._closed:
                self.canceled += 1
                return
            # Linearize disposal with callback start. Worker disposal waits for an
            # already-running callback; none can begin after dispose returns.
            try:
                fn()
                self.delivered += 1
            except Exception as exc:  # noqa: BLE001 - report synthetic callback faults
                self.errors.append({"type": type(exc).__name__, "message": str(exc)})

    def _drain(self):
        with self._lock:
            self._drain_locked()

    def _drain_locked(self):
        assert threading.get_ident() == self._thread
        with self._lock:
            if self._closed:
                for timer in self._timers.values():
                    timer.stop()
                    timer.deleteLater()
                self._timers.clear()
                return
        deadline = time.perf_counter() + 0.005
        for _ in range(64):
            with self._lock:
                if not self._pending or self._closed:
                    break
                fn, due = self._pending.popleft()
            if due is None:
                self._call(fn)
            else:
                self._next += 1
                token = self._next
                timer = QTimer(self._bridge)
                timer.setSingleShot(True)
                timer.setTimerType(Qt.TimerType.PreciseTimer)
                self._timers[token] = timer

                def fire(token=token, fn=fn):
                    with self._lock:
                        timer = self._timers.pop(token, None)
                        if timer is None:
                            return
                        if not self._closed:
                            self._delayed -= 1
                            self._call(fn)
                        timer.deleteLater()

                timer.timeout.connect(fire)
                timer.start(max(0, round((due - time.perf_counter()) * 1000)))
            if time.perf_counter() >= deadline:
                break
        with self._lock:
            pending = bool(self._pending) and not self._closed
        if pending:
            self._signal()

    def dispose(self, *_args):
        with self._lock:
            if self._closed:
                return
            self._closed = True
            self.canceled += len(self._pending) + len(self._timers)
            self._pending.clear()
            self._delayed = 0
        if threading.get_ident() == self._thread:
            self._drain()
        else:
            self._signal()
