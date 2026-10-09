from __future__ import annotations

import tkinter as tk
from dataclasses import dataclass
from tkinter import ttk
from typing import Any

from src.gui.theme_v2 import BODY_LABEL_STYLE, HEADING_LABEL_STYLE, MUTED_LABEL_STYLE
from src.gui.widgets.responsive_wrap_v2 import bind_wraplength


@dataclass(frozen=True, slots=True)
class ActionExplainerContent:
    title: str
    summary: str
    bullets: tuple[str, ...]

    def to_detail_text(self) -> str:
        return "\n".join(f"- {bullet}" for bullet in self.bullets)


class ActionExplainerPanel(ttk.Frame):
    """Inline guidance for high-risk actions and workflow choices."""

    def __init__(
        self,
        master: tk.Misc,
        *,
        content: ActionExplainerContent,
        app_state: Any | None = None,
        expanded: bool = False,
        wraplength: int = 880,
        summary_when_collapsed: bool = False,
        **kwargs: object,
    ) -> None:
        """``summary_when_collapsed`` is for content whose summary carries a safety-critical notice that must
        stay visible; ordinary workflow guidance collapses to a single header row (PR-GUI-110)."""

        super().__init__(master, style="Panel.TFrame", padding=(8, 4), **kwargs)
        self._summary_when_collapsed = bool(summary_when_collapsed)
        self.content = content
        self._app_state = app_state
        self._manual_expanded = bool(expanded)
        self._help_mode_enabled = bool(getattr(app_state, "help_mode_enabled", False))

        self.columnconfigure(0, weight=1)

        header = ttk.Frame(self, style="Panel.TFrame")
        header.grid(row=0, column=0, sticky="ew")
        header.columnconfigure(0, weight=1)

        self.title_label = ttk.Label(
            header,
            text=content.title,
            style=HEADING_LABEL_STYLE,
        )
        self.title_label.grid(row=0, column=0, sticky="w")

        self.toggle_button = ttk.Button(
            header,
            text="",
            style="Dark.TButton",
            command=self.toggle_details,
            width=14,
        )
        self.toggle_button.grid(row=0, column=1, sticky="e", padx=(8, 0))

        self.summary_label = ttk.Label(
            self,
            text=content.summary,
            style=BODY_LABEL_STYLE,
            justify="left",
            wraplength=wraplength,
        )
        self.summary_label.grid(row=1, column=0, sticky="ew", pady=(6, 0))
        self.toggle_button.bind("<Return>", self._on_return_key, add="+")

        self.details_frame = ttk.Frame(self, style="Panel.TFrame")
        self.details_label = ttk.Label(
            self.details_frame,
            text=content.to_detail_text(),
            style=MUTED_LABEL_STYLE,
            justify="left",
            wraplength=wraplength,
        )
        self.details_label.grid(row=0, column=0, sticky="ew")
        # The configured wraplength is the maximum; narrower windows wrap to the panel's real width.
        bind_wraplength(self.summary_label, maximum=wraplength)
        bind_wraplength(self.details_label, maximum=wraplength)

        if self._app_state is not None and hasattr(self._app_state, "subscribe"):
            try:
                self._app_state.subscribe("help_mode", self._on_help_mode_changed)
            except Exception:
                pass
        self._sync_details()

    def _on_return_key(self, _event: tk.Event) -> str:
        self.toggle_button.invoke()
        return "break"

    def toggle_details(self) -> None:
        if self._help_mode_enabled:
            return
        self._manual_expanded = not self._manual_expanded
        self._sync_details()

    def is_expanded(self) -> bool:
        return bool(self._help_mode_enabled or self._manual_expanded)

    def destroy(self) -> None:
        if self._app_state is not None and hasattr(self._app_state, "unsubscribe"):
            try:
                self._app_state.unsubscribe("help_mode", self._on_help_mode_changed)
            except Exception:
                pass
        super().destroy()

    def _on_help_mode_changed(self) -> None:
        self._help_mode_enabled = bool(getattr(self._app_state, "help_mode_enabled", False))
        self._sync_details()

    def _sync_details(self) -> None:
        expanded = self.is_expanded()
        if expanded or self._summary_when_collapsed:
            self.summary_label.grid(row=1, column=0, sticky="ew", pady=(6, 0))
        else:
            self.summary_label.grid_remove()
        if expanded:
            self.details_frame.grid(row=2, column=0, sticky="ew", pady=(6, 0))
            if self._help_mode_enabled:
                self.toggle_button.configure(text="Help Mode On", state="disabled")
            else:
                self.toggle_button.configure(text="Hide Guidance", state="normal")
        else:
            self.details_frame.grid_remove()
            self.toggle_button.configure(text="Show Guidance", state="normal")
