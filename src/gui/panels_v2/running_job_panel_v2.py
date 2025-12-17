"""V2 Running Job Panel - displays active job with progress, ETA, and controls."""

from __future__ import annotations

import threading
import tkinter as tk
from collections.abc import Callable
from tkinter import ttk
from typing import Any

from src.gui.theme_v2 import (
    SECONDARY_BUTTON_STYLE,
    STATUS_STRONG_LABEL_STYLE,
    SURFACE_FRAME_STYLE,
)
from src.pipeline.job_models_v2 import JobStatusV2, QueueJobV2, UnifiedJobSummary


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
        **kwargs: Any,
    ) -> None:
        super().__init__(master, style=SURFACE_FRAME_STYLE, padding=(8, 8, 8, 8), **kwargs)
        self.controller = controller
        self.app_state = app_state
        self._current_job: QueueJobV2 | None = None
        self._current_job_summary: UnifiedJobSummary | None = None  # PR-CORE-D
        self._queue_origin: int | None = None  # PR-GUI-F2: Original queue position (1-based)

        # Title with queue origin indicator
        title_frame = ttk.Frame(self, style=SURFACE_FRAME_STYLE)
        title_frame.pack(fill="x", pady=(0, 8))

        title = ttk.Label(title_frame, text="Running Job", style=STATUS_STRONG_LABEL_STYLE)
        title.pack(side="left")

        # PR-GUI-F2: Show which queue position this job came from
        self.queue_origin_label = ttk.Label(
            title_frame,
            text="",
            style=STATUS_STRONG_LABEL_STYLE,
        )
        self.queue_origin_label.pack(side="left", padx=(8, 0))

        # Job info label
        self.job_info_label = ttk.Label(
            self,
            text="No job running",
            style=STATUS_STRONG_LABEL_STYLE,
            wraplength=200,
        )
        self.job_info_label.pack(fill="x", pady=(0, 4))

        # PR-CORE-D: PromptPack provenance label
        self.pack_info_label = ttk.Label(
            self,
            text="",
            wraplength=200,
        )
        self.pack_info_label.pack(fill="x", pady=(0, 4))

        # PR-CORE-D: Stage chain with current stage highlighting
        self.stage_chain_label = ttk.Label(
            self,
            text="",
            wraplength=200,
        )
        self.stage_chain_label.pack(fill="x", pady=(0, 4))

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
        button_frame.columnconfigure((0, 1, 2), weight=1)

        self.pause_resume_button = ttk.Button(
            button_frame,
            text="Pause",
            style=SECONDARY_BUTTON_STYLE,
            command=self._on_pause_resume,
            width=8,
        )
        self.pause_resume_button.grid(row=0, column=0, sticky="ew", padx=(0, 2))

        self.cancel_button = ttk.Button(
            button_frame,
            text="Cancel",
            style=SECONDARY_BUTTON_STYLE,
            command=self._on_cancel,
            width=8,
        )
        self.cancel_button.grid(row=0, column=1, sticky="ew", padx=(2, 2))

        # PR-GUI-F3: Cancel + Return to Queue button
        self.cancel_return_button = ttk.Button(
            button_frame,
            text="Cancel→Queue",
            style=SECONDARY_BUTTON_STYLE,
            command=self._on_cancel_and_return,
            width=11,
        )
        self.cancel_return_button.grid(row=0, column=2, sticky="ew", padx=(2, 0))

        # Initial state
        self._update_display()

    def _dispatch_to_ui(self, fn: Callable[[], None]) -> bool:
        """Reschedule updates to the Tk main thread when invoked off-thread."""
        if threading.current_thread().name != "MainThread" and hasattr(self, "after"):
            try:
                self.after(0, fn)
                return True
            except Exception:
                return False
        return False

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
            self.pack_info_label.configure(text="")  # PR-CORE-D
            self.stage_chain_label.configure(text="")  # PR-CORE-D
            self.progress_bar.configure(value=0)
            self.progress_label.configure(text="0%")
            self.status_label.configure(text="Status: Idle")
            self.eta_label.configure(text="")
            self.queue_origin_label.configure(text="")  # PR-GUI-F2
            self.pause_resume_button.configure(text="Pause")
            self.pause_resume_button.state(["disabled"])
            self.cancel_button.state(["disabled"])
            self.cancel_return_button.state(["disabled"])
            return

        # Job info
        self.job_info_label.configure(text=job.get_display_summary())

        # PR-CORE-D: Display PromptPack metadata if available
        if self._current_job_summary:
            pack_name = getattr(self._current_job_summary, "prompt_pack_name", None)
            row_idx = getattr(self._current_job_summary, "prompt_pack_row_index", None)
            if pack_name:
                pack_text = f"Pack: {pack_name}"
                if row_idx is not None:
                    pack_text += f" (Row {row_idx + 1})"
                variant_idx = getattr(self._current_job_summary, "variant_index", None)
                batch_idx = getattr(self._current_job_summary, "batch_index", None)
                if variant_idx is not None or batch_idx is not None:
                    v_text = f"v{variant_idx}" if variant_idx is not None else "v?"
                    b_text = f"b{batch_idx}" if batch_idx is not None else "b?"
                    pack_text += f" [{v_text}/{b_text}]"
                self.pack_info_label.configure(text=pack_text)
            else:
                self.pack_info_label.configure(text="")

            # Display stage chain (could add current stage highlighting later)
            stage_labels = getattr(self._current_job_summary, "stage_chain_labels", None)
            if stage_labels:
                stage_text = " → ".join(stage_labels)
                self.stage_chain_label.configure(text=f"Stages: {stage_text}")
            else:
                self.stage_chain_label.configure(text="")
        else:
            self.pack_info_label.configure(text="")
            self.stage_chain_label.configure(text="")

        # PR-GUI-F2: Queue origin display
        if self._queue_origin is not None:
            self.queue_origin_label.configure(text=f"(from #{self._queue_origin})")
        else:
            self.queue_origin_label.configure(text="")

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
        self.cancel_return_button.state(["!disabled"] if can_control else ["disabled"])

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

    def _on_cancel_and_return(self) -> None:
        """Handle cancel + return to queue button click.

        PR-GUI-F3: Cancels the running job and puts it back at the
        bottom of the queue for later retry.
        """
        if not self.controller:
            return

        method = getattr(self.controller, "on_cancel_job_and_return_v2", None)
        if callable(method):
            method()

    def update_job(self, job: QueueJobV2 | None, queue_origin: int | None = None) -> None:
        """Update the panel with a new job or None.

        PR-GUI-F2: Now accepts queue_origin to show which queue position
        the running job came from.

        Args:
            job: The running job, or None if no job is running.
            queue_origin: 1-based queue position the job came from, or None.
        """
        if self._dispatch_to_ui(lambda: self.update_job(job, queue_origin)):
            return
        self._current_job = job
        self._queue_origin = queue_origin
        self._update_display()

    def update_job_with_summary(
        self,
        job: QueueJobV2 | None,
        summary: UnifiedJobSummary | None = None,
        queue_origin: int | None = None,
    ) -> None:
        """PR-CORE-D: Update the panel with job and UnifiedJobSummary.

        Args:
            job: The running job, or None if no job is running.
            summary: UnifiedJobSummary with PromptPack metadata.
            queue_origin: 1-based queue position the job came from, or None.
        """
        if self._dispatch_to_ui(lambda: self.update_job_with_summary(job, summary, queue_origin)):
            return
        self._current_job = job
        self._current_job_summary = summary
        self._queue_origin = queue_origin
        self._update_display()

    def update_progress(self, progress: float, eta_seconds: float | None = None) -> None:
        """Update just the progress display (more efficient than full update)."""
        if self._dispatch_to_ui(lambda: self.update_progress(progress, eta_seconds)):
            return
        if self._current_job:
            self._current_job.progress = progress
            self._current_job.eta_seconds = eta_seconds

            progress_pct = int(progress * 100)
            self.progress_bar.configure(value=progress_pct)
            self.progress_label.configure(text=f"{progress_pct}%")
            self.eta_label.configure(text=self._format_eta(eta_seconds))

    def update_from_app_state(self, app_state: Any | None = None) -> None:
        """Update panel from app state."""
        if self._dispatch_to_ui(lambda: self.update_from_app_state(app_state)):
            return
        if app_state is None:
            app_state = self.app_state
        if app_state is None:
            return

        # Get running job from app state
        running_job = getattr(app_state, "running_job", None)
        self.update_job(running_job)


__all__ = ["RunningJobPanelV2"]
