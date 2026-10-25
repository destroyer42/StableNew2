# Subsystem: Learning
# Role: Step indicator, status and single primary action for the guided Designed Experiments workflow.

from __future__ import annotations

import tkinter as tk
from collections.abc import Callable
from functools import partial
from tkinter import ttk

from src.gui.theme_v2 import (
    BODY_LABEL_STYLE,
    MUTED_LABEL_STYLE,
    PRIMARY_BUTTON_STYLE,
    SECONDARY_BUTTON_STYLE,
    SURFACE_FRAME_STYLE,
)
from src.gui.ui_tokens import TOKENS
from src.learning.guided_workflow import (
    STATUS_ATTENTION,
    STATUS_COMPLETED,
    STATUS_LOCKED,
    STATUS_WAITING,
    STEP_ORDER,
    TONE_ERROR,
    TONE_INFO,
    TONE_SUCCESS,
    TONE_WARNING,
    GuidedWorkflowProjection,
)

_STATUS_MARK = {
    STATUS_COMPLETED: "done",
    STATUS_ATTENTION: "needs attention",
    STATUS_WAITING: "waiting",
    STATUS_LOCKED: "locked",
}
_TONE_COLOR = {
    TONE_ERROR: TOKENS.colors.status_error,
    TONE_WARNING: TOKENS.colors.status_warning,
    TONE_SUCCESS: TOKENS.colors.status_success,
    TONE_INFO: TOKENS.colors.status_info,
}


class LearningWorkflowBar(ttk.Frame):
    """Five step buttons, the experiment status, one sentence of guidance and one primary button.

    The bar renders a :class:`GuidedWorkflowProjection`; it owns no workflow state and performs no action itself.
    Locked steps are disabled, every other step (including earlier ones) can be opened for inspection.
    """

    def __init__(
        self,
        master: tk.Misc,
        *,
        on_step: Callable[[str], None],
        on_primary: Callable[[str], None],
        **kwargs: object,
    ) -> None:
        super().__init__(master, style=SURFACE_FRAME_STYLE, padding=(8, 6), **kwargs)  # type: ignore[arg-type]
        self._on_step = on_step
        self._on_primary = on_primary
        self._primary_action = "none"
        self.columnconfigure(0, weight=1)

        steps = ttk.Frame(self, style=SURFACE_FRAME_STYLE)
        steps.grid(row=0, column=0, columnspan=2, sticky="ew")
        self.step_buttons: dict[str, ttk.Button] = {}
        self._step_notes: dict[str, tk.StringVar] = {}
        for column, step in enumerate(STEP_ORDER):
            steps.columnconfigure(column, weight=1, uniform="learning_step")
            cell = ttk.Frame(steps, style=SURFACE_FRAME_STYLE)
            cell.grid(row=0, column=column, sticky="ew", padx=(0 if column == 0 else 3, 0))
            cell.columnconfigure(0, weight=1)
            button = ttk.Button(
                cell,
                text=step.title(),
                style=SECONDARY_BUTTON_STYLE,
                command=partial(self._on_step, step),
            )
            button.grid(row=0, column=0, sticky="ew")
            note = tk.StringVar(value="")
            ttk.Label(cell, textvariable=note, style=MUTED_LABEL_STYLE, wraplength=170).grid(
                row=1, column=0, sticky="w"
            )
            self.step_buttons[step] = button
            self._step_notes[step] = note

        self.status_var = tk.StringVar(value="")
        self.status_label = ttk.Label(self, textvariable=self.status_var, style=BODY_LABEL_STYLE)
        self.status_label.grid(row=1, column=0, columnspan=2, sticky="w", pady=(6, 0))
        self.headline_var = tk.StringVar(value="")
        self.headline_label = ttk.Label(
            self,
            textvariable=self.headline_var,
            style=MUTED_LABEL_STYLE,
            wraplength=900,
            justify="left",
        )
        self.headline_label.grid(row=2, column=0, sticky="ew", pady=(2, 0))
        self.primary_button = ttk.Button(
            self, text="", style=PRIMARY_BUTTON_STYLE, command=self._primary_clicked
        )
        self.primary_button.grid(row=2, column=1, sticky="e", padx=(8, 0), pady=(2, 0))
        self.notice_var = tk.StringVar(value="")
        self.notice_label = ttk.Label(
            self,
            textvariable=self.notice_var,
            style=BODY_LABEL_STYLE,
            foreground=TOKENS.colors.status_warning,
            wraplength=900,
            justify="left",
        )
        self.notice_label.grid(row=3, column=0, columnspan=2, sticky="w", pady=(2, 0))
        self.bind("<Configure>", self._on_configure, add="+")

    def _primary_clicked(self) -> None:
        self._on_primary(self._primary_action)

    def _on_configure(self, event: tk.Event) -> None:
        # Keep guidance text inside the bar at narrow widths (1366 px and below).
        wrap = max(240, int(event.width) - 220)
        self.headline_label.configure(wraplength=wrap)
        self.notice_label.configure(wraplength=max(240, int(event.width) - 24))

    def render(self, projection: GuidedWorkflowProjection, *, experiment_name: str = "") -> None:
        for index, view in enumerate(projection.steps, start=1):
            button = self.step_buttons[view.step]
            marker = "> " if view.is_viewed else ""
            button.configure(text=f"{marker}{index}. {view.label}")
            button.state(["!disabled"] if view.navigable else ["disabled"])
            mark = _STATUS_MARK.get(view.status, "")
            recommended = "next" if view.is_recommended and view.status != STATUS_COMPLETED else ""
            self._step_notes[view.step].set(
                " - ".join(part for part in (mark, recommended) if part) or view.purpose
            )
        name = f"{experiment_name} | " if experiment_name else ""
        flags = f" | {', '.join(projection.flags)}" if projection.flags else ""
        self.status_var.set(f"{name}Status: {projection.status_label}{flags}")
        self.status_label.configure(
            foreground=_TONE_COLOR.get(projection.status_tone, TOKENS.colors.text_primary)
        )
        self.headline_var.set(projection.headline)
        primary = projection.primary
        self._primary_action = primary.action
        self.primary_button.configure(text=primary.label)
        self.primary_button.state(["!disabled"] if primary.enabled else ["disabled"])
        notices = list(projection.notices)
        if not primary.enabled and primary.reason:
            notices.insert(0, primary.reason)
        self.notice_var.set("  ".join(notices))

    @property
    def primary_action(self) -> str:
        return self._primary_action


__all__ = ["LearningWorkflowBar"]
