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
        self._closed = False
        # PR-GUI-110: a combobox too narrow to show its value shows the whole value here (hover or focus).
        self.value_provider: Callable[[], str] | None = None

        widget.bind("<Enter>", self._schedule, add="+")
        widget.bind("<Leave>", self._hide, add="+")
        widget.bind("<ButtonPress>", self._hide, add="+")
        widget.bind("<Destroy>", self._on_widget_destroyed, add="+")

    def _on_widget_destroyed(self, event: tk.Event | None) -> None:
        """The widget is going away: cancel the pending timer and drop the popup, then ignore every later call."""
        if event is not None and getattr(event, "widget", None) is not self.widget:
            return  # a descendant's <Destroy> is delivered to this binding too
        self._closed = True
        self._hide()

    def _cancel_timer(self) -> None:
        after_id, self._after_id = self._after_id, None
        if after_id:
            try:
                self.widget.after_cancel(after_id)
            except tk.TclError:
                pass  # the interpreter or widget is already gone; the timer went with it

    def _schedule(self, _event: tk.Event | None) -> None:
        if self._closed:
            return
        self._cancel_timer()
        try:
            self._after_id = self.widget.after(self.delay_ms, self._fire)
        except tk.TclError:
            self._after_id = None

    def _fire(self) -> None:
        self._after_id = None
        self._show()

    def _schedule_for_focus(self, event: tk.Event | None) -> None:
        """Keyboard focus shows a tooltip only when the full value would add information (it is truncated)."""
        if self.value_provider is None:
            return
        value = str(self.value_provider() or "")
        if value and value_is_truncated(self.widget, value):
            self._schedule(event)

    def _display_text(self) -> str:
        text = self.text
        if self.value_provider is not None:
            value = str(self.value_provider() or "")
            if value and value_is_truncated(self.widget, value):
                text = f"{value}\n\n{text}" if text else value
        return text

    def _show(self) -> None:
        if self._closed:
            return
        try:
            if not self.widget.winfo_exists():
                return
            self.widget.update_idletasks()
        except tk.TclError:
            return
        if self._window:
            return
        text = self._display_text()
        if not text:
            return
        try:
            self._build_window(text)
        except tk.TclError:
            self._discard_window()  # the widget was destroyed while the popup was being built

    def _build_window(self, text: str) -> None:
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

    def _discard_window(self) -> None:
        window, self._window = self._window, None
        if window is not None:
            try:
                window.destroy()
            except tk.TclError:
                pass  # already destroyed with its parent

    def _hide(self, _event: tk.Event | None = None) -> None:
        """Idempotent: cancel the pending timer and drop the popup, whatever state the widget is in."""
        self._cancel_timer()
        self._discard_window()

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
        widget.bind("<FocusIn>", tooltip._schedule_for_focus, add="+")
        widget.bind("<FocusOut>", tooltip._hide, add="+")
        widget.bind("<<ComboboxSelected>>", tooltip._hide, add="+")
        widget._full_value_tooltip = True  # type: ignore[attr-defined]
        newly += 1
    return newly
