"""Fault capture for an operator journey (Tk, thread and log errors)."""

from __future__ import annotations

import logging
import sys
import threading
import traceback
from collections.abc import Callable
from types import TracebackType
from typing import Any

_SHUTDOWN_NOISE = ("invalid command name", "application has been destroyed")


class _ListHandler(logging.Handler):
    def __init__(self, sink: list[dict[str, Any]]) -> None:
        super().__init__(level=logging.INFO)
        self.sink = sink

    def emit(self, record: logging.LogRecord) -> None:
        try:
            self.sink.append(
                {
                    "level": record.levelname,
                    "logger": record.name,
                    "message": record.getMessage()[:2000],
                    "thread": record.threadName,
                }
            )
        except Exception:
            pass


class FaultCapture:
    """Collect Tk callback, background-thread and log errors; restore hooks on exit."""

    def __init__(self, root: Any | None = None) -> None:
        self.root = root
        self.tk_errors: list[str] = []
        self.thread_errors: list[str] = []
        self.main_errors: list[str] = []
        self.shutdown_noise: list[str] = []
        self._closing = False
        self.logs: list[dict[str, Any]] = []
        self._handler = _ListHandler(self.logs)
        self._saved: dict[str, Any] = {}

    def __enter__(self) -> FaultCapture:
        self._saved["excepthook"] = sys.excepthook
        self._saved["threading_hook"] = threading.excepthook
        sys.excepthook = self._on_main_error
        threading.excepthook = self._on_thread_error
        if self.root is not None:
            self._saved["tk_hook"] = self.root.report_callback_exception
            self.root.report_callback_exception = self._on_tk_error
            try:  # Tcl-level background errors (e.g. after-callbacks on dead widgets)
                self.root.tk.createcommand("bgerror", self._on_bgerror)
            except Exception:
                pass
        logging.getLogger().addHandler(self._handler)
        return self

    def __exit__(self, *_: object) -> None:
        logging.getLogger().removeHandler(self._handler)
        sys.excepthook = self._saved["excepthook"]
        threading.excepthook = self._saved["threading_hook"]
        if self.root is not None and "tk_hook" in self._saved:
            try:
                self.root.report_callback_exception = self._saved["tk_hook"]
                self.root.tk.deletecommand("bgerror")
            except Exception:
                pass  # root already destroyed by a graceful shutdown

    def begin_shutdown(self) -> None:
        """Mark the operator's close action; destroyed-widget noise after it is separate."""

        self._closing = True

    def _record_tk(self, text: str) -> None:
        if self._closing and any(marker in text for marker in _SHUTDOWN_NOISE):
            self.shutdown_noise.append(text[:600])
        else:
            self.tk_errors.append(text)

    def _on_tk_error(
        self, exc: type[BaseException], value: BaseException, tb: TracebackType | None
    ) -> None:
        self._record_tk("".join(traceback.format_exception(exc, value, tb))[-3000:])

    def _on_bgerror(self, message: str) -> None:
        self._record_tk(f"tcl-bgerror: {message}"[:3000])

    def _on_thread_error(self, args: threading.ExceptHookArgs) -> None:
        name = args.thread.name if args.thread else "?"
        text = "".join(
            traceback.format_exception(args.exc_type, args.exc_value, args.exc_traceback)
        )
        self.thread_errors.append(f"[{name}] {text[-3000:]}")

    def _on_main_error(
        self, exc: type[BaseException], value: BaseException, tb: TracebackType | None
    ) -> None:
        self.main_errors.append("".join(traceback.format_exception(exc, value, tb))[-3000:])

    def error_logs(self) -> list[dict[str, Any]]:
        return [entry for entry in self.logs if entry["level"] in {"ERROR", "CRITICAL"}]

    def all_errors(self) -> list[str]:
        return [*self.tk_errors, *self.thread_errors, *self.main_errors]


def thread_snapshot(label: str) -> dict[str, Any]:
    """Live threads at a checkpoint, plus StableNew's ThreadRegistry view."""

    registry: list[str] = []
    try:
        from src.utils.thread_registry import get_thread_registry

        registry = [t.name for t in get_thread_registry().get_active_threads()]
    except Exception as exc:  # pragma: no cover - defensive
        registry = [f"registry-unavailable: {exc}"]
    return {
        "checkpoint": label,
        "threads": sorted((t.name, bool(t.daemon)) for t in threading.enumerate() if t.is_alive()),
        "registry": sorted(registry),
    }


def leaked_non_daemon_threads(
    baseline_names: set[str], *, ignore: Callable[[str], bool] = lambda _n: False
) -> list[str]:
    """Non-daemon threads alive now that were not part of the pre-journey baseline."""

    return sorted(
        t.name
        for t in threading.enumerate()
        if t.is_alive()
        and not t.daemon
        and t is not threading.main_thread()
        and t.name not in baseline_names
        and not ignore(t.name)
    )
