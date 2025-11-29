"""Scrolling helpers for V2 GUI widgets."""

from __future__ import annotations

import tkinter as tk
from tkinter import ttk
from typing import Tuple


def enable_mousewheel(widget: tk.Widget) -> None:
    """Bind the platform-appropriate mousewheel events to scroll the widget."""

    def _on_mousewheel(event: tk.Event) -> None:
        delta = getattr(event, "delta", 0)
        if delta == 0 and getattr(event, "num", None) in (4, 5):
            delta = 120 if event.num == 4 else -120
        step = int(-1 * (delta / 120))
        try:
            widget.yview_scroll(step, "units")
        except Exception:
            pass

    def _bind(_event: tk.Event) -> None:
        widget.bind_all("<MouseWheel>", _on_mousewheel, add="+")
        widget.bind_all("<Button-4>", _on_mousewheel, add="+")
        widget.bind_all("<Button-5>", _on_mousewheel, add="+")

    def _unbind(_event: tk.Event) -> None:
        widget.unbind_all("<MouseWheel>")
        widget.unbind_all("<Button-4>")
        widget.unbind_all("<Button-5>")

    widget.bind("<Enter>", _bind, add="+")
    widget.bind("<Leave>", _unbind, add="+")


def make_scrollable(parent: tk.Widget, *, orient: str = "vertical") -> Tuple[ttk.Frame, tk.Widget]:
    """Wrap a frame in a scrollable canvas and return (container, inner frame)."""
    container = ttk.Frame(parent)
    canvas = tk.Canvas(container, highlightthickness=0)
    canvas.grid(row=0, column=0, sticky="nsew")
    scrollbar = ttk.Scrollbar(container, orient=orient, command=canvas.yview)
    scrollbar.grid(row=0, column=1, sticky="ns")
    canvas.configure(yscrollcommand=scrollbar.set)

    inner = ttk.Frame(canvas)
    window = canvas.create_window((0, 0), window=inner, anchor="nw")

    container.rowconfigure(0, weight=1)
    container.columnconfigure(0, weight=1)

    def _configure_canvas(event: tk.Event) -> None:
        canvas.configure(scrollregion=canvas.bbox("all"))
    inner.bind("<Configure>", _configure_canvas)

    def _resize_canvas(event: tk.Event) -> None:
        canvas.itemconfigure(window, width=event.width)
    canvas.bind("<Configure>", _resize_canvas)

    return container, inner
