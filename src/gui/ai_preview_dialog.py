"""AI Assist Preview enablement dialog (owner decision D13): the one place an operator enables or revokes Preview.

The dialog states what Preview means before it offers the action. The only effect of Enable is the owner's
``enable_preview`` (an identity-only record for the exact installed model and runtime); nothing else changes.

It also holds the model selector (owner decision D20): a dropdown of the models that are imported and verified, by display
name. Choosing one calls the owner's ``select_model`` (one synchronous activation, refused while a request runs or when the
egress attestation does not cover the model's runtime build). It never enables Preview itself.
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
        picker = ttk.Frame(self)
        picker.pack(fill="x", padx=12, pady=(6, 0))
        ttk.Label(picker, text="Model:").pack(side="left")
        self.model_var = tk.StringVar()
        self.model_box = ttk.Combobox(
            picker, textvariable=self.model_var, state="readonly", width=58
        )
        self.model_box.pack(side="left", padx=6, fill="x", expand=True)
        self.model_box.bind("<<ComboboxSelected>>", self._model_selected)
        self.model_detail_var = tk.StringVar()
        ttk.Label(self, textvariable=self.model_detail_var, wraplength=520, justify="left").pack(
            fill="x", padx=12, pady=(2, 0)
        )
        self._choices: dict[str, Any] = {}
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
        self._refresh_models()
        state = self._owner.preview_state()
        self.state_var.set(preview_status_text(state))
        self.enable_button.state(["!disabled"] if state.can_enable else ["disabled"])
        self.revoke_button.state(["!disabled"] if state.enabled else ["disabled"])

    def _refresh_models(self) -> None:
        choices = tuple(self._owner.model_choices())
        self._choices = {choice.display_name: choice for choice in choices}
        self.model_box.configure(values=list(self._choices))
        active = next((choice for choice in choices if choice.active), None)
        self.model_var.set(active.display_name if active is not None else "")
        busy = bool(getattr(self._owner, "busy", False))
        self.model_box.state(["!disabled", "readonly"] if choices and not busy else ["disabled"])
        if not choices:
            self.model_detail_var.set(
                "No model is imported and verified here with a compatible runtime build."
            )
        elif busy:
            self.model_detail_var.set("A request is running; models cannot be switched now.")
        elif active is not None:
            self.model_detail_var.set(self._detail(active))
        else:
            self.model_detail_var.set("Choose a model to make it the active one.")

    @staticmethod
    def _detail(choice: Any) -> str:
        preview = {
            "preview": "AI Assist Preview is enabled for this model.",
            "qualified": "This model is qualified.",
        }.get(choice.trust, "AI Assist Preview is not enabled for this model.")
        attested = (
            "" if choice.attested else " The outbound restriction is not attested for this runtime."
        )
        return f"Runtime {choice.build_id}. {preview}{attested}"

    def _model_selected(self, _event: object = None) -> None:
        choice = self._choices.get(self.model_var.get())
        if choice is None:
            self.refresh()
            return
        _ok, message = self._owner.select_model(choice.model_id)
        self.result_var.set(message)
        self.refresh()
        self._on_change()

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
