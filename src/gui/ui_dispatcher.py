from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Protocol


class UiDispatcher(Protocol):
    """Toolkit-neutral UI dispatch contract."""

    def invoke(self, fn: Callable[[], None]) -> None:
        """Schedule a callable on the UI thread."""


@dataclass
class TkUiDispatcher:
    """Tk implementation of UiDispatcher using root.after."""

    root: object

    def invoke(self, fn: Callable[[], None]) -> None:
        after = getattr(self.root, "after", None)
        if callable(after):
            after(0, fn)
            return
        fn()


class ImmediateUiDispatcher:
    """Synchronous dispatcher for tests/headless paths."""

    def invoke(self, fn: Callable[[], None]) -> None:
        fn()


__all__ = ["UiDispatcher", "TkUiDispatcher", "ImmediateUiDispatcher"]
