"""Tooltips for V2 GUI widgets."""

from __future__ import annotations

import tkinter as tk
from collections.abc import Callable
from tkinter import font as tkfont
from tkinter import ttk


class Tooltip:
    """Show a small text popup for a widget on hover."""

    def __init__(self, widget: tk.Widget, text: str, *, delay_ms: int = 500) -> None:
        self.widget = widget
        self.text = text
        self.delay_ms = delay_ms
        self._window: tk.Toplevel | None = None
        self._after_id: str | None = None
        # PR-GUI-110: a combobox too narrow to show its value shows the whole value here (hover or focus).
        self.value_provider: Callable[[], str] | None = None

        widget.bind("<Enter>", self._schedule, add="+")
        widget.bind("<Leave>", self._hide, add="+")
        widget.bind("<ButtonPress>", self._hide, add="+")

    def _schedule(self, _event: tk.Event | None) -> None:
        if self._after_id:
            self.widget.after_cancel(self._after_id)
        self._after_id = self.widget.after(self.delay_ms, self._show)

    def _display_text(self) -> str:
        text = self.text
        if self.value_provider is not None:
            value = str(self.value_provider() or "")
            if value and value_is_truncated(self.widget, value):
                text = f"{value}\n\n{text}" if text else value
        return text

    def _show(self) -> None:
        self.widget.update_idletasks()
        if self._window:
            return
        text = self._display_text()
        if not text:
            return
        self._window = tw = tk.Toplevel(self.widget)
        tw.withdraw()
        tw.overrideredirect(True)
        tw.attributes("-topmost", True)
        label = ttk.Label(
            tw,
            text=text,
            background="#222",
            foreground="#fff",
            relief="solid",
            borderwidth=1,
            padding=(4, 2),
        )
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

    def show(self) -> None:
        """Public method invoked by tests to show the tooltip."""
        self._show()

    def hide(self) -> None:
        """Public method invoked by tests to hide the tooltip."""
        self._hide()


def attach_tooltip(widget: tk.Widget, text: str, *, delay_ms: int = 500) -> Tooltip:
    """Attach a tooltip helper to a widget."""
    tooltip = Tooltip(widget, text, delay_ms=delay_ms)
    try:
        widget.tooltip = tooltip
    except Exception:
        pass
    return tooltip


def value_is_truncated(widget: tk.Widget, value: str, *, padding: int = 28) -> bool:
    """Whether ``value`` is wider than ``widget`` can display (arrow/border ``padding`` reserved)."""
    try:
        font = tkfont.Font(root=widget, font=str(widget.cget("font")) or "TkTextFont")
    except tk.TclError:
        font = tkfont.nametofont("TkTextFont")
    return int(font.measure(value)) + padding > int(widget.winfo_width())


def install_full_value_tooltips(root_widget: tk.Misc) -> int:
    """Make every ``ttk.Combobox`` under ``root_widget`` show its full value when it cannot fit.

    Idempotent and presentation-only: it reads the widget's current value and never changes it. Returns the
    number of comboboxes newly covered.
    """
    newly = 0
    stack: list[tk.Misc] = [root_widget]
    while stack:
        widget = stack.pop()
        stack.extend(widget.winfo_children())
        if not isinstance(widget, ttk.Combobox) or getattr(widget, "_full_value_tooltip", False):
            continue
        tooltip = getattr(widget, "tooltip", None)
        if not isinstance(tooltip, Tooltip):
            tooltip = Tooltip(widget, "")
            try:
                setattr(widget, "tooltip", tooltip)  # noqa: B010 - same attribute attach_tooltip sets
            except Exception:
                pass
        tooltip.value_provider = widget.get
        widget.bind("<FocusIn>", tooltip._schedule, add="+")
        widget.bind("<FocusOut>", tooltip._hide, add="+")
        widget.bind("<<ComboboxSelected>>", tooltip._hide, add="+")
        widget._full_value_tooltip = True  # type: ignore[attr-defined]
        newly += 1
    return newly
