"""Re-run with tweaks for the Video Workflow tab (V1-2): read a finished job off the Tk thread, then fill the form.

Presentation glue only.  The job is read and its driving video verified by the Tk-free ``src.video.motion_rerun``
functions on a worker owned by the ``ThreadRegistry``; the result returns to the Tk thread through ``TkUiDispatcher``
and is dropped when a newer request superseded it or the tab is gone.  Nothing is queued here: the operator changes
what they like and queues through the normal form, ``VideoWorkflowNjrBuilder`` and ``JobService``.
"""

from __future__ import annotations

import tkinter as tk
from collections.abc import Callable
from typing import Any

from src.gui.ui_dispatcher import tk_dispatcher_for
from src.gui.view_contracts.video_experiment_contract import BackgroundWorkRunner, WorkOutcome
from src.utils.thread_registry import get_thread_registry
from src.video.motion_rerun import RerunOpening, open_rerun


class RerunHost:
    """One pending *Re-run with tweaks...* request at a time; a newer one supersedes it."""

    def __init__(
        self,
        widget: tk.Misc,
        *,
        repository: Callable[[], Any],
        on_opened: Callable[[RerunOpening], None],
        on_refused: Callable[[str], None],
        on_status: Callable[[str], None],
        runner: BackgroundWorkRunner | None = None,
    ) -> None:
        self._widget = widget
        self._repository = repository
        self._on_opened = on_opened
        self._on_refused = on_refused
        self._on_status = on_status
        self._runner = runner
        self._token = 0

    def _work_runner(self) -> BackgroundWorkRunner:
        if self._runner is None:
            dispatcher = tk_dispatcher_for(self._widget)
            self._runner = BackgroundWorkRunner(
                spawn=lambda name, target: get_thread_registry().spawn(
                    target=target,
                    name=name,
                    daemon=False,
                    purpose="Read a finished video job for Re-run with tweaks without blocking Tk",
                ),
                dispatch=lambda fn: dispatcher.invoke(lambda: self._deliver(fn)),
            )
        return self._runner

    def _deliver(self, finish: Callable[[], None]) -> None:
        try:
            if self._widget.winfo_exists():
                finish()
        except tk.TclError:
            pass  # the tab is going away

    def open(self, job_id: str) -> None:
        self._token += 1
        token = self._token
        repository = self._repository()  # the object only; every read happens on the worker
        self._on_status(f"Reading job {job_id} for Re-run with tweaks...")

        def work() -> WorkOutcome:
            return WorkOutcome(value=open_rerun(repository, job_id))

        self._work_runner().start(
            "video-rerun-open", work, lambda outcome: self._finish(token, outcome)
        )

    def _finish(self, token: int, outcome: WorkOutcome) -> None:
        if token != self._token:
            return  # superseded by a newer request
        if outcome.error or not isinstance(outcome.value, RerunOpening):
            self._on_refused(f"Re-run with tweaks is not available: {outcome.error or 'no job'}")
            return
        self._on_opened(outcome.value)


__all__ = ["RerunHost"]
