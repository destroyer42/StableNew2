"""Simple debug log console for job lifecycle events."""

from __future__ import annotations

import tkinter as tk
from tkinter import ttk
from datetime import datetime
from typing import Any

from src.gui.theme_v2 import BACKGROUND_ELEVATED, TEXT_PRIMARY, SURFACE_FRAME_STYLE, PADDING_MD, STATUS_STRONG_LABEL_STYLE
from src.gui.app_state_v2 import AppStateV2
from src.pipeline.job_models_v2 import JobLifecycleLogEvent


class DebugLogPanelV2(ttk.Frame):
    def __init__(self, master: tk.Misc, *, app_state: AppStateV2 | None = None, **kwargs: Any) -> None:
        super().__init__(master, style=SURFACE_FRAME_STYLE, padding=PADDING_MD, **kwargs)
        self.app_state = app_state
        header = ttk.Label(self, text="Job Lifecycle Log", style=STATUS_STRONG_LABEL_STYLE)
        header.pack(anchor=tk.W)
        self._text = tk.Text(
            self,
            height=8,
            wrap="none",
            bg=BACKGROUND_ELEVATED,
            fg=TEXT_PRIMARY,
            state="disabled",
            relief="flat",
        )
        self._text.pack(fill=tk.BOTH, expand=True, pady=(4, 0))
        self._text.configure(font="TkFixedFont")
        self._state = app_state
        if self._state is not None:
            self._state.subscribe("log_events", self._on_log_events_changed)
            self._on_log_events_changed()

    def _on_log_events_changed(self) -> None:
        if self._state is None:
            return
        events = list(self._state.log_events or [])
        lines = [self._format_event(evt) for evt in events[-200:]]
        self._set_text("\n".join(lines))

    def _set_text(self, value: str) -> None:
        self._text.config(state=tk.NORMAL)
        self._text.delete("1.0", tk.END)
        self._text.insert("1.0", value or "No events yet.")
        self._text.config(state=tk.DISABLED)

    def _format_event(self, event: JobLifecycleLogEvent) -> str:
        ts = event.timestamp.strftime("%H:%M:%S")
        job_part = f"job={event.job_id}" if event.job_id else "job=-"
        draft_part = f"draft={event.draft_size}" if event.draft_size is not None else ""
        payload = f"{event.source} | {event.event_type} | {job_part} {draft_part}".strip()
        return f"{ts} | {payload} | {event.message}"
