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
        """Bind mouse wheel to scroll column under cursor.
        
        PR-GUI-D: Uses enter/leave on the canvas to capture wheel events,
        avoiding conflicts with nested comboboxes and spinboxes.
        """
        self._wheel_bound = False
        
        def _bind_wheel(_event: tk.Event) -> None:
            if not self._wheel_bound:
                self._canvas.bind_all("<MouseWheel>", self._on_mousewheel)
                # Linux X11 scroll buttons
                self._canvas.bind_all("<Button-4>", self._on_mousewheel_linux)
                self._canvas.bind_all("<Button-5>", self._on_mousewheel_linux)
                self._wheel_bound = True
        
        def _unbind_wheel(_event: tk.Event) -> None:
            if self._wheel_bound:
                try:
                    self._canvas.unbind_all("<MouseWheel>")
                    self._canvas.unbind_all("<Button-4>")
                    self._canvas.unbind_all("<Button-5>")
                except Exception:
                    pass
                self._wheel_bound = False
        
        # Bind to both canvas and inner frame
        self._canvas.bind("<Enter>", _bind_wheel, add="+")
        self._canvas.bind("<Leave>", _unbind_wheel, add="+")
        self.inner.bind("<Enter>", _bind_wheel, add="+")
        # Note: Don't unbind on inner leave since mouse may still be over canvas

    def _on_mousewheel_linux(self, event: tk.Event) -> None:
        """Handle Linux Button-4/Button-5 scroll events."""
        # Check if the widget receiving the event is a combobox or listbox
        widget_class = str(getattr(event.widget, "winfo_class", lambda: "")()).lower()
        if "combobox" in widget_class or "listbox" in widget_class or "spinbox" in widget_class:
            return
        delta = -1 if event.num == 5 else 1
        self._canvas.yview_scroll(delta, "units")

    def _on_mousewheel(self, event: tk.Event) -> None:
        # Avoid double-scrolling when hovering over native dropdown/list widgets
        widget_class = str(getattr(event.widget, "winfo_class", lambda: "")()).lower()
        if "combobox" in widget_class or "listbox" in widget_class or "spinbox" in widget_class:
            return
        delta = int(-1 * (event.delta / 120))
        self._canvas.yview_scroll(delta, "units")


__all__ = ["ScrollableFrame"]
