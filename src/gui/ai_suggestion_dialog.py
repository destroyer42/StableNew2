"""Read-only AI review dialog; only an explicit Accept callback can edit the authoring buffer."""

from __future__ import annotations

import tkinter as tk
from collections.abc import Callable
from functools import partial
from tkinter import ttk

from src.ai_assist.contracts import SuggestionKind
from src.gui.scrolling import enable_mousewheel
from src.gui.theme_v2 import apply_toplevel_theme, style_text_widget
from src.gui_v2.ai_suggestion_view import KIND_LABELS, SuggestionReview


class AiSuggestionDialog(tk.Toplevel):
    def __init__(
        self,
        master: tk.Misc,
        *,
        on_request: Callable[[SuggestionKind], None],
        on_accept: Callable[[], None],
        on_cancel: Callable[[], None],
        on_close: Callable[[], None],
        explanations: dict[SuggestionKind, str],
    ) -> None:
        super().__init__(master)
        self.title("AI suggestion review")
        self.resizable(True, True)
        apply_toplevel_theme(self)
        self._on_close = on_close
        self._closing = False
        self._requests: list[tuple[ttk.Button, SuggestionKind]] = []
        kinds = ttk.Frame(self)
        kinds.pack(fill="x", padx=8, pady=8)
        for kind, label in KIND_LABELS.items():
            button = ttk.Button(kinds, text=label, command=partial(on_request, kind))
            button.pack(side="left", padx=4)
            self._requests.append((button, kind))
        self._explanations = explanations
        self.status_var = tk.StringVar(
            value="Choose the assistance to request. Acceptance changes only the editing buffer."
        )
        ttk.Label(self, textvariable=self.status_var, wraplength=760, justify="left").pack(
            fill="x", padx=8
        )
        self.preview = tk.Text(self, height=22, width=100, wrap="word", undo=False)
        style_text_widget(self.preview)
        scrollbar = ttk.Scrollbar(self, orient="vertical", command=self.preview.yview)
        self.preview.configure(yscrollcommand=scrollbar.set, state="disabled")
        scrollbar.pack(side="right", fill="y")
        self.preview.pack(fill="both", expand=True, padx=8, pady=8)
        enable_mousewheel(self.preview)
        actions = ttk.Frame(self)
        actions.pack(fill="x", padx=8, pady=8)
        self.accept_button = ttk.Button(
            actions, text="Accept rewrite", command=on_accept, state="disabled"
        )
        self.accept_button.pack(side="right", padx=4)
        ttk.Button(actions, text="Reject / Close", command=self.close).pack(side="right", padx=4)
        self.cancel_button = ttk.Button(
            actions, text="Cancel Request", command=on_cancel, state="disabled"
        )
        self.cancel_button.pack(side="left")
        self.protocol("WM_DELETE_WINDOW", self.close)
        self._set_requests(False)
        unavailable = [f"{KIND_LABELS[k]}: {v}" for k, v in explanations.items() if v]
        self._text("\n".join(unavailable))

    def _set_requests(self, running: bool) -> None:
        for button, kind in self._requests:
            button.state(["disabled"] if running or self._explanations.get(kind) else ["!disabled"])

    def _text(self, value: str) -> None:
        self.preview.configure(state="normal")
        self.preview.delete("1.0", "end")
        self.preview.insert("1.0", value)
        self.preview.configure(state="disabled")

    def running(self, kind: SuggestionKind) -> None:
        self.status_var.set(f"{KIND_LABELS[kind]}: request running…")
        self._text("")
        self._set_requests(True)
        self.accept_button.state(["disabled"])
        self.cancel_button.state(["!disabled"])

    def show_review(self, model: SuggestionReview) -> None:
        self.status_var.set(f"{model.kind}: {model.status}")
        self._set_requests(False)
        self.cancel_button.state(["disabled"])
        self.accept_button.state(["!disabled"] if model.can_accept else ["disabled"])
        lines: list[str] = []
        if model.original or model.proposed:
            lines.extend(
                (
                    "Original authored material",
                    model.original,
                    "",
                    "Proposed material",
                    model.proposed,
                )
            )
        if model.changes:
            lines.extend(("", "Model change codes", ", ".join(model.changes)))
        p = model.compatibility
        if p is not None:
            lines.extend(
                (
                    "",
                    "Deterministic target compatibility (separate from model changes)",
                    p.summary,
                    "Effective positive",
                    p.adapted_positive,
                    f"Effective negative: {p.adapted_negative}",
                    f"Embeddings: {p.embeddings}",
                    f"LoRAs: {p.loras}",
                    *p.steps,
                    *p.notes,
                )
            )
        self._text("\n".join(lines))

    def clear_sensitive(self) -> None:
        self._text("")
        self.accept_button.state(["disabled"])
        self.status_var.set(
            "Content visibility or source context changed. Request a new suggestion."
        )

    def close(self) -> None:
        if self._closing:
            return
        self._closing = True
        self.clear_sensitive()
        self._on_close()
        self.destroy()
