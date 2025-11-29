"""Tooltips for V2 GUI widgets."""

from __future__ import annotations

import tkinter as tk
from tkinter import ttk


class Tooltip:
    """Show a small text popup for a widget on hover."""

    def __init__(self, widget: tk.Widget, text: str, *, delay_ms: int = 500) -> None:
        self.widget = widget
        self.text = text
        self.delay_ms = delay_ms
        self._window: tk.Toplevel | None = None
        self._after_id: str | None = None

        widget.bind("<Enter>", self._schedule, add="+")
        widget.bind("<Leave>", self._hide, add="+")
        widget.bind("<ButtonPress>", self._hide, add="+")

    def _schedule(self, _event: tk.Event | None) -> None:
        if self._after_id:
            self.widget.after_cancel(self._after_id)
        self._after_id = self.widget.after(self.delay_ms, self._show)

    def _show(self) -> None:
        if self._window or not self.widget.winfo_ismapped():
            return
        self._window = tw = tk.Toplevel(self.widget)
        tw.withdraw()
        tw.overrideredirect(True)
        tw.attributes("-topmost", True)
        label = ttk.Label(tw, text=self.text, background="#222", foreground="#fff", relief="solid", borderwidth=1, padding=(4, 2))
        label.pack()
        x = self.widget.winfo_rootx() + 10
        y = self.widget.winfo_rooty() + self.widget.winfo_height() + 2
        tw.geometry(f"+{x}+{y}")
        tw.deiconify()

    def _hide(self, _event: tk.Event | None = None) -> None:
        if self._after_id:
            self.widget.after_cancel(self._after_id)
            self._after_id = None
        if self._window:
            self._window.destroy()
            self._window = None


def attach_tooltip(widget: tk.Widget, text: str, *, delay_ms: int = 500) -> Tooltip:
    """Attach a tooltip helper to a widget."""
    return Tooltip(widget, text, delay_ms=delay_ms)
