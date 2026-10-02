"""Tk rendering of the Video Workflow "Compare one control" section (PR-VID-194).

Presentation only: the state machine lives in ``VideoExperimentSession``.  The variable list is the
selected workflow's declared operator controls; a number control gets an entry and a text control a
small text box, both rendered from the declaration.  This module builds no payload, calls no
backend and branches on no workflow or model.
"""

from __future__ import annotations

import tkinter as tk
from collections.abc import Callable
from tkinter import ttk
from typing import Any

from src.gui.theme_v2 import style_text_widget
from src.gui.view_contracts.video_experiment_contract import (
    MAX_CANDIDATES,
    VideoExperimentSession,
)


class WorkflowExperimentPanel(ttk.LabelFrame):
    """Compact experiment section; hidden while the workflow declares no controls."""

    def __init__(
        self,
        master: tk.Misc,
        *,
        session: VideoExperimentSession,
        read_form: Callable[[], tuple[str, dict[str, Any]]],
        on_queued: Callable[[list[str]], None] | None = None,
    ) -> None:
        super().__init__(master, text="Compare one control", padding=8)
        self._session = session
        self._read_form = read_form
        self._on_queued = on_queued
        self._candidate_widgets: list[Any] = []
        self._label_to_name: dict[str, str] = {}
        self.enabled_var = tk.BooleanVar(value=False)
        self.variable_var = tk.StringVar(value="")
        self.baseline_var = tk.StringVar(value="")
        self.message_var = tk.StringVar(value="")
        self.columnconfigure(1, weight=1)

        ttk.Checkbutton(
            self,
            text="Compare one control (baseline + up to 3 values, one admission)",
            variable=self.enabled_var,
            command=self._on_toggle,
        ).grid(row=0, column=0, columnspan=3, sticky="w")

        self.detail = ttk.Frame(self, style="Panel.TFrame")
        self.detail.grid(row=1, column=0, columnspan=3, sticky="ew", pady=(6, 0))
        self.detail.columnconfigure(1, weight=1)
        ttk.Label(self.detail, text="Control", style="Dark.TLabel").grid(
            row=0, column=0, sticky="w", padx=(0, 8)
        )
        self.variable_combo = ttk.Combobox(
            self.detail,
            textvariable=self.variable_var,
            values=[],
            state="readonly",
            style="Dark.TCombobox",
            width=34,
        )
        self.variable_combo.grid(row=0, column=1, sticky="w")
        self.variable_combo.bind("<<ComboboxSelected>>", lambda _e: self._on_variable())
        ttk.Label(self.detail, text="Baseline (A)", style="Dark.TLabel").grid(
            row=1, column=0, sticky="w", padx=(0, 8), pady=(6, 0)
        )
        ttk.Label(
            self.detail, textvariable=self.baseline_var, style="Muted.TLabel", wraplength=640
        ).grid(row=1, column=1, sticky="w", pady=(6, 0))

        self.candidates_frame = ttk.Frame(self.detail, style="Panel.TFrame")
        self.candidates_frame.grid(row=2, column=0, columnspan=2, sticky="ew", pady=(6, 0))
        self.candidates_frame.columnconfigure(1, weight=1)
        self.add_button = ttk.Button(
            self.detail, text="Add value", style="Dark.TButton", command=self._on_add
        )
        self.add_button.grid(row=3, column=1, sticky="w", pady=(4, 0))

        actions = ttk.Frame(self.detail, style="Panel.TFrame")
        actions.grid(row=4, column=0, columnspan=2, sticky="ew", pady=(8, 0))
        self.preview_button = ttk.Button(
            actions, text="Build Preview", style="Dark.TButton", command=self._on_preview
        )
        self.preview_button.pack(side="left")
        self.queue_button = ttk.Button(
            actions, text="Queue Experiment", style="Primary.TButton", command=self._on_queue
        )
        self.queue_button.pack(side="left", padx=(8, 0))
        self.cancel_button = ttk.Button(
            actions, text="Cancel Preview", style="Dark.TButton", command=self._on_cancel
        )
        self.cancel_button.pack(side="left", padx=(8, 0))

        self.preview_text = tk.Text(self.detail, height=10, wrap="word", state="disabled")
        style_text_widget(self.preview_text, elevated=True)
        self.preview_text.grid(row=5, column=0, columnspan=2, sticky="ew", pady=(8, 0))
        ttk.Label(
            self.detail, textvariable=self.message_var, style="Muted.TLabel", wraplength=640
        ).grid(row=6, column=0, columnspan=2, sticky="w", pady=(4, 0))
        self.refresh()

    # ------------------------------------------------------------------ session binding

    def apply_controls(self, controls: list[dict[str, Any]] | None) -> None:
        """Show exactly the workflow's declared controls, or hide when there are none."""

        self._session.apply_controls(controls)
        self.enabled_var.set(self._session.enabled)
        self._label_to_name = {label: name for name, label in self._session.variable_choices}
        self.variable_combo["values"] = list(self._label_to_name)
        control = self._session.variable_control
        self.variable_var.set(control["label"] if control else "")
        if self._session.available:
            self.grid()
        else:
            self.grid_remove()
        self._rebuild_candidates()
        self.refresh()

    def refresh(self) -> None:
        """Re-render status, preview and button states (does not touch candidate entries)."""

        session = self._session
        show = self.enabled_var.get() and session.available
        if show:
            self.detail.grid()
        else:
            self.detail.grid_remove()
        self.message_var.set(session.message)
        self.baseline_var.set(self._baseline_text() if show else "")
        self.add_button.configure(
            state="normal" if len(session.candidates) < MAX_CANDIDATES else "disabled"
        )
        self.queue_button.configure(state="normal" if session.preview_valid else "disabled")
        self.cancel_button.configure(state="normal" if session.preview_valid else "disabled")
        self._render_preview()

    def invalidate_if_changed(self) -> None:
        if not (self._session.preview_valid or self.enabled_var.get()):
            return  # nothing previewed and comparing is off: no form read needed
        source, form = self._read_form()
        if self._session.invalidate_if_changed(source, form):
            self.refresh()
        elif self.enabled_var.get() and self._session.available:
            self.baseline_var.set(self._baseline_text())

    # ------------------------------------------------------------------ rendering

    def _baseline_text(self) -> str:
        _source, form = self._read_form()
        return self._session.baseline_text(form)

    def _render_preview(self) -> None:
        view = self._session.preview
        lines: list[str] = []
        if view is not None:
            lines.append(f"Experiment {view.experiment_id}   common seed {view.common_seed}")
            lines.append(view.statement)
            lines.append("")
            lines.extend(f"{label}:  {value}" for label, value in view.arms)
            lines.append("")
            lines.append("Fixed across every job:")
            lines.extend(f"  {label}: {value}" for label, value in view.fixed)
        self.preview_text.configure(state="normal")
        self.preview_text.delete("1.0", "end")
        self.preview_text.insert("1.0", "\n".join(lines))
        self.preview_text.configure(state="disabled")

    def _rebuild_candidates(self) -> None:
        for child in self.candidates_frame.winfo_children():
            child.destroy()
        self._candidate_widgets = []
        control = self._session.variable_control
        if control is None:
            return
        for index, text in enumerate(self._session.candidates):
            ttk.Label(
                self.candidates_frame, text=f"Value {chr(ord('B') + index)}", style="Dark.TLabel"
            ).grid(row=index, column=0, sticky="nw", padx=(0, 8), pady=(0, 4))
            widget: Any
            if control["kind"] == "text":
                widget = tk.Text(self.candidates_frame, height=2, wrap="word")
                style_text_widget(widget, elevated=True)
                widget.insert("1.0", text)
                widget.bind(
                    "<KeyRelease>",
                    lambda _e, i=index, w=widget: self._on_candidate(i, w.get("1.0", "end")),
                    add="+",
                )
            else:
                variable = tk.StringVar(value=text)
                variable.trace_add(
                    "write", lambda *_a, i=index, v=variable: self._on_candidate(i, v.get())
                )
                widget = ttk.Entry(
                    self.candidates_frame, textvariable=variable, style="Dark.TEntry", width=14
                )
                widget._experiment_var = variable  # keep the variable alive with the widget
            widget.grid(row=index, column=1, sticky="ew", pady=(0, 4))
            ttk.Button(
                self.candidates_frame,
                text="Remove",
                style="Dark.TButton",
                command=lambda i=index: self._on_remove(i),
            ).grid(row=index, column=2, padx=(6, 0), pady=(0, 4))
            self._candidate_widgets.append(widget)

    # ------------------------------------------------------------------ handlers

    def _on_toggle(self) -> None:
        self._session.set_enabled(self.enabled_var.get())
        self.enabled_var.set(self._session.enabled)
        self.refresh()

    def _on_variable(self) -> None:
        self._session.select_variable(self._label_to_name.get(self.variable_var.get(), ""))
        self._rebuild_candidates()
        self.refresh()

    def _on_add(self) -> None:
        if self._session.add_candidate():
            self._rebuild_candidates()
        self.refresh()

    def _on_remove(self, index: int) -> None:
        if self._session.remove_candidate(index):
            self._rebuild_candidates()
        self.refresh()

    def _on_candidate(self, index: int, text: str) -> None:
        self._session.set_candidate(index, text.strip())
        self.refresh()

    def _on_preview(self) -> None:
        source, form = self._read_form()
        self._session.build_preview(source, form)
        self.refresh()

    def _on_cancel(self) -> None:
        self._session.cancel_preview()
        self.refresh()

    def _on_queue(self) -> None:
        source, form = self._read_form()
        job_ids = self._session.queue(source, form)
        self.refresh()
        if job_ids and self._on_queued is not None:
            self._on_queued(job_ids)


__all__ = ["WorkflowExperimentPanel"]
