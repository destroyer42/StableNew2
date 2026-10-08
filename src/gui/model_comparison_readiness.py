"""Single-flight worker mailbox; all Tk calls remain in the polling owner."""

from __future__ import annotations

import queue
import threading
import time
from collections.abc import Callable
from typing import Any


class ComparisonEvidenceTask:
    def __init__(self, work: Callable[..., Any], *, timeout: float = 1200) -> None:
        self._cancel = threading.Event()
        self._deadline = time.monotonic() + timeout
        self.messages: queue.Queue[tuple[str, Any]] = queue.Queue()
        self._last_progress = 0.0
        self.thread = threading.Thread(
            target=self._run, args=(work,), name="learning-checkpoint-evidence", daemon=True
        )
        self.thread.start()

    def cancelled(self) -> bool:
        return self._cancel.is_set() or time.monotonic() >= self._deadline

    def cancel(self) -> None:
        self._cancel.set()

    def _progress(self, message: str) -> None:
        now = time.monotonic()
        if now - self._last_progress > 0.1:
            self.messages.put(("progress", message))
            self._last_progress = now

    def _run(self, work: Callable[..., Any]) -> None:
        try:
            result = work(cancelled=self.cancelled, progress=self._progress)
            if self.cancelled():
                raise InterruptedError(
                    "Checkpoint evidence refresh cancelled or timed out; retry Preview"
                )
            self.messages.put(("ready", result))
        except Exception as exc:
            self.messages.put(("error", str(exc)))
