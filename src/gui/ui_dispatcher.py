from __future__ import annotations

import threading
from collections.abc import Callable
from dataclasses import dataclass, field

from src.controller.ports.ui_dispatcher import ImmediateUiDispatcher, UiDispatcher
from src.gui.gui_invoker import TkInvoker


@dataclass
class TkUiDispatcher:
    """Tk implementation of the toolkit-neutral UiDispatcher contract."""

    root: object
    _invoker: TkInvoker | None = field(init=False, default=None, repr=False)
    _ui_thread_id: int = field(init=False, repr=False)

    def __post_init__(self) -> None:
        self._ui_thread_id = threading.get_ident()
        try:
            self._invoker = TkInvoker(self.root)  # type: ignore[arg-type]
        except Exception:
            self._invoker = None

    def schedule(self, fn: Callable[[], None]) -> None:
        invoker = self._invoker
        if invoker is not None:
            invoker.schedule(fn)
            return
        if not self._after(0, fn):
            fn()

    def _after(self, delay_ms: int, fn: Callable[[], None]) -> bool:
        after = getattr(self.root, "after", None)
        if not callable(after):
            return False
        try:
            after(max(0, int(delay_ms)), fn)
        except Exception:
            return False
        return True

    def invoke(self, fn: Callable[[], None]) -> None:
        """Backward-compatible name for :meth:`schedule`."""
        self.schedule(fn)

    def invoke_later(self, delay_ms: int, fn: Callable[[], None]) -> None:
        invoker = self._invoker
        if invoker is not None:
            invoker.invoke_later(delay_ms, fn)
            return
        if not self._after(delay_ms, fn):
            fn()

    def run_on_ui_thread(self, fn: Callable[[], None]) -> None:
        invoker = self._invoker
        if invoker is not None:
            invoker.run_on_ui_thread(fn)
            return
        if threading.get_ident() == self._ui_thread_id:
            fn()
            return
        self.schedule(fn)


__all__ = ["ImmediateUiDispatcher", "TkUiDispatcher", "UiDispatcher"]
