"""Renders the operator controls a video workflow declares (PR-VID-192).

The panel owns no execution policy: it shows exactly the controls the selected workflow spec
declared (``operator_controls`` projection), starts every number at the declared default so the
operator sees the real value, and reports raw operator text back.  Validation, the fallback for an
empty text control and freezing into the immutable job stay in ``VideoWorkflowController`` /
``src.video.workflow_controls``.  With no declared controls the panel is hidden, so nothing implies
a setting will be honoured when it will not.
"""

from __future__ import annotations

import tkinter as tk
from collections.abc import Callable, Mapping
from tkinter import ttk
from typing import Any

from src.gui.theme_v2 import style_text_widget
from src.gui.tooltip import attach_tooltip


def _format_default(value: Any) -> str:
    try:
        return f"{float(value):g}"
    except (TypeError, ValueError):
        return str(value)


class WorkflowControlsPanel(ttk.LabelFrame):
    """A dynamic form section for a workflow's declared numeric/text controls."""

    def __init__(
        self,
        master: tk.Misc,
        *,
        on_change: Callable[[], None] | None = None,
        title: str = "Workflow Controls",
    ) -> None:
        super().__init__(master, text=title, padding=8)
        self._on_change = on_change
        self._controls: list[dict[str, Any]] = []
        self._vars: dict[str, tk.StringVar] = {}
        self._texts: dict[str, tk.Text] = {}
        self.columnconfigure(1, weight=1)

    # ------------------------------------------------------------------ structure

    @property
    def control_names(self) -> list[str]:
        return [control["name"] for control in self._controls]

    def apply(self, controls: list[dict[str, Any]] | None) -> None:
        """Show exactly ``controls`` (defaults selected), or hide the panel when there are none."""

        declared = [dict(control) for control in controls or []]
        if declared == self._controls and declared:
            return
        for child in self.winfo_children():
            child.destroy()
        self._controls = declared
        self._vars = {}
        self._texts = {}
        if not declared:
            self.grid_remove()
            return
        for row, control in enumerate(declared):
            self._build_row(row, control)
        self.grid()

    def _build_row(self, row: int, control: dict[str, Any]) -> None:
        name = control["name"]
        label = ttk.Label(self, text=control["label"], style="Dark.TLabel")
        help_text = str(control.get("help") or "")
        widget: tk.Widget
        if control["kind"] == "text":
            label.grid(row=row, column=0, sticky="nw", padx=(0, 8), pady=(0, 6))
            text_widget = tk.Text(self, height=3, wrap="word")
            style_text_widget(text_widget, elevated=True)
            text_widget.grid(row=row, column=1, columnspan=2, sticky="nsew", pady=(0, 6))
            text_widget.bind("<KeyRelease>", lambda _e: self._changed(), add="+")
            self._texts[name] = text_widget
            widget = text_widget
        else:
            label.grid(row=row, column=0, sticky="w", padx=(0, 8), pady=(0, 6))
            variable = tk.StringVar(value=_format_default(control["default"]))
            variable.trace_add("write", lambda *_a: self._changed())
            widget = ttk.Entry(self, textvariable=variable, style="Dark.TEntry", width=12)
            widget.grid(row=row, column=1, sticky="w", pady=(0, 6))
            self._vars[name] = variable
            ttk.Label(
                self,
                text=(
                    f"default {_format_default(control['default'])} "
                    f"(range {_format_default(control['minimum'])} to "
                    f"{_format_default(control['maximum'])})"
                ),
                style="Muted.TLabel",
            ).grid(row=row, column=2, sticky="w", padx=(8, 0), pady=(0, 6))
        if help_text:
            attach_tooltip(label, help_text)
            attach_tooltip(widget, help_text)

    # ------------------------------------------------------------------ state

    def get_values(self) -> dict[str, str]:
        """Raw operator text for every shown control (empty text/number means 'use the default')."""

        values: dict[str, str] = {}
        for control in self._controls:
            name = control["name"]
            if control["kind"] == "text":
                values[name] = self._texts[name].get("1.0", "end").strip()
            else:
                values[name] = self._vars[name].get().strip()
        return values

    def set_values(self, values: Mapping[str, Any] | None) -> None:
        """Restore saved values for the shown controls; unknown/missing names are ignored."""

        if not isinstance(values, Mapping):
            return
        for control in self._controls:
            name = control["name"]
            if name not in values or values[name] is None:
                continue
            if control["kind"] == "text":
                widget = self._texts[name]
                widget.delete("1.0", "end")
                widget.insert("1.0", str(values[name]))
            else:
                self._vars[name].set(str(values[name]))

    def summary_parts(self) -> list[str]:
        """Effective-settings fragments; a number that differs from its default is marked."""

        parts: list[str] = []
        for control in self._controls:
            name = control["name"]
            if control["kind"] == "text":
                text = self._texts[name].get("1.0", "end").strip()
                parts.append(f"{name}={'custom' if text else 'same as prompt'}")
                continue
            text = self._vars[name].get().strip()
            shown = text or _format_default(control["default"])
            is_default = False
            try:
                is_default = float(shown) == float(control["default"])
            except ValueError:
                pass
            parts.append(f"{name}={shown}{'' if is_default else ' [changed]'}")
        return parts

    def _changed(self) -> None:
        if self._on_change is not None:
            self._on_change()


__all__ = ["WorkflowControlsPanel"]
