"""V2 Running Job Panel - displays active job with progress, ETA, and controls."""

from __future__ import annotations

import tkinter as tk
from tkinter import ttk
from typing import Any

from src.gui.theme_v2 import (
    SECONDARY_BUTTON_STYLE,
    STATUS_STRONG_LABEL_STYLE,
    SURFACE_FRAME_STYLE,
)
from src.pipeline.job_models_v2 import JobStatusV2, QueueJobV2


class RunningJobPanelV2(ttk.Frame):
    """
    Panel displaying the currently running job.
    
    Features:
    - Job info display
    - Progress bar with percentage
    - ETA display
    - Pause/Resume button
    - Cancel button
    """

    def __init__(
        self,
        master: tk.Misc,
        *,
        controller: Any | None = None,
        app_state: Any | None = None,
        **kwargs,
    ):
        super().__init__(master, style=SURFACE_FRAME_STYLE, padding=(8, 8, 8, 8), **kwargs)
        self.controller = controller
        self.app_state = app_state
        self._current_job: QueueJobV2 | None = None

        # Title
        title = ttk.Label(self, text="Running Job", style=STATUS_STRONG_LABEL_STYLE)
        title.pack(fill="x", pady=(0, 8))

        # Job info label
        self.job_info_label = ttk.Label(
            self,
            text="No job running",
            style=STATUS_STRONG_LABEL_STYLE,
            wraplength=200,
        )
        self.job_info_label.pack(fill="x", pady=(0, 4))

        # Progress frame
        progress_frame = ttk.Frame(self, style=SURFACE_FRAME_STYLE)
        progress_frame.pack(fill="x", pady=(4, 4))

        self.progress_bar = ttk.Progressbar(
            progress_frame,
            mode="determinate",
            length=200,
        )
        self.progress_bar.pack(side="left", fill="x", expand=True)

        self.progress_label = ttk.Label(
            progress_frame,
            text="0%",
            width=5,
            anchor="e",
        )
        self.progress_label.pack(side="right", padx=(8, 0))

        # Status and ETA
        status_frame = ttk.Frame(self, style=SURFACE_FRAME_STYLE)
        status_frame.pack(fill="x", pady=(4, 8))

        self.status_label = ttk.Label(status_frame, text="Status: Idle")
        self.status_label.pack(side="left")

        self.eta_label = ttk.Label(status_frame, text="")
        self.eta_label.pack(side="right")

        # Control buttons
        button_frame = ttk.Frame(self, style=SURFACE_FRAME_STYLE)
        button_frame.pack(fill="x")
        button_frame.columnconfigure((0, 1), weight=1)

        self.pause_resume_button = ttk.Button(
            button_frame,
            text="Pause",
            style=SECONDARY_BUTTON_STYLE,
            command=self._on_pause_resume,
            width=10,
        )
        self.pause_resume_button.grid(row=0, column=0, sticky="ew", padx=(0, 4))

        self.cancel_button = ttk.Button(
            button_frame,
            text="Cancel",
            style=SECONDARY_BUTTON_STYLE,
            command=self._on_cancel,
            width=10,
        )
        self.cancel_button.grid(row=0, column=1, sticky="ew", padx=(4, 0))

        # Initial state
        self._update_display()

    def _format_eta(self, seconds: float | None) -> str:
        """Format ETA seconds to a human-readable string."""
        if seconds is None or seconds <= 0:
            return ""
        
        if seconds < 60:
            return f"ETA: {int(seconds)}s"
        elif seconds < 3600:
            mins = int(seconds // 60)
            secs = int(seconds % 60)
            return f"ETA: {mins}m {secs}s"
        else:
            hours = int(seconds // 3600)
            mins = int((seconds % 3600) // 60)
            return f"ETA: {hours}h {mins}m"

    def _update_display(self) -> None:
        """Update the display based on current job state."""
        job = self._current_job

        if job is None:
            self.job_info_label.configure(text="No job running")
            self.progress_bar.configure(value=0)
            self.progress_label.configure(text="0%")
            self.status_label.configure(text="Status: Idle")
            self.eta_label.configure(text="")
            self.pause_resume_button.configure(text="Pause")
            self.pause_resume_button.state(["disabled"])
            self.cancel_button.state(["disabled"])
            return

        # Job info
        self.job_info_label.configure(text=job.get_display_summary())

        # Progress
        progress_pct = int(job.progress * 100)
        self.progress_bar.configure(value=progress_pct)
        self.progress_label.configure(text=f"{progress_pct}%")

        # Status
        status_text = f"Status: {job.status.value.title()}"
        self.status_label.configure(text=status_text)

        # ETA
        self.eta_label.configure(text=self._format_eta(job.eta_seconds))

        # Button states
        is_running = job.status == JobStatusV2.RUNNING
        is_paused = job.status == JobStatusV2.PAUSED
        can_control = is_running or is_paused

        if is_paused:
            self.pause_resume_button.configure(text="Resume")
        else:
            self.pause_resume_button.configure(text="Pause")

        self.pause_resume_button.state(["!disabled"] if can_control else ["disabled"])
        self.cancel_button.state(["!disabled"] if can_control else ["disabled"])

    def _on_pause_resume(self) -> None:
        """Handle pause/resume button click."""
        if not self.controller or not self._current_job:
            return

        is_paused = self._current_job.status == JobStatusV2.PAUSED

        if is_paused:
            method = getattr(self.controller, "on_resume_job_v2", None)
        else:
            method = getattr(self.controller, "on_pause_job_v2", None)

        if callable(method):
            method()

    def _on_cancel(self) -> None:
        """Handle cancel button click."""
        if not self.controller:
            return

        method = getattr(self.controller, "on_cancel_job_v2", None)
        if callable(method):
            method()

    def update_job(self, job: QueueJobV2 | None) -> None:
        """Update the panel with a new job or None."""
        self._current_job = job
        self._update_display()

    def update_progress(self, progress: float, eta_seconds: float | None = None) -> None:
        """Update just the progress display (more efficient than full update)."""
        if self._current_job:
            self._current_job.progress = progress
            self._current_job.eta_seconds = eta_seconds
            
            progress_pct = int(progress * 100)
            self.progress_bar.configure(value=progress_pct)
            self.progress_label.configure(text=f"{progress_pct}%")
            self.eta_label.configure(text=self._format_eta(eta_seconds))

    def update_from_app_state(self, app_state: Any | None = None) -> None:
        """Update panel from app state."""
        if app_state is None:
            app_state = self.app_state
        if app_state is None:
            return

        # Get running job from app state
        running_job = getattr(app_state, "running_job", None)
        self.update_job(running_job)


__all__ = ["RunningJobPanelV2"]
