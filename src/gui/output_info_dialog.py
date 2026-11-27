"""NAME-INFO: the desktop "More info" window, one column per image shown (both sides of a compare).

Presentation only: the fields come from ``src/review/output_info.py``, read on the background runner. Read-only:
nothing is queued and no file or record is written.
"""

from __future__ import annotations

import tkinter as tk
from collections.abc import Sequence
from datetime import UTC, datetime
from pathlib import Path
from tkinter import ttk
from typing import Any

from src.controller.app_controller_services.pack_model_batch_service import batch_identity
from src.controller.content_visibility_resolver import ContentVisibilityResolver
from src.gui import theme_v2 as theme_mod
from src.gui.view_contracts.edit_work_runner import EditWorkRunner, build_edit_work_runner
from src.review.output_info import OutputDescriber, info_rows

_VIDEO_SUFFIXES = frozenset({".mp4", ".mov", ".webm", ".mkv", ".gif"})

Side = tuple[str, str | Path]


def describe_sides(
    sides: Sequence[Side], repository: Any
) -> list[tuple[str, list[tuple[str, str]]]]:
    """``(heading, rows)`` per side. Blocking file and database work: call it off the Tk thread."""

    describer = OutputDescriber(repository, batch_identity=batch_identity)
    described = []
    for heading, given in sides:
        path = Path(given)
        try:
            made = datetime.fromtimestamp(path.stat().st_mtime, UTC)
        except OSError:
            made = None
        kind = "video" if path.suffix.lower() in _VIDEO_SUFFIXES else "image"
        info = describer.describe(path, kind=kind, made_at=made)
        described.append((heading, [*info_rows(info), ("File", path.name)]))
    return described


class OutputInfoDialog(tk.Toplevel):
    def __init__(
        self,
        master: tk.Misc,
        sides: Sequence[Side],
        *,
        repository: Any = None,
        app_state: Any = None,
    ) -> None:
        super().__init__(master)
        self.title("More info")
        self.geometry("820x340")
        self.minsize(520, 240)
        theme_mod.apply_toplevel_theme(self)
        self._app_state = app_state
        self._sides = tuple((heading or "This file", Path(path)) for heading, path in sides)
        self._work: EditWorkRunner | None = build_edit_work_runner(self)
        self.status_var = tk.StringVar(master=self, value="Reading…")
        body = ttk.Frame(self, style=theme_mod.SURFACE_FRAME_STYLE, padding=theme_mod.PADDING_MD)
        body.pack(fill=tk.BOTH, expand=True)
        body.columnconfigure(0, weight=1)
        body.rowconfigure(1, weight=1)
        ttk.Label(body, textvariable=self.status_var, style=theme_mod.MUTED_LABEL_STYLE).grid(
            row=0, column=0, sticky="w"
        )
        columns = ("field", *(f"side{index}" for index in range(len(self._sides))))
        self.tree = ttk.Treeview(body, columns=columns, show="headings", height=9)
        self.tree.heading("field", text="")
        self.tree.column("field", width=110, stretch=False)
        for index, (heading, _path) in enumerate(self._sides):
            self.tree.heading(f"side{index}", text=heading)
            self.tree.column(f"side{index}", width=340, stretch=True)
        horizontal = ttk.Scrollbar(body, orient=tk.HORIZONTAL, command=self.tree.xview)
        self.tree.configure(xscrollcommand=horizontal.set)
        self.tree.grid(row=1, column=0, sticky="nsew", pady=(4, 0))
        horizontal.grid(row=2, column=0, sticky="ew")
        ttk.Button(body, text="Close", command=self.destroy).grid(
            row=3, column=0, sticky="e", pady=(6, 0)
        )
        self.bind("<Escape>", lambda _event: self.destroy())
        self.protocol("WM_DELETE_WINDOW", self.destroy)
        self._work.submit(
            "output-info",
            lambda: describe_sides(self._sides, repository),
            on_result=self._show,
            on_error=lambda _error: self.status_var.set("The information could not be read."),
            name="output-info",
            purpose="Read what made the shown images without blocking Tk",
        )

    def _show(self, described: list[tuple[str, list[tuple[str, str]]]]) -> None:
        self.status_var.set("")
        resolver = ContentVisibilityResolver(
            str(getattr(self._app_state, "content_visibility_mode", None) or "nsfw")
        )
        values = [dict(rows) for _heading, rows in described]
        names = list(dict.fromkeys(name for _heading, rows in described for name, _value in rows))
        self.tree.delete(*self.tree.get_children())
        for name in names:
            row = [
                resolver.redact_text(side.get(name, "")) if side.get(name) else "—"
                for side in values
            ]
            self.tree.insert("", "end", values=(name, *row))

    def destroy(self) -> None:
        work = getattr(self, "_work", None)
        if work is not None:
            self._work = None
            work.close()
        super().destroy()


__all__ = ["OutputInfoDialog", "describe_sides"]
