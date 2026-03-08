"""Multi-line prompt field widget with scrollbar and StringVar sync (PR-GUI-LAYOUT-002).

This widget provides a reusable 3-line Text widget with vertical scrollbar that syncs
bidirectionally with a tk.StringVar for integration with existing stage card code.
"""

from __future__ import annotations

import tkinter as tk
from collections.abc import Callable
from tkinter import ttk
from typing import Any

from src.gui.theme_v2 import BACKGROUND_ELEVATED, SURFACE_FRAME_STYLE, TEXT_PRIMARY


class MultiLinePromptField(ttk.Frame):
    """A multi-line text field with scrollbar that syncs with a StringVar.

    Features:
    - 3 lines tall by default (configurable)
    - Vertical scrollbar (appears when needed)
    - Bidirectional sync with StringVar
    - Dark mode themed
    - Word wrapping enabled

    Args:
        parent: Parent widget
        textvariable: StringVar to sync with
        height: Number of visible lines (default 3)
        on_change: Optional callback when text changes
        style: Frame style (default SURFACE_FRAME_STYLE)
    """

    def __init__(
        self,
        parent: tk.Widget,
        *,
        textvariable: tk.StringVar,
        height: int = 3,
        on_change: Callable[[], None] | None = None,
        style: str = SURFACE_FRAME_STYLE,
    ) -> None:
        super().__init__(parent, style=style)

        self.textvariable = textvariable
        self._on_change = on_change
        self._syncing = False  # Prevent infinite loop during sync

        # Configure grid
        self.columnconfigure(0, weight=1)
        self.rowconfigure(0, weight=1)

        # Text widget
        self.text = tk.Text(
            self,
            height=height,
            wrap="word",
            bg=BACKGROUND_ELEVATED,
            fg=TEXT_PRIMARY,
            relief="solid",
            borderwidth=1,
            highlightthickness=0,
            font=("Segoe UI", 9),
            insertbackground=TEXT_PRIMARY,  # Cursor color
        )
        self.text.grid(row=0, column=0, sticky="nsew")

        # Scrollbar
        self.scrollbar = ttk.Scrollbar(
            self,
            orient="vertical",
            command=self.text.yview,
        )
        self.scrollbar.grid(row=0, column=1, sticky="ns")
        self.text.configure(yscrollcommand=self.scrollbar.set)

        # Sync: StringVar → Text widget
        self._var_trace_id = self.textvariable.trace_add(
            "write",
            self._on_var_changed,
        )

        # Sync: Text widget → StringVar
        self.text.bind("<KeyRelease>", self._on_text_changed)
        self.text.bind("<<Paste>>", self._on_text_changed)
        self.text.bind("<<Cut>>", self._on_text_changed)

        # Initialize text from variable
        self._sync_var_to_text()

    def _on_var_changed(self, *_args: object) -> None:
        """Handle StringVar changes - update Text widget."""
        if self._syncing:
            return
        self._sync_var_to_text()

    def _on_text_changed(self, _event: object = None) -> None:
        """Handle Text widget changes - update StringVar."""
        if self._syncing:
            return
        self._sync_text_to_var()
        if self._on_change:
            self._on_change()

    def _sync_var_to_text(self) -> None:
        """Update Text widget content from StringVar."""
        self._syncing = True
        try:
            current_text = self.text.get("1.0", "end-1c")
            new_text = self.textvariable.get()
            if current_text != new_text:
                # Preserve cursor position if possible
                try:
                    cursor_pos = self.text.index(tk.INSERT)
                except tk.TclError:
                    cursor_pos = "1.0"

                self.text.delete("1.0", tk.END)
                self.text.insert("1.0", new_text)

                # Restore cursor if within bounds
                try:
                    self.text.mark_set(tk.INSERT, cursor_pos)
                except tk.TclError:
                    self.text.mark_set(tk.INSERT, "end")
        finally:
            self._syncing = False

    def _sync_text_to_var(self) -> None:
        """Update StringVar from Text widget content."""
        self._syncing = True
        try:
            text_content = self.text.get("1.0", "end-1c")
            current_var = self.textvariable.get()
            if text_content != current_var:
                self.textvariable.set(text_content)
        finally:
            self._syncing = False

    def get(self) -> str:
        """Get current text content."""
        return self.text.get("1.0", "end-1c")

    def set(self, value: str) -> None:
        """Set text content (updates both widget and variable)."""
        self.textvariable.set(value)

    def clear(self) -> None:
        """Clear text content."""
        self.set("")

    def configure_text(self, **kwargs: Any) -> None:
        """Configure the underlying Text widget."""
        self.text.configure(**kwargs)

    def disable(self) -> None:
        """Disable text editing."""
        self.text.configure(state="disabled")

    def enable(self) -> None:
        """Enable text editing."""
        self.text.configure(state="normal")

    def destroy(self) -> None:
        """Clean up trace before destroying."""
        try:
            self.textvariable.trace_remove("write", self._var_trace_id)
        except Exception:
            pass
        super().destroy()


__all__ = ["MultiLinePromptField"]
