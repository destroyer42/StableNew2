# Subsystem: Learning
# Role: Read-only card describing exactly what a frozen experiment Preview would submit.

from __future__ import annotations

import tkinter as tk
from tkinter import ttk

from src.gui.theme_v2 import BODY_LABEL_STYLE, CARD_FRAME_STYLE, MUTED_LABEL_STYLE
from src.gui.ui_tokens import TOKENS
from src.learning.preview_summary import PreviewSummary


class LearningPreviewCard(ttk.LabelFrame):
    """Presents a :class:`PreviewSummary`; it owns no data and queues nothing."""

    def __init__(self, master: tk.Misc, **kwargs: object) -> None:
        super().__init__(master, text="Frozen Preview", padding=8, style=CARD_FRAME_STYLE, **kwargs)  # type: ignore[arg-type]
        self.columnconfigure(1, weight=1)
        self.headline_var = tk.StringVar(value="")
        ttk.Label(self, textvariable=self.headline_var, style=BODY_LABEL_STYLE).grid(
            row=0, column=0, columnspan=2, sticky="w"
        )
        self._rows = ttk.Frame(self)
        self._rows.grid(row=1, column=0, columnspan=2, sticky="ew", pady=(6, 0))
        self._rows.columnconfigure(1, weight=1)
        self.warning_var = tk.StringVar(value="")
        self.warning_label = ttk.Label(
            self,
            textvariable=self.warning_var,
            style=BODY_LABEL_STYLE,
            foreground=TOKENS.colors.status_warning,
            wraplength=640,
            justify="left",
        )
        self.warning_label.grid(row=2, column=0, columnspan=2, sticky="w", pady=(6, 0))
        self.bind("<Configure>", self._on_configure, add="+")
        self._value_labels: list[ttk.Label] = []
        self.render(None, stale=False)

    def _on_configure(self, event: tk.Event) -> None:
        wrap = max(240, int(event.width) - 40)
        self.warning_label.configure(wraplength=wrap)
        for label in self._value_labels:
            label.configure(wraplength=max(200, wrap - 180))

    def render(self, summary: PreviewSummary | None, *, stale: bool) -> None:
        for child in self._rows.winfo_children():
            child.destroy()
        self._value_labels = []
        if summary is None:
            self.headline_var.set(
                "No Preview yet. Building a Preview freezes the plan and queues nothing."
            )
            self.warning_var.set("")
            return
        self.headline_var.set(
            summary.headline
            + (" - OUT OF DATE: the design changed after this Preview" if stale else "")
        )
        for index, (label, value) in enumerate(summary.rows):
            ttk.Label(self._rows, text=f"{label}:", style=MUTED_LABEL_STYLE).grid(
                row=index, column=0, sticky="nw", padx=(0, 10)
            )
            value_label = ttk.Label(
                self._rows, text=value, style=BODY_LABEL_STYLE, justify="left", wraplength=420
            )
            value_label.grid(row=index, column=1, sticky="w")
            self._value_labels.append(value_label)
        warnings = list(summary.warnings)
        if stale:
            warnings.insert(0, "This Preview cannot be run. Return to Design and build it again.")
        self.warning_var.set("  ".join(warnings))


__all__ = ["LearningPreviewCard"]
