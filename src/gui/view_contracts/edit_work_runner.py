"""Keyed, latest-wins background work for the Edit workspaces (Review and Photo Optimize), PR-GUI-UX-580.

One thin wrapper over the existing ``BackgroundTaskCoordinator`` (tracked threads, one in-flight task per key, a newer
request supersedes older pending work and only the latest result is delivered). The runner adds the two guarantees a
Tk view needs: a callback never runs after the owning widget is closed or destroyed, and the callbacks always run on the
UI thread through the injected dispatcher. It owns no queue, executor or lifecycle of its own.
"""

from __future__ import annotations

import tkinter as tk
from collections.abc import Callable
from typing import Any, TypeVar

from src.controller.app_controller_services.background_task_coordinator import (
    BackgroundTaskCoordinator,
)
from src.gui.ui_dispatcher import tk_dispatcher_for

T = TypeVar("T")


def _tk_coordinator(widget: tk.Misc) -> BackgroundTaskCoordinator:
    dispatcher = tk_dispatcher_for(widget)
    return BackgroundTaskCoordinator(dispatcher=dispatcher.invoke)


#: Tests replace this with ``lambda widget: BackgroundTaskCoordinator(run_inline=True)`` (or a coordinator over a
#: manually driven thread registry) so workers run deterministically without sleeps.
coordinator_factory: Callable[[tk.Misc], BackgroundTaskCoordinator] = _tk_coordinator


class EditWorkRunner:
    """Run keyed work off the UI thread and deliver only the latest result of each key, only while open."""

    def __init__(
        self, coordinator: BackgroundTaskCoordinator, *, is_alive: Callable[[], bool]
    ) -> None:
        self._coordinator = coordinator
        self._is_alive = is_alive
        self._closed = False

    @property
    def closed(self) -> bool:
        return self._closed

    def close(self) -> None:
        """Drop every later callback; work already running finishes unobserved."""

        self._closed = True

    def _live(self) -> bool:
        if self._closed:
            return False
        try:
            return bool(self._is_alive())
        except tk.TclError:
            return False

    def submit(
        self,
        key: str,
        work: Callable[[], T],
        *,
        on_result: Callable[[T], None] | None = None,
        on_error: Callable[[Exception], None] | None = None,
        on_complete: Callable[[bool, Exception | None], None] | None = None,
        name: str | None = None,
        purpose: str | None = None,
    ) -> int:
        """Queue ``work`` under ``key``; a newer submit for the same key supersedes this one's result."""

        def guarded_result(value: T) -> None:
            if on_result is not None and self._live():
                on_result(value)

        def guarded_error(error: Exception) -> None:
            if on_error is not None and self._live():
                on_error(error)

        def guarded_complete(is_latest: bool, error: Exception | None) -> None:
            if on_complete is not None and self._live():
                on_complete(is_latest, error)

        if self._closed:
            return 0
        return self._coordinator.submit(
            key,
            work,
            on_result=guarded_result,
            on_error=guarded_error,
            on_complete=guarded_complete,
            name=name,
            purpose=purpose,
        )

    def metrics(self) -> dict[str, Any]:
        return self._coordinator.get_metrics_snapshot()


def build_edit_work_runner(widget: tk.Misc) -> EditWorkRunner:
    """Runner bound to ``widget``: callbacks stop once the widget no longer exists."""

    return EditWorkRunner(coordinator_factory(widget), is_alive=widget.winfo_exists)


__all__ = ["EditWorkRunner", "build_edit_work_runner", "coordinator_factory"]
