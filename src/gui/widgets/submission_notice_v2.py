"""Inline, non-modal submission feedback (PR-VID-UX-313). Presentation only.

Replaces blocking ``messagebox`` pop-ups after a Queue click:

* ``show_error`` keeps a clear message beside the form until it is dismissed or the next attempt, so a
  failure is never lost behind a dialog or swallowed;
* ``show_queued`` acknowledges an accepted job with an optional "View in queue" action and dismisses itself
  after a short delay.  The pending dismissal is cancelled when the widget is destroyed or replaced.

PR-GUI-400 adds the neutral / info / success / warning kinds and gives every kind a word, an accent edge bar and
an accessible role, so a status is never conveyed by color alone (``accessible_text`` is the text a screen reader
or a test reads).  Colors and words come from ``TOKENS.notices``.

It never submits, builds or reads anything; callers pass the message and the action.
"""

from __future__ import annotations

import tkinter as tk
from collections.abc import Callable
from tkinter import ttk
from typing import Any

from src.gui import design_system_v2 as design_system
from src.gui.ui_tokens import TOKENS, NoticeRole

QUEUED_NOTICE_MS = 8000
KIND_ERROR = "error"
KIND_QUEUED = "queued"
KIND_WARNING = "warning"
KIND_INFO = "info"
KIND_SUCCESS = "success"
KIND_NEUTRAL = "neutral"

# ``queued`` predates the semantic kinds; it is a success with its own word.
_ALIASES: dict[str, tuple[str, str]] = {KIND_QUEUED: (KIND_SUCCESS, "Queued")}
_BAR_WIDTH = 4
_BUTTON_ALLOWANCE = 180  # wrap budget kept for the two action buttons before they are measured
_MIN_WRAP = 240


def _resolve(kind: str) -> tuple[NoticeRole, str]:
    semantic, word = _ALIASES.get(kind, (kind, ""))
    role = TOKENS.notices.role(semantic)
    return role, word or role.label


class SubmissionNotice(ttk.Frame):
    def __init__(self, master: tk.Misc, **kwargs: Any) -> None:
        super().__init__(master, style="Panel.TFrame", **kwargs)
        self.kind = ""
        self.role = ""
        self.message_var = tk.StringVar(value="")
        self._dismiss_id: str | None = None
        self._on_view: Callable[[], None] | None = None
        self.columnconfigure(2, weight=1)
        self.bar = ttk.Frame(self, width=_BAR_WIDTH)
        self.prefix_label = ttk.Label(self, text="")
        self.label = ttk.Label(self, textvariable=self.message_var, justify="left", wraplength=640)
        self.label.grid(row=0, column=2, sticky="ew")
        self.view_button = ttk.Button(
            self, text="View in queue", style="Dark.TButton", command=self._view
        )
        self.dismiss_button = ttk.Button(
            self, text="Dismiss", style="Dark.TButton", command=self.clear
        )
        self.bind("<Configure>", self._on_configure, add="+")
        self.bind("<Destroy>", self._on_destroy, add="+")
        self._apply_style("neutral")
        self._set_idle()
        self.grid_remove()

    def _on_configure(self, _event: Any = None) -> None:
        try:
            reserved = _BAR_WIDTH + self.prefix_label.winfo_reqwidth() + _BUTTON_ALLOWANCE
            self.label.configure(wraplength=max(self.winfo_width() - reserved, _MIN_WRAP))
        except tk.TclError:
            pass

    # ------------------------------------------------------------------ public

    def show_error(self, message: str) -> None:
        self._show(KIND_ERROR, message, None)

    def show_warning(self, message: str) -> None:
        self._show(KIND_WARNING, message, None)

    def show_info(self, message: str) -> None:
        self._show(KIND_INFO, message, None)

    def show_neutral(self, message: str) -> None:
        self._show(KIND_NEUTRAL, message, None)

    def show_success(self, message: str) -> None:
        self._show(KIND_SUCCESS, message, None)
        self._schedule_dismiss()

    def show_queued(self, message: str, *, on_view_queue: Callable[[], None] | None = None) -> None:
        self._show(KIND_QUEUED, message, on_view_queue)
        self._schedule_dismiss()

    def accessible_text(self) -> str:
        """What assistive technology (or a test) should read: the kind's word, then the message."""

        if not self.kind:
            return ""
        _role, word = _resolve(self.kind)
        message = self.message_var.get()
        return f"{word}: {message}" if message else word

    def clear(self) -> None:
        self._cancel_dismiss()
        self.kind = ""
        self.role = ""
        self._on_view = None
        try:
            self.message_var.set("")
            self.prefix_label.configure(text="")
            self.view_button.grid_remove()
            self.dismiss_button.grid_remove()
            self._set_idle()
            self.grid_remove()
        except tk.TclError:
            pass

    # ------------------------------------------------------------------ internals

    def _set_idle(self) -> None:
        """Nothing painted and the pre-notice height: the tabs reserve this row before any message arrives."""

        self.bar.grid_remove()
        self.prefix_label.grid_remove()
        self.label.grid_configure(pady=0)
        self.configure(style="Panel.TFrame")

    def _show(self, kind: str, message: str, on_view: Callable[[], None] | None) -> None:
        self._cancel_dismiss()
        role, word = _resolve(kind)
        self.kind = kind
        self.role = role.a11y_role
        self._on_view = on_view
        self.message_var.set(str(message or "").strip())
        self.prefix_label.configure(text=word)
        self._apply_style(role.kind)
        self.bar.grid(row=0, column=0, sticky="ns")
        self.prefix_label.grid(
            row=0,
            column=1,
            sticky="nw",
            padx=(TOKENS.spacing.md, TOKENS.spacing.sm),
            pady=TOKENS.spacing.sm,
        )
        self.label.grid_configure(pady=TOKENS.spacing.sm)
        if on_view is not None:
            self.view_button.grid(
                row=0, column=3, padx=(TOKENS.spacing.md, 0), pady=TOKENS.spacing.sm
            )
        else:
            self.view_button.grid_remove()
        self.dismiss_button.grid(
            row=0, column=4, padx=(TOKENS.spacing.sm, TOKENS.spacing.sm), pady=TOKENS.spacing.sm
        )
        self.grid()

    def _apply_style(self, semantic_kind: str) -> None:
        names = design_system.notice_style_names(semantic_kind)
        self.configure(style=names.frame)
        self.bar.configure(style=names.bar)
        self.prefix_label.configure(style=names.prefix)
        self.label.configure(style=names.message)

    def _schedule_dismiss(self) -> None:
        try:
            self._dismiss_id = self.after(QUEUED_NOTICE_MS, self.clear)
        except tk.TclError:
            self._dismiss_id = None

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


__all__ = [
    "KIND_ERROR",
    "KIND_INFO",
    "KIND_NEUTRAL",
    "KIND_QUEUED",
    "KIND_SUCCESS",
    "KIND_WARNING",
    "QUEUED_NOTICE_MS",
    "SubmissionNotice",
]
