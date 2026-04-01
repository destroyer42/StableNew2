from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Protocol

from src.gui.gui_invoker import GuiInvoker


class UiDispatcher(Protocol):
    """Toolkit-neutral UI dispatch contract."""

    def invoke(self, fn: Callable[[], None]) -> None:
        """Schedule a callable on the UI thread."""


@dataclass
class TkUiDispatcher:
    """Tk implementation of UiDispatcher using the queued Tk pump."""

    root: object
    _invoker: GuiInvoker | None = field(init=False, default=None, repr=False)

    def __post_init__(self) -> None:
        try:
            self._invoker = GuiInvoker(self.root)
        except Exception:
            self._invoker = None

    def invoke(self, fn: Callable[[], None]) -> None:
        invoker = self._invoker
        if invoker is not None:
            invoker.invoke(fn)
            return
        after = getattr(self.root, "after", None)
        if callable(after):
            try:
                after(0, fn)
                return
            except Exception:
                pass
        fn()


class ImmediateUiDispatcher:
    """Synchronous dispatcher for tests/headless paths."""

    def invoke(self, fn: Callable[[], None]) -> None:
        fn()


__all__ = ["UiDispatcher", "TkUiDispatcher", "ImmediateUiDispatcher"]
