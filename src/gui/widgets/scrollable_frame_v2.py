from __future__ import annotations

import tkinter as tk
from tkinter import ttk

from src.gui import theme_v2


class ScrollableFrame(ttk.Frame):
    """Reusable scrollable frame for V2 panels."""

    def __init__(self, master: tk.Misc, *, style: str | None = None, **kwargs) -> None:
        super().__init__(master, style=style, **kwargs)

        self._canvas = tk.Canvas(
            self,
            highlightthickness=0,
            borderwidth=0,
            bg=theme_v2.BACKGROUND_DARK,
        )
        self._canvas.grid(row=0, column=0, sticky="nsew")

        self._vsb = ttk.Scrollbar(self, orient="vertical", command=self._canvas.yview)
        self._vsb.grid(row=0, column=1, sticky="ns")
        self._canvas.configure(yscrollcommand=self._vsb.set)

        self.inner = ttk.Frame(self._canvas, style="Panel.TFrame")
        self._inner_window = self._canvas.create_window((0, 0), window=self.inner, anchor="nw")

        self.rowconfigure(0, weight=1)
        self.columnconfigure(0, weight=1)

        self.inner.bind("<Configure>", self._on_inner_configure)
        self._canvas.bind("<Configure>", self._on_canvas_configure)
        self._bind_mousewheel_events()

    def _on_inner_configure(self, event: tk.Event) -> None:
        self._canvas.configure(scrollregion=self._canvas.bbox("all"))

    def _on_canvas_configure(self, event: tk.Event) -> None:
        canvas_width = event.width
        self._canvas.itemconfigure(self._inner_window, width=canvas_width)

    def _bind_mousewheel_events(self) -> None:
        self._capture_wheel = False
        for widget in (self, self._canvas, self.inner):
            try:
                widget.bind("<Enter>", lambda _e: setattr(self, "_capture_wheel", True))
                widget.bind("<Leave>", lambda _e: setattr(self, "_capture_wheel", False))
                widget.bind_all("<MouseWheel>", self._on_mousewheel, add="+")
            except Exception:
                pass

    def _on_mousewheel(self, event: tk.Event) -> None:
        # Avoid double-scrolling when hovering over native dropdown/list widgets
        widget_class = str(getattr(event.widget, "winfo_class", lambda: "")()).lower()
        if "combobox" in widget_class or "listbox" in widget_class:
            return
        if not getattr(self, "_capture_wheel", False):
            return
        delta = int(-1 * (event.delta / 120))
        self._canvas.yview_scroll(delta, "units")


__all__ = ["ScrollableFrame"]
