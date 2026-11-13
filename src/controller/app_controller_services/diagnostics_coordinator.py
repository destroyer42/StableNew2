from __future__ import annotations

import sys
import threading
from collections.abc import Callable
from typing import Any


class DiagnosticsCoordinator:
    """Sole owner of the process-global exception hooks and their original values.

    The coordinator captures ``sys.excepthook`` at construction, and the
    ``threading.excepthook`` and Tk ``report_callback_exception`` values at
    install time.  It installs the host's handlers, forwards to the captured
    originals on request (``forward_*``) and restores them on ``uninstall``.
    Nothing else keeps a copy of an original hook.

    ``install`` is idempotent while installed (a second call can never capture
    our own handler as the "original") and rolls back whatever it replaced if it
    fails part-way.
    """

    def __init__(self) -> None:
        self._original_excepthook: Callable[..., Any] | None = sys.excepthook
        self._original_threading_excepthook = getattr(threading, "excepthook", None)
        self._original_tk_report_callback_exception: Callable[..., Any] | None = None
        self._installed = False

    @property
    def installed(self) -> bool:
        return self._installed

    def install(
        self,
        *,
        main_window: Any,
        on_uncaught_exception: Callable[..., Any],
        on_thread_exception: Callable[..., Any],
        on_tk_exception: Callable[..., Any],
    ) -> None:
        if self._installed:
            return
        try:
            try:
                sys.excepthook = on_uncaught_exception
            except Exception:  # noqa: BLE001, S110 - installing a new hook must not raise even if the target cannot be replaced
                pass
            if hasattr(threading, "excepthook"):
                self._original_threading_excepthook = threading.excepthook
                threading.excepthook = on_thread_exception
            root = getattr(main_window, "root", None)
            if root and hasattr(root, "report_callback_exception"):
                self._original_tk_report_callback_exception = root.report_callback_exception
                root.report_callback_exception = on_tk_exception
        except BaseException:
            self._restore(main_window)
            raise
        self._installed = True

    def uninstall(self, *, main_window: Any) -> None:
        if not self._installed:
            return
        self._restore(main_window)
        self._installed = False

    def forward_uncaught_exception(
        self, exc_type: type[BaseException], exc_value: BaseException, exc_traceback: Any
    ) -> None:
        """Forward a system-level exception to the original ``sys.excepthook``."""
        if self._original_excepthook is not None:
            self._original_excepthook(exc_type, exc_value, exc_traceback)

    def forward_thread_exception(self, args: threading.ExceptHookArgs) -> None:
        """Forward a thread exception to the original ``threading.excepthook``."""
        if self._original_threading_excepthook:
            self._original_threading_excepthook(args)

    def forward_tk_exception(
        self, exc_type: type[BaseException], exc_value: BaseException, exc_traceback: Any
    ) -> None:
        """Forward a Tk callback exception to the original handler; never raises."""
        if callable(self._original_tk_report_callback_exception):
            try:
                self._original_tk_report_callback_exception(exc_type, exc_value, exc_traceback)
            except Exception:  # noqa: BLE001, S110 - forwarding to the original Tk hook must never raise during exception handling
                pass

    def _restore(self, main_window: Any) -> None:
        if self._original_excepthook is not None:
            try:
                sys.excepthook = self._original_excepthook
            except Exception:  # noqa: BLE001, S110 - restoring the original sys hook must not raise during teardown
                pass
        if hasattr(threading, "excepthook") and self._original_threading_excepthook is not None:
            try:
                threading.excepthook = self._original_threading_excepthook
            except Exception:  # noqa: BLE001, S110 - restoring the original threading hook must not raise during teardown
                pass
        root = getattr(main_window, "root", None)
        if (
            root
            and hasattr(root, "report_callback_exception")
            and self._original_tk_report_callback_exception is not None
        ):
            try:
                root.report_callback_exception = self._original_tk_report_callback_exception
            except Exception:  # noqa: BLE001, S110 - restoring the original Tk hook must not raise during teardown
                pass
