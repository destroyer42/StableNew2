"""Compact job history renderer for the Pipeline tab."""

from __future__ import annotations

import os
import subprocess
import sys
import tkinter as tk
from collections.abc import Callable
from datetime import datetime
from pathlib import Path
from tkinter import ttk
from typing import Any

from src.gui import theme_v2 as theme_mod
from src.queue.job_history_store import JobHistoryEntry


class JobHistoryPanelV2(ttk.Frame):
    """Show recent job history entries (completion timestamps, packs, duration, output)."""

    def __init__(
        self,
        master: tk.Misc,
        *,
        controller: Any | None = None,
        app_state: Any | None = None,
        theme: Any | None = None,
        folder_opener: Callable[[str], None] | None = None,
        **kwargs,
    ) -> None:
        style_name = theme_mod.SURFACE_FRAME_STYLE
        super().__init__(master, style=style_name, padding=theme_mod.PADDING_MD, **kwargs)
        self.controller = controller
        self.app_state = app_state
        self._folder_opener = folder_opener or self._default_open_folder
        self._entries: dict[str, JobHistoryEntry] = {}
        self._item_to_job: dict[str, str] = {}
        self._selected_job_id: str | None = None

        header_style = theme_mod.STATUS_STRONG_LABEL_STYLE
        ttk.Label(self, text="Job History", style=header_style).pack(anchor=tk.W, pady=(0, 4))

        action_bar = ttk.Frame(self, style=style_name)
        action_bar.pack(fill=tk.X, pady=(0, 4))
        self.refresh_btn = ttk.Button(action_bar, text="Refresh History", command=self._on_refresh)
        self.refresh_btn.pack(side=tk.RIGHT, padx=(0, 4))
        self.open_btn = ttk.Button(
            action_bar,
            text="Open Output Folder",
            command=self._on_open_folder,
            state=tk.DISABLED,
        )
        self.open_btn.pack(side=tk.LEFT)
        self.replay_btn = ttk.Button(
            action_bar,
            text="Replay Job",
            command=self._on_replay_job,
            state=tk.DISABLED,
        )
        self.replay_btn.pack(side=tk.LEFT, padx=(4, 0))
        self.explain_btn = ttk.Button(
            action_bar,
            text="Explain Job",
            command=self._on_explain_job,
            state=tk.DISABLED,
        )
        self.explain_btn.pack(side=tk.LEFT, padx=(4, 0))

        columns = ("time", "status", "packs", "duration", "images", "output")
        headings = {
            "time": "Completed",
            "status": "Status",
            "packs": "Packs / Payload",
            "duration": "Duration",
            "images": "Images",
            "output": "Output Folder",
        }
        self.history_tree = ttk.Treeview(self, columns=columns, show="headings", height=6)
        for col in columns:
            self.history_tree.heading(col, text=headings[col])
            width = 110
            if col in {"packs", "output"}:
                width = 220
            self.history_tree.column(col, anchor=tk.W, width=width, stretch=True)
        self.history_tree.pack(fill=tk.BOTH, expand=True)
        self.history_tree.bind("<<TreeviewSelect>>", self._on_select)
        self._history_menu = tk.Menu(self, tearoff=0)
        self._history_menu.add_command(label="Explain This Job", command=self._on_explain_job)
        self.history_tree.bind("<Button-3>", self._on_context_menu)

        if app_state and hasattr(app_state, "subscribe"):
            app_state.subscribe("history_items", self._on_history_items_changed)
            try:
                self._on_history_items_changed()
            except Exception:
                pass

    def _on_refresh(self) -> None:
        ctrl = self.controller
        if ctrl and hasattr(ctrl, "refresh_job_history"):
            try:
                ctrl.refresh_job_history()
                return
            except Exception:
                pass
        self._on_history_items_changed()

    def _on_history_items_changed(self) -> None:
        items = []
        if self.app_state:
            items = list(self.app_state.history_items or [])
        self._populate_history(items)

    def _populate_history(self, entries: list[JobHistoryEntry]) -> None:
        for item in self.history_tree.get_children():
            self.history_tree.delete(item)
        self._entries.clear()
        self._item_to_job.clear()
        for entry in entries:
            values = self._entry_values(entry)
            item_id = self.history_tree.insert("", "end", values=values)
            self._entries[entry.job_id] = entry
            self._item_to_job[item_id] = entry.job_id
        self._selected_job_id = None
        self.open_btn.configure(state=tk.DISABLED)

    def _entry_values(self, entry: JobHistoryEntry) -> tuple[str, ...]:
        time_text = self._format_time(entry.completed_at or entry.started_at or entry.created_at)
        status = entry.status.value
        packs = self._shorten(entry.payload_summary or "n/a", width=40)
        # Use pre-calculated duration_ms if available, otherwise fall back to timestamp diff
        if entry.duration_ms is not None:
            duration = self._format_duration_ms(entry.duration_ms)
        else:
            duration = self._format_duration(entry.started_at, entry.completed_at)
        images = "-"
        output = self._derive_output_folder(entry)
        return (time_text, status, packs, duration, images, output)

    def _on_select(self, event=None) -> None:
        selection = self.history_tree.selection()
        if not selection:
            self._selected_job_id = None
            self.open_btn.configure(state=tk.DISABLED)
            self.replay_btn.configure(state=tk.DISABLED)
            return
        item_id = selection[0]
        job_id = self._item_to_job.get(item_id)
        self._selected_job_id = job_id
        entry = self._entries.get(job_id) if job_id else None
        if not entry:
            self._selected_job_id = None
            self.open_btn.configure(state=tk.DISABLED)
            self.replay_btn.configure(state=tk.DISABLED)
            self.explain_btn.configure(state=tk.DISABLED)
            return
        self.open_btn.configure(state=tk.NORMAL)
        self.replay_btn.configure(state=tk.NORMAL)
        self.explain_btn.configure(state=tk.NORMAL)

    def _on_open_folder(self) -> None:
        if not self._selected_job_id:
            return
        entry = self._entries.get(self._selected_job_id)
        if not entry:
            return
        folder = self._derive_output_folder(entry)
        if not folder:
            return
        try:
            self._folder_opener(folder)
        except Exception:
            pass

    def _on_replay_job(self) -> None:
        if not self._selected_job_id or not self.controller:
            return
        handler = getattr(self.controller, "on_replay_history_job_v2", None)
        if not callable(handler):
            return
        try:
            handler(self._selected_job_id)
        except Exception:
            pass

    def _on_explain_job(self) -> None:
        if not self._selected_job_id or not self.controller:
            return
        handler = getattr(self.controller, "explain_job", None)
        if callable(handler):
            try:
                handler(self._selected_job_id)
            except Exception:
                pass

    def _on_context_menu(self, event: tk.Event) -> None:
        item = self.history_tree.identify_row(event.y)
        if not item:
            return
        self.history_tree.selection_set(item)
        self.history_tree.focus(item)
        job_id = self._item_to_job.get(item)
        if not job_id:
            return
        self._selected_job_id = job_id
        self.explain_btn.configure(state=tk.NORMAL)
        self._history_menu.tk_popup(event.x_root, event.y_root)

    def _derive_output_folder(self, entry: JobHistoryEntry) -> str:
        base = Path("runs")
        candidate = base / entry.job_id
        if candidate.exists():
            return str(candidate)
        if base.exists():
            return str(base)
        return str(base)

    @staticmethod
    def _format_time(value: str | None) -> str:
        if not value:
            return "-"
        try:
            dt = datetime.fromisoformat(value)
            return dt.strftime("%H:%M:%S")
        except Exception:
            return value

    @staticmethod
    def _format_duration(start: str | None, end: str | None) -> str:
        if not start or not end:
            return "-"
        try:
            delta = datetime.fromisoformat(end) - datetime.fromisoformat(start)
            return f"{delta.total_seconds():.1f}s"
        except Exception:
            return "-"

    @staticmethod
    def _format_duration_ms(duration_ms: int) -> str:
        """Format duration in milliseconds to readable format."""
        total_seconds = duration_ms / 1000
        if total_seconds < 60:
            return f"{total_seconds:.0f}s"
        minutes = int(total_seconds // 60)
        seconds = int(total_seconds % 60)
        if minutes < 60:
            return f"{minutes}m {seconds}s"
        hours = minutes // 60
        minutes = minutes % 60
        return f"{hours}h {minutes}m"

    @staticmethod
    def _shorten(text: str, *, width: int = 16) -> str:
        if len(text) <= width:
            return text
        return text[: width - 3] + "..."

    @staticmethod
    def _default_open_folder(path: str) -> None:
        candidate = Path(path)
        if not candidate.exists():
            candidate = candidate.parent
        try:
            if os.name == "nt":
                os.startfile(str(candidate))
            elif sys.platform == "darwin":
                subprocess.run(["open", str(candidate)], check=False)
            else:
                subprocess.run(["xdg-open", str(candidate)], check=False)
        except Exception:
            pass
