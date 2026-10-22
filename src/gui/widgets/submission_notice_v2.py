"""Inline, non-modal submission feedback (PR-VID-UX-313). Presentation only.

Replaces blocking ``messagebox`` pop-ups after a Queue click:

* ``show_error`` keeps a clear message beside the form until it is dismissed or the next attempt, so a
  failure is never lost behind a dialog or swallowed;
* ``show_queued`` acknowledges an accepted job with an optional "View in queue" action and dismisses itself
  after a short delay.  The pending dismissal is cancelled when the widget is destroyed or replaced.

It never submits, builds or reads anything; callers pass the message and the action.
"""

from __future__ import annotations

import tkinter as tk
from collections.abc import Callable
from tkinter import ttk
from typing import Any

from src.gui import theme_v2 as theme_mod

QUEUED_NOTICE_MS = 8000
KIND_ERROR = "error"
KIND_QUEUED = "queued"


class SubmissionNotice(ttk.Frame):
    def __init__(self, master: tk.Misc, **kwargs: Any) -> None:
        super().__init__(master, style="Panel.TFrame", **kwargs)
        self.kind = ""
        self.message_var = tk.StringVar(value="")
        self._dismiss_id: str | None = None
        self._on_view: Callable[[], None] | None = None
        self.columnconfigure(0, weight=1)
        self.label = ttk.Label(
            self, textvariable=self.message_var, style="Dark.TLabel", justify="left", wraplength=640
        )
        self.label.grid(row=0, column=0, sticky="ew")
        self.view_button = ttk.Button(
            self, text="View in queue", style="Dark.TButton", command=self._view
        )
        self.dismiss_button = ttk.Button(
            self, text="Dismiss", style="Dark.TButton", command=self.clear
        )
        self.bind("<Configure>", self._on_configure, add="+")
        self.bind("<Destroy>", self._on_destroy, add="+")
        self.grid_remove()

    def _on_configure(self, _event: Any = None) -> None:
        try:
            width = max(self.winfo_width() - 180, 240)
            self.label.configure(wraplength=width)
        except tk.TclError:
            pass

    # ------------------------------------------------------------------ public

    def show_error(self, message: str) -> None:
        self._show(KIND_ERROR, message, None)

    def show_queued(self, message: str, *, on_view_queue: Callable[[], None] | None = None) -> None:
        self._show(KIND_QUEUED, message, on_view_queue)
        try:
            self._dismiss_id = self.after(QUEUED_NOTICE_MS, self.clear)
        except tk.TclError:
            self._dismiss_id = None

    def clear(self) -> None:
        self._cancel_dismiss()
        self.kind = ""
        self._on_view = None
        try:
            self.message_var.set("")
            self.view_button.grid_remove()
            self.dismiss_button.grid_remove()
            self.grid_remove()
        except tk.TclError:
            pass

    # ------------------------------------------------------------------ internals

    def _show(self, kind: str, message: str, on_view: Callable[[], None] | None) -> None:
        self._cancel_dismiss()
        self.kind = kind
        self._on_view = on_view
        self.message_var.set(str(message or "").strip())
        self.label.configure(
            style=theme_mod.SUBMISSION_ERROR_LABEL_STYLE if kind == KIND_ERROR else "Dark.TLabel"
        )
        if on_view is not None:
            self.view_button.grid(row=0, column=1, padx=(8, 0))
        else:
            self.view_button.grid_remove()
        self.dismiss_button.grid(row=0, column=2, padx=(6, 0))
        self.grid()

    def _view(self) -> None:
        action = self._on_view
        self.clear()
        if action is not None:
            action()

    def _cancel_dismiss(self) -> None:
        pending, self._dismiss_id = self._dismiss_id, None
        if pending is not None:
            try:
                self.after_cancel(pending)
            except tk.TclError:
                pass

    def _on_destroy(self, event: Any = None) -> None:
        if event is None or event.widget is self:
            self._cancel_dismiss()


__all__ = ["KIND_ERROR", "KIND_QUEUED", "QUEUED_NOTICE_MS", "SubmissionNotice"]
