"""Toolkit-neutral UI scheduling contract.

Presentation toolkits implement this protocol at the application edge.
Controller and state code may depend on this contract but never on Tk/Qt
scheduler types directly.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Protocol

type UiCallback = Callable[[], None]


class UiDispatcher(Protocol):
    """Minimal toolkit-neutral contract for UI-thread delivery."""

    def schedule(self, fn: UiCallback) -> None:
        """Queue ``fn`` for normal UI-thread delivery."""

    def invoke_later(self, delay_ms: int, fn: UiCallback) -> None:
        """Queue ``fn`` for UI-thread delivery after approximately ``delay_ms``."""

    def run_on_ui_thread(self, fn: UiCallback) -> None:
        """Run inline when already on the UI thread, otherwise marshal to it."""


class ImmediateUiDispatcher:
    """Synchronous implementation for deterministic tests/headless state."""

    def schedule(self, fn: UiCallback) -> None:
        fn()

    def invoke_later(self, delay_ms: int, fn: UiCallback) -> None:
        del delay_ms
        fn()

    def run_on_ui_thread(self, fn: UiCallback) -> None:
        fn()

    def invoke(self, fn: UiCallback) -> None:
        """Compatibility name for callers still using the old dispatcher API."""
        self.schedule(fn)


__all__ = ["ImmediateUiDispatcher", "UiCallback", "UiDispatcher"]
