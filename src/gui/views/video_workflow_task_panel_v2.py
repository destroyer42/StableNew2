"""Task selector and Suggested-settings line for the Video Workflow tab (PR-VID-UX-360).

Presentation only.  The selector asks its owner whether a task may be selected and stays where it was
when the owner refuses; the summary line shows what was filled in for the operator and offers to change
or reset it; the pin tracker records which fields the operator edited so suggestions never overwrite
them.  None of these widgets reads a workflow record, builds a job or talks to a controller.
"""

from __future__ import annotations

import tkinter as tk
from collections.abc import Callable, Iterable, Iterator, Mapping, Sequence
from contextlib import contextmanager
from tkinter import ttk
from typing import Any

from src.gui.tooltip import attach_tooltip
from src.gui.widgets.responsive_wrap_v2 import bind_wraplength
from src.video.workflow_tasks import TASKS

SUMMARY_SEPARATOR = " · "


class WorkflowTaskSelector(ttk.Frame):
    """One row of mutually exclusive task choices: "What do you want to make?"."""

    def __init__(self, master: tk.Misc, *, on_select: Callable[[str], bool], **kwargs: Any) -> None:
        super().__init__(master, style="Panel.TFrame", **kwargs)
        self._on_select = on_select
        self._current = TASKS[0].task_id
        self._descriptions = {task.task_id: task.description for task in TASKS}
        self.task_var = tk.StringVar(master=self, value=self._current)
        self.buttons: dict[str, ttk.Radiobutton] = {}
        self._tooltips: dict[str, Any] = {}
        ttk.Label(self, text="Make", style="Dark.TLabel").pack(side="left", padx=(0, 8))
        for task in TASKS:
            button = ttk.Radiobutton(
                self,
                text=task.label,
                value=task.task_id,
                variable=self.task_var,
                style="Dark.TRadiobutton",
                command=lambda task_id=task.task_id: self._on_click(task_id),
            )
            button.pack(side="left", padx=(0, 12))
            self.buttons[task.task_id] = button
            self._tooltips[task.task_id] = attach_tooltip(button, task.description)

    def _on_click(self, task_id: str) -> None:
        if task_id == self._current:
            return
        if self._on_select(task_id):
            self._current = task_id
        self.task_var.set(self._current)

    def set_task(self, task_id: str) -> None:
        """Show ``task_id`` as selected without asking the owner."""

        if task_id in self.buttons:
            self._current = task_id
            self.task_var.set(task_id)

    def set_availability(self, reasons: Mapping[str, str]) -> None:
        """Disable each task that has a reason (shown as its tooltip); enable the rest."""

        for task_id, button in self.buttons.items():
            reason = str(reasons.get(task_id) or "")
            button.configure(state="disabled" if reason else "normal")
            tooltip = self._tooltips.get(task_id)
            text = reason or self._descriptions[task_id]
            if tooltip is not None and hasattr(tooltip, "text"):
                tooltip.text = text


class SuggestedSettingsLine(ttk.Frame):
    """One line saying what was set up for the operator, with Change and Reset to suggested."""

    def __init__(
        self,
        master: tk.Misc,
        *,
        on_change: Callable[[], None],
        on_reset: Callable[[], None],
        **kwargs: Any,
    ) -> None:
        super().__init__(master, style="Panel.TFrame", **kwargs)
        self.columnconfigure(1, weight=1)
        self.summary_var = tk.StringVar(master=self, value="")
        self.notes_var = tk.StringVar(master=self, value="")
        ttk.Label(self, text="Settings", style="Dark.TLabel").grid(
            row=0, column=0, sticky="w", padx=(0, 8)
        )
        self.summary_label = ttk.Label(
            self, textvariable=self.summary_var, style="Dark.TLabel", justify="left"
        )
        self.summary_label.grid(row=0, column=1, sticky="ew")
        bind_wraplength(self.summary_label)
        self.change_button = ttk.Button(
            self, text="Change", style="Dark.TButton", command=on_change
        )
        self.change_button.grid(row=0, column=2, sticky="e", padx=(8, 0))
        self.reset_button = ttk.Button(
            self, text="Reset to suggested", style="Dark.TButton", command=on_reset
        )
        self.reset_button.grid(row=0, column=3, sticky="e", padx=(6, 0))
        self.notes_label = ttk.Label(
            self, textvariable=self.notes_var, style="Muted.TLabel", justify="left"
        )
        self.notes_label.grid(row=1, column=0, columnspan=4, sticky="ew", pady=(2, 0))
        bind_wraplength(self.notes_label)
        self.notes_label.grid_remove()

    def set_summary(self, parts: Sequence[str]) -> None:
        self.summary_var.set(SUMMARY_SEPARATOR.join(str(part) for part in parts if part))

    def set_notes(self, notes: Sequence[str]) -> None:
        text = "\n".join(str(note) for note in notes if note)
        self.notes_var.set(text)
        if text:
            self.notes_label.grid()
        else:
            self.notes_label.grid_remove()

    def set_editing(self, editing: bool) -> None:
        self.change_button.configure(text="Hide" if editing else "Change")


class PinTracker:
    """Which form fields the operator edited.  A write made inside ``applying()`` is the form's own."""

    def __init__(self) -> None:
        self.pinned: set[str] = set()
        self._applying = 0

    def watch(self, field: str, variable: tk.Variable) -> None:
        variable.trace_add("write", lambda *_args: self.pin(field))

    def pin(self, field: str) -> None:
        if not self._applying:
            self.pinned.add(field)

    @contextmanager
    def applying(self) -> Iterator[None]:
        self._applying += 1
        try:
            yield
        finally:
            self._applying -= 1

    def pin_all(self, fields: Iterable[str]) -> None:
        self.pinned.update(fields)

    def clear(self) -> None:
        self.pinned.clear()


__all__ = ["PinTracker", "SuggestedSettingsLine", "WorkflowTaskSelector"]
