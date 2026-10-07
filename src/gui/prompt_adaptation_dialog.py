"""Read-only Tk dialog for the explicit "Adapt for Target" preview (PR-IMG-130C).

Presentation only: it renders an already-built ``AdaptationPreviewModel`` and has no editing path back into the PromptPack.
Closing it changes nothing.
"""

from __future__ import annotations

import tkinter as tk
from tkinter import ttk

from src.gui.theme_v2 import apply_toplevel_theme, style_text_widget
from src.gui_v2.prompt_adaptation_preview import AdaptationPreviewModel


class PromptAdaptationDialog(tk.Toplevel):
    def __init__(self, master: tk.Misc, model: AdaptationPreviewModel) -> None:
        super().__init__(master)
        self.model = model
        self.title("Adapt for Target (preview)")
        self.resizable(True, True)
        apply_toplevel_theme(self)
        self._rendered: list[str] = []

        self._label(model.summary, wrap=720, pady=(8, 6))

        columns = ttk.Frame(self)
        columns.pack(fill="both", expand=True, padx=8)
        columns.columnconfigure(0, weight=1)
        columns.columnconfigure(1, weight=1)
        self.original_text_widget = self._column(columns, 0, "Original positive prompt", model.original_positive)
        self.adapted_text_widget = self._column(columns, 1, "Adapted positive prompt", model.adapted_positive)

        self._label(f"Original negative: {model.original_negative}", pady=(8, 0))
        self._label(f"Adapted negative: {model.adapted_negative}")
        self._label(f"Embeddings: {model.embeddings}")
        self._label(f"LoRAs: {model.loras}")

        if model.steps:
            self._label("Adaptation steps (in order):", pady=(8, 0))
            for number, step in enumerate(model.steps, 1):
                self._label(f"{number}. {step}", wrap=720)
        for note in model.notes:
            self._label(note, wrap=720, pady=(6, 0))

        ttk.Button(self, text="Close", command=self.close).pack(anchor="e", padx=8, pady=8)
        self.protocol("WM_DELETE_WINDOW", self.close)

    def _label(self, text: str, *, wrap: int = 0, pady: tuple[int, int] | int = 0) -> None:
        self._rendered.append(text)
        label = ttk.Label(self, text=text, justify="left", **({"wraplength": wrap} if wrap else {}))
        label.pack(anchor="w", padx=8, pady=pady)

    def _column(self, parent: ttk.Frame, column: int, heading: str, text: str) -> tk.Text:
        self._rendered.append(heading)
        frame = ttk.Frame(parent)
        frame.grid(row=0, column=column, sticky="nsew", padx=(0, 4) if column == 0 else (4, 0))
        ttk.Label(frame, text=heading).pack(anchor="w")
        widget = tk.Text(frame, height=8, width=44, wrap="word")
        style_text_widget(widget)
        widget.insert("1.0", text)
        widget.configure(state="disabled")  # read-only: there is no path back into the PromptPack
        widget.pack(fill="both", expand=True)
        return widget

    def visible_text(self) -> str:
        """Everything the dialog shows (labels and both read-only text boxes), for tests and diagnostics."""

        boxes = [self.original_text_widget.get("1.0", "end"), self.adapted_text_widget.get("1.0", "end")]
        return "\n".join(self._rendered + boxes)

    def close(self) -> None:
        try:
            self.destroy()
        except tk.TclError:
            pass


__all__ = ["PromptAdaptationDialog"]
