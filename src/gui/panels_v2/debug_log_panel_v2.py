"""Simple debug log console for job lifecycle events."""

from __future__ import annotations

import tkinter as tk
from tkinter import ttk
from typing import Any

from src.gui.app_state_v2 import AppStateV2
from src.gui.theme_v2 import (
    BACKGROUND_ELEVATED,
    PADDING_MD,
    STATUS_STRONG_LABEL_STYLE,
    SURFACE_FRAME_STYLE,
    TEXT_PRIMARY,
)
from src.pipeline.job_models_v2 import JobLifecycleLogEvent


class DebugLogPanelV2(ttk.Frame):
    def __init__(
        self, master: tk.Misc, *, app_state: AppStateV2 | None = None, **kwargs: Any
    ) -> None:
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
        """Format lifecycle event with user-friendly messages.
        
        PR-GUI-DATA-006: Enhanced lifecycle log formatting for better readability.
        
        Displays human-readable messages with visual indicators:
        - job_created → "Job abc123 created"
        - stage_completed → "Completed txt2img stage ✓"
        - job_failed → "Job abc123 failed ✗"
        - draft_submitted → "Draft batch with 4 jobs submitted"
        """
        ts = event.timestamp.strftime("%H:%M:%S")
        job_id_short = event.job_id[:8] if event.job_id else "-"
        
        # Format event-specific message
        if event.event_type == "job_created":
            msg = f"Job {job_id_short} created"
        elif event.event_type == "job_started":
            msg = f"Job {job_id_short} started"
        elif event.event_type == "stage_completed":
            stage_name = event.message.split()[-1] if event.message else "stage"
            msg = f"Completed {stage_name} stage ✓"
        elif event.event_type == "job_completed":
            msg = f"Job {job_id_short} completed ✓"
        elif event.event_type == "job_failed":
            reason = event.message if event.message else "unknown error"
            msg = f"Job {job_id_short} failed ✗ ({reason})"
        elif event.event_type == "draft_submitted":
            count = event.draft_size if event.draft_size else "?"
            msg = f"Draft batch with {count} jobs submitted"
        elif event.event_type == "draft_cancelled":
            msg = "Draft cancelled"
        elif event.event_type == "queue_cleared":
            msg = "Queue cleared"
        else:
            # Fallback to technical format for unknown event types
            msg = f"{event.source} | {event.event_type}"
            if event.job_id:
                msg += f" | job={job_id_short}"
            if event.message:
                msg += f" | {event.message}"
        
        return f"{ts} | {msg}"
