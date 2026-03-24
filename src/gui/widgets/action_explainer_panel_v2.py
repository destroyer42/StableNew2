from __future__ import annotations

import tkinter as tk
from dataclasses import dataclass
from tkinter import ttk

from src.gui.theme_v2 import BODY_LABEL_STYLE, HEADING_LABEL_STYLE, MUTED_LABEL_STYLE


@dataclass(frozen=True, slots=True)
class ActionExplainerContent:
    title: str
    summary: str
    bullets: tuple[str, ...]

    def to_detail_text(self) -> str:
        return "\n".join(f"- {bullet}" for bullet in self.bullets)


class ActionExplainerPanel(ttk.Frame):
    """Always-visible inline guidance for high-risk actions and workflow choices."""

    def __init__(
        self,
        master: tk.Misc,
        *,
        content: ActionExplainerContent,
        wraplength: int = 880,
        **kwargs: object,
    ) -> None:
        super().__init__(master, style="Panel.TFrame", padding=8, **kwargs)
        self.content = content

        self.columnconfigure(0, weight=1)

        self.title_label = ttk.Label(
            self,
            text=content.title,
            style=HEADING_LABEL_STYLE,
        )
        self.title_label.grid(row=0, column=0, sticky="w")

        self.summary_label = ttk.Label(
            self,
            text=content.summary,
            style=BODY_LABEL_STYLE,
            justify="left",
            wraplength=wraplength,
        )
        self.summary_label.grid(row=1, column=0, sticky="ew", pady=(6, 0))

        self.details_label = ttk.Label(
            self,
            text=content.to_detail_text(),
            style=MUTED_LABEL_STYLE,
            justify="left",
            wraplength=wraplength,
        )
        self.details_label.grid(row=2, column=0, sticky="ew", pady=(6, 0))