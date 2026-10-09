"""Keyboard-accessible collapsible section (PR-GUI-110). Presentation only; it never owns the values inside it.

The body widgets are ordinary children of ``body`` and keep their identity, variables and values whether the
section is collapsed or expanded; collapsing only unmaps the body. The operator's choice lives on the instance
for the session (no persistence authority).
"""

from __future__ import annotations

import tkinter as tk
from tkinter import ttk
from typing import Any

from src.gui.view_contracts.workspace_density_contract import disclosure_title


class DisclosureSection(ttk.Frame):
    def __init__(
        self,
        master: tk.Misc,
        *,
        title: str,
        expanded: bool = False,
        body_style: str = "Panel.TFrame",
        body_padding: Any = 8,
        **kwargs: Any,
    ) -> None:
        super().__init__(master, style="Panel.TFrame", **kwargs)
        self._title = title
        self._status = ""
        self._status_active = False
        self._expanded = bool(expanded)
        self.columnconfigure(0, weight=1)
        self.toggle_button = ttk.Button(
            self, text="", style="Disclosure.TButton", command=self.toggle, takefocus=True
        )
        self.toggle_button.grid(row=0, column=0, sticky="ew")
        # ttk.Button activates on Space; Return is the other expected disclosure key.
        self.toggle_button.bind("<Return>", self._on_return, add="+")
        self.body = ttk.Frame(self, style=body_style, padding=body_padding)
        self._sync()

    # -- public API -------------------------------------------------------------------------------------------------

    def toggle(self) -> None:
        self.set_expanded(not self._expanded)

    def set_expanded(self, expanded: bool) -> None:
        if bool(expanded) == self._expanded:
            return
        self._expanded = bool(expanded)
        self._sync()

    def is_expanded(self) -> bool:
        return self._expanded

    def set_status(self, text: str, *, active: bool = False) -> None:
        """Header hint shown while collapsed; ``active`` accents the header when hidden content is non-default."""

        text = str(text or "")
        if text == self._status and bool(active) == self._status_active:
            return
        self._status = text
        self._status_active = bool(active)
        self._sync()

    def header_text(self) -> str:
        return str(self.toggle_button.cget("text"))

    # -- internals --------------------------------------------------------------------------------------------------

    def _on_return(self, _event: tk.Event) -> str:
        self.toggle()
        return "break"

    def _sync(self) -> None:
        self.toggle_button.configure(
            text=disclosure_title(self._title, expanded=self._expanded, status=self._status),
            style="DisclosureActive.TButton" if self._status_active else "Disclosure.TButton",
        )
        if self._expanded:
            self.body.grid(row=1, column=0, sticky="nsew")
        else:
            self.body.grid_remove()


__all__ = ["DisclosureSection"]
