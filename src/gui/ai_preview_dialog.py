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

from src.ai_assist.remote_preview import MODEL_LABELS, REMOTE_PREVIEW_LABEL, RemoteApproval
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
        self._remote_choices: dict[str, RemoteApproval] = {}
        remote = ttk.LabelFrame(self, text=REMOTE_PREVIEW_LABEL)
        remote.pack(fill="x", padx=12, pady=(0, 10))
        ttk.Label(remote, text="Remote Ollama model").pack(anchor="w", padx=6, pady=(4, 0))
        self.remote_model = tk.StringVar()
        self.remote_box = ttk.Combobox(remote, textvariable=self.remote_model, state="disabled")
        self.remote_box.pack(fill="x", padx=6)
        self.remote_box.bind("<<ComboboxSelected>>", self._select_remote)
        self.remote_status = tk.StringVar()
        ttk.Label(remote, textvariable=self.remote_status, wraplength=520, justify="left").pack(
            fill="x", padx=6, pady=4
        )
        self.refresh()

    def refresh_remote(self, *, request_pending: bool = False) -> None:
        get_status = getattr(self._owner, "remote_preview", None)
        if get_status is None:
            return
        settings, status = get_status()
        choices = {MODEL_LABELS[item.model]: item for item in settings.approvals}
        if choices != self._remote_choices:
            self._remote_choices = choices
            self.remote_box.configure(values=tuple(choices))
        self.remote_model.set(MODEL_LABELS.get(settings.active_model or "", ""))
        selectable = (
            choices
            and settings.preferred
            and not request_pending
            and not self._owner.busy
            and not self._owner.closed
        )
        self.remote_box.state(["!disabled", "readonly"] if selectable else ["disabled"])
        self.remote_status.set(status)

    def _select_remote(self, _event: object) -> None:
        approval = self._remote_choices.get(self.remote_model.get())
        if approval is not None:
            _ok, message = self._owner.select_remote_model(approval)
            self.result_var.set(message)
        self.refresh_remote()
        self._on_change()

    def refresh(self) -> None:
        self._refresh_models()
        self.refresh_remote()
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
