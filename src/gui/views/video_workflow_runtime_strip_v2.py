"""Tk rendering of the Video Workflow "Runtime readiness" strip (PR-VID-UX-311).

Presentation only: every rule lives in ``workflow_preflight`` and ``RuntimeReadinessSession``. The probe reads RAM, the
driver's GPU memory and, when ComfyUI is already serving, its node list, so it runs on a worker owned by the existing
``ThreadRegistry``; widget reads happen before the worker starts and every widget update is marshalled back to the Tk
thread through ``TkUiDispatcher``. The strip has no control that changes the form or what is submitted (Refresh only
re-runs the read-only probe) and it never starts, stops or adopts a process.
"""

from __future__ import annotations

import tkinter as tk
from collections.abc import Callable
from tkinter import ttk
from typing import Any

from src.gui.ui_dispatcher import TkUiDispatcher
from src.gui.view_contracts.video_experiment_contract import BackgroundWorkRunner, WorkOutcome
from src.gui.view_contracts.video_runtime_readiness_contract import (
    RuntimeReadinessSession,
    RuntimeReadinessView,
    RuntimeReadinessWork,
)
from src.gui.widgets.responsive_wrap_v2 import bind_wraplength
from src.utils.thread_registry import get_thread_registry

_STATE_TAG = {"ok": "OK", "blocked": "BLOCKED", "unknown": "LATER"}


class WorkflowRuntimeReadinessStrip(ttk.LabelFrame):
    """Compact, read-only gate list for the selected workflow; hidden while no workflow is selected."""

    def __init__(
        self,
        master: tk.Misc,
        *,
        session: RuntimeReadinessSession,
        read_selection: Callable[[], tuple[str, str]],
        on_change: Callable[[], None] | None = None,
        runner: BackgroundWorkRunner | None = None,
    ) -> None:
        super().__init__(master, text="Runtime readiness", padding=8)
        self._session = session
        self._read_selection = read_selection
        self._on_change = on_change
        self._runner = runner
        self._closed = False
        self._last_view: RuntimeReadinessView | None = None
        self.columnconfigure(0, weight=1)
        self.summary_var = tk.StringVar(value="")
        self.summary_label = ttk.Label(self, textvariable=self.summary_var, style="Dark.TLabel")
        self.summary_label.grid(row=0, column=0, sticky="ew")
        bind_wraplength(self.summary_label)
        self.rows_frame = ttk.Frame(self, style="Panel.TFrame")
        self.rows_frame.grid(row=1, column=0, sticky="ew", pady=(4, 0))
        self.rows_frame.columnconfigure(1, weight=1)
        self._row_labels: list[ttk.Label] = []
        self.refresh_button = ttk.Button(
            self,
            text="Refresh",
            style="Dark.TButton",
            command=lambda: self.request_refresh(force=True),
        )
        self.refresh_button.grid(row=2, column=0, sticky="w", pady=(6, 0))
        self.bind("<Destroy>", self._on_destroy, add="+")
        self.render()

    # ------------------------------------------------------------------ requests (Tk thread)

    def request_refresh(self, *, force: bool = False) -> None:
        if self._closed:
            return
        try:
            workflow_id, workflow_version = self._read_selection()
        except Exception:  # noqa: BLE001 - an unreadable form leaves what is displayed as it is
            return
        work = self._session.refresh(workflow_id, workflow_version, force=force)
        if work is not None:
            self._start(work)
        self.render()
        self._notify()

    def _work_runner(self) -> BackgroundWorkRunner:
        if self._runner is None:
            dispatcher = TkUiDispatcher(self.winfo_toplevel())
            self._runner = BackgroundWorkRunner(
                spawn=lambda name, target: get_thread_registry().spawn(
                    target=target,
                    name=name,
                    daemon=False,
                    purpose="Check Video Workflow runtime readiness without blocking Tk",
                ),
                dispatch=dispatcher.invoke,
            )
        return self._runner

    def _start(self, work: RuntimeReadinessWork) -> None:
        self._work_runner().start(
            f"VideoRuntimeReadiness-{id(self)}",
            lambda: self._session.run(work),
            lambda outcome: self._deliver(lambda: self._finish(work, outcome)),
        )

    def _deliver(self, finish: Callable[[], None]) -> None:
        if self._closed:
            return
        try:
            if not self.winfo_exists():
                return
            finish()
        except tk.TclError:
            pass  # the widget tree is going away; there is nothing left to update

    def _finish(self, work: RuntimeReadinessWork, outcome: WorkOutcome) -> None:
        follow_up = self._session.finish(work, outcome)
        self.render()
        self._notify()
        if follow_up is not None:
            self._start(follow_up)

    def _notify(self) -> None:
        if self._on_change is not None:
            self._on_change()

    def _on_destroy(self, event: Any = None) -> None:
        if event is None or event.widget is self:
            self._closed = True
            self._session.close()

    # ------------------------------------------------------------------ rendering (Tk thread)

    def render(self) -> None:
        view = self._session.view()
        self._last_view = view
        if view.state == "idle":
            self.grid_remove()
            return
        self.grid()
        self.summary_var.set(view.summary)
        for label in self._row_labels:
            label.destroy()
        self._row_labels = []
        for index, row in enumerate(view.rows):
            tag = ttk.Label(
                self.rows_frame,
                text=_STATE_TAG.get(row.state, row.state.upper()),
                style="Muted.TLabel",
                width=8,
            )
            tag.grid(row=index, column=0, sticky="nw", padx=(0, 6))
            text = f"{row.label}: {row.detail}" + (
                f" {row.fix}" if row.fix and row.state == "blocked" else ""
            )
            body = ttk.Label(self.rows_frame, text=text, style="Dark.TLabel", justify="left")
            body.grid(row=index, column=1, sticky="ew")
            bind_wraplength(body)
            self._row_labels.extend((tag, body))
        self.refresh_button.configure(state="disabled" if view.busy else "normal")

    @property
    def last_view(self) -> RuntimeReadinessView | None:
        return self._last_view


__all__ = ["WorkflowRuntimeReadinessStrip"]
