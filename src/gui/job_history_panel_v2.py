"""Read-only Job History & Active Queue panel for GUI v2."""
# Phase 3+/4 GUI extras:
# Not required for Phase 1 stability; used by future adetailer/randomizer/job history workflows only.

from __future__ import annotations

import tkinter as tk
from tkinter import ttk
from collections.abc import Iterable
from typing import Any

from src.controller.job_history_service import JobViewModel
from src.gui import theme_v2 as theme_mod


class JobHistoryPanelV2(ttk.Frame):
    """Display active/queued jobs and recent history via JobHistoryService."""

    def __init__(self, master: tk.Misc, *, job_history_service: Any, theme: Any = None, **kwargs) -> None:
        style_name = theme_mod.SURFACE_FRAME_STYLE
        super().__init__(master, style=style_name, padding=theme_mod.PADDING_MD, **kwargs)
        self._service = job_history_service
        self._theme = theme
        self._selected_job_id: str | None = None
        self._selected_status: str | None = None

        header_style = theme_mod.STATUS_STRONG_LABEL_STYLE
        self.header_label = ttk.Label(self, text="Jobs / Queue", style=header_style)
        self.header_label.pack(anchor=tk.W, pady=(0, 4))

        action_bar = ttk.Frame(self, style=style_name)
        action_bar.pack(fill=tk.X, pady=(0, 6))
        self.refresh_btn = ttk.Button(action_bar, text="Refresh", command=self.refresh)
        self.refresh_btn.pack(side=tk.RIGHT)
        self.cancel_btn = ttk.Button(action_bar, text="Cancel Job", command=self._on_cancel, state=tk.DISABLED)
        self.cancel_btn.pack(side=tk.LEFT, padx=(0, 6))
        self.retry_btn = ttk.Button(action_bar, text="Retry Job", command=self._on_retry, state=tk.DISABLED)
        self.retry_btn.pack(side=tk.LEFT)

        self.active_frame = ttk.LabelFrame(self, text="Active / Queued", padding=6, style=style_name)
        self.active_frame.pack(fill=tk.BOTH, expand=True, pady=(0, 6))
        self.recent_frame = ttk.LabelFrame(self, text="Recent Jobs", padding=6, style=style_name)
        self.recent_frame.pack(fill=tk.BOTH, expand=True)

        self._active_empty_label: ttk.Label | None = None
        self._recent_empty_label: ttk.Label | None = None
        self.active_tree = self._build_tree(
            self.active_frame,
            columns=("job_id", "status", "created", "started", "summary"),
            headings={
                "job_id": "Job",
                "status": "Status",
                "created": "Created",
                "started": "Started",
                "summary": "Payload",
            },
        )
        self.active_tree.bind("<<TreeviewSelect>>", self._on_select_active)
        self.recent_tree = self._build_tree(
            self.recent_frame,
            columns=("job_id", "status", "completed", "summary", "error"),
            headings={
                "job_id": "Job",
                "status": "Status",
                "completed": "Completed",
                "summary": "Payload",
                "error": "Last error",
            },
        )
        self.recent_tree.bind("<<TreeviewSelect>>", self._on_select_recent)

        self.refresh()

    def _build_tree(self, parent: tk.Misc, *, columns: Iterable[str], headings: dict[str, str]) -> ttk.Treeview:
        tree = ttk.Treeview(parent, columns=tuple(columns), show="headings", height=6)
        for col in columns:
            tree.heading(col, text=headings.get(col, col))
            width = 90
            if col in {"summary", "error"}:
                width = 260
            tree.column(col, anchor=tk.W, width=width, stretch=True)
        tree.pack(fill=tk.BOTH, expand=True)
        return tree

    def refresh(self) -> None:
        """Refresh data from the job history service."""

        active_jobs = self._safe_list(self._service, "list_active_jobs") or []
        recent_jobs = self._safe_list(self._service, "list_recent_jobs", limit=50) or []

        self._populate_tree(self.active_tree, active_jobs, section="active")
        self._populate_tree(self.recent_tree, recent_jobs, section="recent")

    def _populate_tree(self, tree: ttk.Treeview, jobs: list[JobViewModel], *, section: str) -> None:
        for item in tree.get_children():
            tree.delete(item)

        if not jobs:
            self._show_empty(section)
            return

        self._hide_empty(section)
        for job in jobs:
            values = self._tree_values(job, section=section)
            tree.insert("", "end", values=values)
        self._update_buttons()

    def _tree_values(self, job: JobViewModel, *, section: str) -> tuple[str, ...]:
        short_id = job.job_id
        payload = self._shorten(job.payload_summary, width=80)
        if section == "active":
            return (
                short_id,
                job.status.value,
                job.created_at or "",
                job.started_at or "",
                payload,
            )
        return (
            short_id,
            job.status.value,
            job.completed_at or job.created_at or "",
            payload,
            self._shorten(job.last_error or "", width=64),
        )

    def _show_empty(self, section: str) -> None:
        if section == "active":
            if self._active_empty_label is None:
                self._active_empty_label = ttk.Label(
                    self.active_frame, text="No active or queued jobs", style="Dark.TLabel"
                )
                self._active_empty_label.pack(anchor=tk.W, pady=4)
        elif section == "recent":
            if self._recent_empty_label is None:
                self._recent_empty_label = ttk.Label(
                    self.recent_frame, text="No recent jobs yet", style="Dark.TLabel"
                )
                self._recent_empty_label.pack(anchor=tk.W, pady=4)
        self._update_buttons()

    def _hide_empty(self, section: str) -> None:
        if section == "active" and self._active_empty_label is not None:
            try:
                self._active_empty_label.destroy()
            except Exception:
                pass
            self._active_empty_label = None
        if section == "recent" and self._recent_empty_label is not None:
            try:
                self._recent_empty_label.destroy()
            except Exception:
                pass
            self._recent_empty_label = None
        self._update_buttons()

    @staticmethod
    def _shorten(text: str, *, width: int = 12) -> str:
        if text is None:
            return ""
        s = str(text)
        return s if len(s) <= width else s[:width - 3] + "..."

    @staticmethod
    def _safe_list(service: Any, method: str, *args, **kwargs) -> list[JobViewModel]:
        func = getattr(service, method, None)
        if not callable(func):
            return []
        try:
            result = func(*args, **kwargs)
            return list(result) if result else []
        except Exception:
            return []

    # Selection and actions -------------------------------------------------
    def _on_select_active(self, event=None) -> None:
        sel = self.active_tree.selection()
        if not sel:
            return
        values = self.active_tree.item(sel[0], "values")
        self._selected_job_id = values[0]
        self._selected_status = str(values[1]).lower()
        self._update_buttons()

    def _on_select_recent(self, event=None) -> None:
        sel = self.recent_tree.selection()
        if not sel:
            return
        values = self.recent_tree.item(sel[0], "values")
        self._selected_job_id = values[0]
        self._selected_status = str(values[1]).lower()
        self._update_buttons()

    def _update_buttons(self) -> None:
        status = (self._selected_status or "").lower()
        cancel_enabled = status in {"queued", "running"}
        retry_enabled = status in {"completed", "failed", "cancelled"}
        try:
            self.cancel_btn.configure(state=tk.NORMAL if cancel_enabled else tk.DISABLED)
            self.retry_btn.configure(state=tk.NORMAL if retry_enabled else tk.DISABLED)
        except Exception:
            pass

    def _on_cancel(self) -> None:
        if not self._selected_job_id:
            return
        cancel = getattr(self._service, "cancel_job", None)
        if callable(cancel):
            try:
                cancel(self._selected_job_id)
            except Exception:
                pass
        self.refresh()

    def _on_retry(self) -> None:
        if not self._selected_job_id:
            return
        retry = getattr(self._service, "retry_job", None)
        if callable(retry):
            try:
                retry(self._selected_job_id)
            except Exception:
                pass
        self.refresh()
