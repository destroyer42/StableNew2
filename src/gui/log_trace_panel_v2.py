"""Trace log panel for GUI V2."""

from __future__ import annotations

import tkinter as tk
from tkinter import ttk
from typing import Iterable, Dict, List

from src.utils import InMemoryLogHandler


class LogTracePanelV2(ttk.Frame):
    """Collapsible panel that shows recent log entries."""

    def __init__(self, master: tk.Misc, log_handler: InMemoryLogHandler, *args, **kwargs):
        super().__init__(master, *args, **kwargs)
        self._log_handler = log_handler
        self._expanded = tk.BooleanVar(value=False)
        self._level_filter = tk.StringVar(value="ALL")
        self._auto_scroll = tk.BooleanVar(value=True)

        header = ttk.Frame(self)
        header.pack(side=tk.TOP, fill=tk.X)

        self._toggle_btn = ttk.Button(
            header,
            text="Details ▼",
            width=12,
            command=self._on_toggle,
        )
        self._toggle_btn.pack(side=tk.LEFT)

        ttk.Label(header, text="Level:").pack(side=tk.LEFT, padx=(8, 2))
        self._level_combo = ttk.Combobox(
            header,
            textvariable=self._level_filter,
            values=["ALL", "WARN+", "ERROR"],
            state="readonly",
            width=8,
        )
        self._level_combo.pack(side=tk.LEFT)
        self._level_combo.bind("<<ComboboxSelected>>", lambda *_: self.refresh())

        # Auto-scroll toggle
        self._scroll_check = ttk.Checkbutton(
            header,
            text="Auto-scroll",
            variable=self._auto_scroll,
        )
        self._scroll_check.pack(side=tk.LEFT, padx=(8, 0))

        self._body = ttk.Frame(self)

        self._log_text = tk.Text(
            self._body,
            height=6,
            wrap=tk.WORD,
            state=tk.DISABLED,
            font=("TkDefaultFont", 9),
        )
        self._log_text.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)

        scrollbar = ttk.Scrollbar(self._body, orient=tk.VERTICAL, command=self._log_text.yview)
        scrollbar.pack(side=tk.RIGHT, fill=tk.Y)
        self._log_text.configure(yscrollcommand=scrollbar.set)

        self.refresh()
        self._schedule_refresh()

    def _on_toggle(self) -> None:
        if self._expanded.get():
            self._expanded.set(False)
            self._toggle_btn.config(text="Details ▼")
            self._body.pack_forget()
        else:
            self._expanded.set(True)
            self._toggle_btn.config(text="Details ▲")
            self._body.pack(side=tk.TOP, fill=tk.BOTH, expand=True)
            self.refresh()

    def refresh(self) -> None:
        entries = list(self._log_handler.get_entries())
        filtered = self._apply_filter(entries)

        # Save current scroll position
        current_yview = self._log_text.yview()

        self._log_text.config(state=tk.NORMAL)
        self._log_text.delete(1.0, tk.END)
        for entry in filtered:
            self._log_text.insert(tk.END, f"[{entry['level']}] {entry['message']}\n")
        self._log_text.config(state=tk.DISABLED)

        # Handle scrolling based on auto-scroll setting
        if self._auto_scroll.get():
            # Auto-scroll enabled: always go to bottom
            self._log_text.see(tk.END)
        else:
            # Auto-scroll disabled: restore previous position
            self._log_text.yview_moveto(current_yview[0])

    def _apply_filter(self, entries: Iterable[Dict[str, object]]) -> List[Dict[str, object]]:
        mode = self._level_filter.get()
        result: List[Dict[str, object]] = []
        for entry in entries:
            level = str(entry.get("level", "")).upper()
            if mode == "ALL":
                result.append(entry)
            elif mode == "WARN+" and level in ("WARNING", "ERROR", "CRITICAL"):
                result.append(entry)
            elif mode == "ERROR" and level in ("ERROR", "CRITICAL"):
                result.append(entry)
        return result

    def _schedule_refresh(self) -> None:
        """Schedule periodic refresh of log entries."""
        self.after(1000, self._do_refresh)

    def _do_refresh(self) -> None:
        """Perform refresh and schedule next one."""
        self.refresh()
        self._schedule_refresh()
