from __future__ import annotations

import sys
import threading
from collections.abc import Callable
from typing import Any


class DiagnosticsCoordinator:
    """Own exception hook installation and teardown for the application runtime."""

    def __init__(self) -> None:
        self._original_excepthook = sys.excepthook
        self._original_threading_excepthook = getattr(threading, "excepthook", None)
        self._original_tk_report_callback_exception: Callable[..., Any] | None = None

    def install(
        self,
        *,
        main_window: Any,
        on_uncaught_exception: Callable[..., Any],
        on_thread_exception: Callable[..., Any],
        on_tk_exception: Callable[..., Any],
    ) -> None:
        try:
            sys.excepthook = on_uncaught_exception
        except Exception:
            pass
        if hasattr(threading, "excepthook"):
            self._original_threading_excepthook = threading.excepthook
            threading.excepthook = on_thread_exception
        root = getattr(main_window, "root", None)
        if root and hasattr(root, "report_callback_exception"):
            self._original_tk_report_callback_exception = root.report_callback_exception
            root.report_callback_exception = on_tk_exception

    def uninstall(self, *, main_window: Any) -> None:
        try:
            sys.excepthook = self._original_excepthook
        except Exception:
            pass
        if hasattr(threading, "excepthook") and self._original_threading_excepthook is not None:
            try:
                threading.excepthook = self._original_threading_excepthook
            except Exception:
                pass
        root = getattr(main_window, "root", None)
        if (
            root
            and hasattr(root, "report_callback_exception")
            and self._original_tk_report_callback_exception is not None
        ):
            try:
                root.report_callback_exception = self._original_tk_report_callback_exception
            except Exception:
                pass
