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

        self._body = ttk.Frame(self)

        self._log_list = tk.Listbox(self._body, height=6)
        self._log_list.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)

        scrollbar = ttk.Scrollbar(self._body, orient=tk.VERTICAL, command=self._log_list.yview)
        scrollbar.pack(side=tk.RIGHT, fill=tk.Y)
        self._log_list.configure(yscrollcommand=scrollbar.set)

        self.refresh()

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

        self._log_list.delete(0, tk.END)
        for entry in filtered:
            self._log_list.insert(tk.END, f"[{entry['level']}] {entry['message']}")

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
