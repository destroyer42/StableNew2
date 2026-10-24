"""The "Iterate from History" choice dialog (PR-HISTORY-610A).

Shows the two deliberate choices for one completed job, each with what it does and - when it is not available - the plain
reason. Choosing one only calls back; it never loads anything itself, and the dialog is modeless so it cannot block the
history table or a test. Reasons come from ``assess_history_iterate`` and never contain prompt text.
"""

from __future__ import annotations

import tkinter as tk
from collections.abc import Callable
from tkinter import ttk

from src.gui import theme_v2 as theme_mod
from src.gui_v2.history_iterate_model import IterateAssessment, IterateChoice

CHOICE_REVIEW = "edit_image"
CHOICE_PIPELINE = "regenerate"


class HistoryIterateDialog(tk.Toplevel):
    def __init__(
        self,
        master: tk.Misc,
        assessment: IterateAssessment,
        *,
        on_choose: Callable[[str], None],
    ) -> None:
        super().__init__(master)
        self.title("Iterate from History")
        self.resizable(False, False)
        self._on_choose = on_choose
        self.assessment = assessment
        body = ttk.Frame(self, style=theme_mod.SURFACE_FRAME_STYLE, padding=theme_mod.PADDING_MD)
        body.pack(fill=tk.BOTH, expand=True)
        ttk.Label(
            body,
            text=f"Job {assessment.job_id or '(unknown)'}",
            style=theme_mod.STATUS_STRONG_LABEL_STYLE,
        ).pack(anchor=tk.W, pady=(0, 6))
        self.edit_btn = self._block(
            body, "Edit Image in Review", assessment.review, CHOICE_REVIEW, "Edit Image in Review"
        )
        self.regenerate_btn = self._block(
            body,
            "Regenerate with Changes in Pipeline",
            assessment.pipeline,
            CHOICE_PIPELINE,
            "Regenerate with Changes",
        )
        ttk.Label(
            body,
            text="Neither choice queues anything, and the original job and image are never changed.",
            style=theme_mod.MUTED_LABEL_STYLE,
            wraplength=420,
            justify=tk.LEFT,
        ).pack(anchor=tk.W, pady=(6, 0))
        ttk.Button(body, text="Cancel", command=self.destroy).pack(anchor=tk.E, pady=(8, 0))

    def _block(
        self, parent: tk.Misc, heading: str, choice: IterateChoice, key: str, button_text: str
    ) -> ttk.Button:
        frame = ttk.Frame(parent, style=theme_mod.SURFACE_FRAME_STYLE)
        frame.pack(fill=tk.X, pady=(0, 6))
        ttk.Label(frame, text=heading, style=theme_mod.STATUS_STRONG_LABEL_STYLE).pack(anchor=tk.W)
        ttk.Label(
            frame,
            text=choice.summary,
            style=theme_mod.MUTED_LABEL_STYLE,
            wraplength=420,
            justify=tk.LEFT,
        ).pack(anchor=tk.W)
        if not choice.supported:
            ttk.Label(
                frame,
                text=f"Not available: {choice.reason}",
                style=theme_mod.MUTED_LABEL_STYLE,
                wraplength=420,
                justify=tk.LEFT,
            ).pack(anchor=tk.W, pady=(2, 0))
        button = ttk.Button(
            frame,
            text=button_text,
            command=lambda: self._choose(key),
            state=tk.NORMAL if choice.supported else tk.DISABLED,
        )
        button.pack(anchor=tk.W, pady=(4, 0))
        return button

    def _choose(self, key: str) -> None:
        self.destroy()
        self._on_choose(key)


__all__ = ["CHOICE_PIPELINE", "CHOICE_REVIEW", "HistoryIterateDialog"]
