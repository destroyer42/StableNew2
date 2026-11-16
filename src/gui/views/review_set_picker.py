"""A small picker for Review's Open menu (Recent job and Batch). Presentation only (PR-REVIEW-LIFECYCLE-621).

The dialog lists rows it is given and reports the chosen row id; the Review tab resolves outputs through the existing
output resolution and loads them. It reads no repository, queue or file itself.
"""

from __future__ import annotations

import tkinter as tk
from collections.abc import Callable, Sequence
from tkinter import ttk

from src.gui.theme_v2 import apply_toplevel_theme


class ReviewSetPicker(tk.Toplevel):
    def __init__(
        self,
        master: tk.Misc,
        *,
        title: str,
        columns: Sequence[tuple[str, str, int]],
        on_open: Callable[[str], None],
        open_label: str = "Open in Review",
    ) -> None:
        super().__init__(master)
        self.title(title)
        self.transient(master.winfo_toplevel())
        apply_toplevel_theme(self)
        self.geometry("900x420")
        self.minsize(720, 320)
        self._on_open = on_open
        frame = ttk.Frame(self, padding=8)
        frame.pack(fill="both", expand=True)
        frame.columnconfigure(0, weight=1)
        frame.rowconfigure(0, weight=1)
        self.tree = ttk.Treeview(
            frame, columns=[name for name, _h, _w in columns], show="headings", selectmode="browse"
        )
        for name, heading, width in columns:
            self.tree.heading(name, text=heading)
            self.tree.column(name, width=width, anchor="w")
        self.tree.grid(row=0, column=0, sticky="nsew")
        scrollbar = ttk.Scrollbar(frame, orient="vertical", command=self.tree.yview)
        scrollbar.grid(row=0, column=1, sticky="ns")
        self.tree.configure(yscrollcommand=scrollbar.set)
        self.tree.bind("<Double-1>", lambda _event: self._open())
        self.status = tk.StringVar(master=self, value="")
        ttk.Label(frame, textvariable=self.status, style="Dark.TLabel").grid(
            row=1, column=0, columnspan=2, sticky="w", pady=(6, 0)
        )
        actions = ttk.Frame(frame, style="Panel.TFrame")
        actions.grid(row=2, column=0, columnspan=2, sticky="ew", pady=(8, 0))
        self.open_button = ttk.Button(
            actions, text=open_label, style="Dark.TButton", command=self._open
        )
        self.open_button.pack(side="left")
        ttk.Button(actions, text="Close", style="Dark.TButton", command=self.destroy).pack(
            side="right"
        )

    def set_rows(self, rows: Sequence[tuple[str, Sequence[str]]]) -> None:
        self.tree.delete(*self.tree.get_children())
        for iid, values in rows:
            self.tree.insert("", "end", iid=iid, values=tuple(values))

    def set_status(self, text: str) -> None:
        self.status.set(text)

    def selected_id(self) -> str:
        selection = self.tree.selection()
        return str(selection[0]) if selection else ""

    def _open(self) -> None:
        chosen = self.selected_id()
        if not chosen:
            self.set_status("Select a row first.")
            return
        self._on_open(chosen)


__all__ = ["ReviewSetPicker"]
