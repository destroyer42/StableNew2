"""AI Assist Preview enablement dialog (owner decision D13): the one place an operator enables or revokes Preview.

The dialog states what Preview means before it offers the action. The only effect of Enable is the owner's
``enable_preview`` (an identity-only record for the exact installed model and runtime); nothing else changes.
"""

from __future__ import annotations

import tkinter as tk
from collections.abc import Callable
from tkinter import ttk
from typing import Any

from src.gui.theme_v2 import apply_toplevel_theme
from src.gui_v2.ai_suggestion_view import preview_status_text


class AiPreviewDialog(tk.Toplevel):
    def __init__(self, master: tk.Misc, *, owner: Any, on_change: Callable[[], None]) -> None:
        super().__init__(master)
        self.title("AI Assist Preview")
        self.resizable(False, False)
        apply_toplevel_theme(self)
        self._owner = owner
        self._on_change = on_change
        ttk.Label(self, text=owner.preview_meaning(), wraplength=520, justify="left").pack(
            fill="x", padx=12, pady=(12, 6)
        )
        self.state_var = tk.StringVar()
        ttk.Label(self, textvariable=self.state_var, wraplength=520, justify="left").pack(
            fill="x", padx=12, pady=6
        )
        self.result_var = tk.StringVar()
        ttk.Label(self, textvariable=self.result_var, wraplength=520, justify="left").pack(
            fill="x", padx=12
        )
        actions = ttk.Frame(self)
        actions.pack(fill="x", padx=12, pady=12)
        self.enable_button = ttk.Button(
            actions, text="Enable AI Assist Preview", command=self.enable, state="disabled"
        )
        self.enable_button.pack(side="left", padx=4)
        self.revoke_button = ttk.Button(
            actions, text="Revoke Preview", command=self.revoke, state="disabled"
        )
        self.revoke_button.pack(side="left", padx=4)
        ttk.Button(actions, text="Close", command=self.destroy).pack(side="right", padx=4)
        self.refresh()

    def refresh(self) -> None:
        state = self._owner.preview_state()
        self.state_var.set(preview_status_text(state))
        self.enable_button.state(["!disabled"] if state.can_enable else ["disabled"])
        self.revoke_button.state(["!disabled"] if state.enabled else ["disabled"])

    def enable(self) -> None:
        # Re-checked here, not only by the button state: the explicit click is the operator's confirmation.
        if not self._owner.preview_state().can_enable:
            self.refresh()
            return
        _ok, message = self._owner.enable_preview()
        self.result_var.set(message)
        self.refresh()
        self._on_change()

    def revoke(self) -> None:
        _ok, message = self._owner.revoke_preview()
        self.result_var.set(message)
        self.refresh()
        self._on_change()
