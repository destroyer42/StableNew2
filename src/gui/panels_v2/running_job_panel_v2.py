"""V2 Running Job Panel - displays active job with progress, ETA, and controls."""

from __future__ import annotations

import threading
import tkinter as tk
from collections.abc import Callable
from datetime import datetime
from tkinter import ttk
from typing import Any, TYPE_CHECKING

from src.gui.theme_v2 import (
    SECONDARY_BUTTON_STYLE,
    STATUS_LABEL_STYLE,  # PR-GUI-DARKMODE-002: Import for pack/stage/seed labels
    STATUS_STRONG_LABEL_STYLE,
    SURFACE_FRAME_STYLE,
)
from src.gui.panels_v2.widgets.stage_timeline_widget import (
    StageTimelineWidget,
    TimelineData,
    create_timeline_from_stage_chain,
)
from src.gui.utils.display_helpers import format_seed_display
from src.pipeline.job_models_v2 import JobStatusV2, RuntimeJobStatus, UnifiedJobSummary

if TYPE_CHECKING:
    from src.queue.job_model import Job


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
        self._current_job: UnifiedJobSummary | None = None
        self._current_job_summary: UnifiedJobSummary | None = None  # PR-CORE-D
        self._runtime_status: RuntimeJobStatus | None = None  # Dynamic execution state
        self._queue_origin: int | None = None  # PR-GUI-F2: Original queue position (1-based)
        self._timer_id: str | None = None  # Tk after() timer ID for elapsed time updates

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
            wraplength=400,
        )
        self.job_info_label.pack(fill="x", pady=(0, 4))

        # PR-CORE-D: PromptPack provenance label
        self.pack_info_label = ttk.Label(
            self,
            text="",
            style=STATUS_LABEL_STYLE,  # PR-GUI-DARKMODE-002: Add dark mode style
            wraplength=400,
        )
        self.pack_info_label.pack(fill="x", pady=(0, 4))

        # PR-CORE-D: Stage chain with current stage highlighting
        self.stage_chain_label = ttk.Label(
            self,
            text="",
            style=STATUS_LABEL_STYLE,  # PR-GUI-DARKMODE-002: Add dark mode style
            wraplength=400,
        )
        self.stage_chain_label.pack(fill="x", pady=(0, 4))

        # PR-PIPE-007: Seed display
        self.seed_label = ttk.Label(
            self,
            text="Seed: -",
            style=STATUS_LABEL_STYLE,  # PR-GUI-DARKMODE-002: Add dark mode style
            wraplength=400,
        )
        self.seed_label.pack(fill="x", pady=(0, 4))

        # PR-PIPE-008: Stage timeline visualization
        self._timeline = StageTimelineWidget(
            self,
            height=40,
            show_animation=True,
        )
        self._timeline.pack(fill="x", padx=5, pady=(5, 10))

        # Status and ETA (progress is shown in timeline above)
        status_frame = ttk.Frame(self, style=SURFACE_FRAME_STYLE)
        status_frame.pack(fill="x", pady=(4, 8))

        self.status_label = ttk.Label(status_frame, text="Status: Idle")
        self.status_label.pack(side="left")

        # Elapsed time (new)
        self.elapsed_label = ttk.Label(status_frame, text="")
        self.elapsed_label.pack(side="right", padx=(8, 0))

        self.eta_label = ttk.Label(status_frame, text="")
        self.eta_label.pack(side="right")

        # Control buttons (D-GUI-002: Improved button labels)
        button_frame = ttk.Frame(self, style=SURFACE_FRAME_STYLE)
        button_frame.pack(fill="x")
        button_frame.columnconfigure((0, 1), weight=1)

        self.pause_resume_button = ttk.Button(
            button_frame,
            text="Pause Job",
            style=SECONDARY_BUTTON_STYLE,
            command=self._on_pause_resume,
            width=10,
        )
        self.pause_resume_button.grid(row=0, column=0, sticky="ew", padx=(0, 2))

        self.cancel_button = ttk.Button(
            button_frame,
            text="Cancel Job",
            style=SECONDARY_BUTTON_STYLE,
            command=self._on_cancel,
            width=10,
        )
        self.cancel_button.grid(row=0, column=1, sticky="ew", padx=(2, 0))

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
        """Format ETA seconds to a human-readable string.
        
        PR-GUI-DATA-005: Display estimated time remaining.
        """
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

    @staticmethod
    def _estimate_eta_from_progress(progress: float, started_at: datetime | None) -> float | None:
        """Estimate ETA using current progress percentage and start time."""
        if started_at is None:
            return None
        if progress <= 0.0:
            return None
        elapsed = (datetime.now() - started_at).total_seconds()
        if elapsed <= 0:
            return None
        try:
            total_estimated = elapsed / progress
            return max(total_estimated - elapsed, 0.0)
        except Exception:
            return None

    def _format_elapsed(self, started_at: datetime | None) -> str:
        """Format elapsed time since job started."""
        if started_at is None:
            return ""

        try:
            now = datetime.utcnow()
            delta = now - started_at
            total_seconds = delta.total_seconds()

            if total_seconds < 60:
                return f"Elapsed: {int(total_seconds)}s"
            elif total_seconds < 3600:
                mins = int(total_seconds // 60)
                secs = int(total_seconds % 60)
                return f"Elapsed: {mins}m {secs}s"
            else:
                hours = int(total_seconds // 3600)
                mins = int((total_seconds % 3600) // 60)
                return f"Elapsed: {hours}h {mins}m"
        except Exception:
            return ""

    def _update_display(self) -> None:
        """Update the display based on current job state."""
        job = self._current_job
        runtime = self._runtime_status

        if job is None:
            # Stop timer when no job running
            self._stop_timer()
            self.job_info_label.configure(text="No job running")
            self.pack_info_label.configure(text="")  # PR-CORE-D
            self.stage_chain_label.configure(text="")  # PR-CORE-D
            self.seed_label.configure(text="Seed: -")  # PR-PIPE-007
            self._timeline.clear()  # PR-PIPE-008
            self.status_label.configure(text="Status: Idle")
            self.elapsed_label.configure(text="")
            self.eta_label.configure(text="")
            self.queue_origin_label.configure(text="")  # PR-GUI-F2
            self.pause_resume_button.configure(text="Pause Job")
            self.pause_resume_button.state(["disabled"])
            self.cancel_button.state(["disabled"])
            return

        # Job info (from UnifiedJobSummary - static data)
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
                    # D-GUI-002: Use 1-based indexing for display (v1/b1)
                    v_text = f"v{variant_idx + 1}" if variant_idx is not None else "v?"
                    b_text = f"b{batch_idx + 1}" if batch_idx is not None else "b?"
                    pack_text += f" [{v_text}/{b_text}]"
                self.pack_info_label.configure(text=pack_text)
            else:
                self.pack_info_label.configure(text="")

            # D-GUI-002: Display current stage with progress
            # Use RuntimeJobStatus if available, otherwise fall back to static stage chain
            if runtime:
                # Runtime status available - show current execution state
                stage_text = f"Stage: {runtime.get_stage_label()}"
                self.stage_chain_label.configure(text=stage_text)
            else:
                # No runtime status - show stage chain from job config
                stage_labels = getattr(self._current_job_summary, "stage_chain_labels", None)
                if stage_labels:
                    # Show all stages since we don't know which is current
                    stage_text = f"Stages: {' → '.join(stage_labels)}"
                    self.stage_chain_label.configure(text=stage_text)
                else:
                    self.stage_chain_label.configure(text="")

            # PR-PIPE-007: Display seed
            # Use actual_seed from runtime if available, otherwise show "calculating..."
            if runtime and runtime.actual_seed is not None:
                seed_text = str(runtime.actual_seed)
            else:
                seed_text = "calculating..."
            self.seed_label.configure(text=f"Seed: {seed_text}")

            # PR-PIPE-008: Update timeline widget
            # TODO: Need stage_chain structure from runtime for timeline
            # For now, clear timeline if no runtime data
            if runtime:
                # We don't have stage_chain structure in runtime yet
                # This will be enhanced in future phase
                self._timeline.clear()
            else:
                self._timeline.clear()
        else:
            self.pack_info_label.configure(text="")
            self.stage_chain_label.configure(text="")
            self.seed_label.configure(text="Seed: -")  # PR-PIPE-007
            self._timeline.clear()  # PR-PIPE-008

        # PR-GUI-F2: Queue origin display
        if self._queue_origin is not None:
            self.queue_origin_label.configure(text=f"(from #{self._queue_origin})")
        else:
            self.queue_origin_label.configure(text="")

        # Status (progress from runtime if available)
        status_value = job.status if isinstance(job.status, str) else job.status.value
        status_text = f"Status: {status_value.title()}"
        
        if runtime:
            # Use progress from runtime status
            progress_pct = runtime.get_progress_percentage()
            if progress_pct > 0:
                status_text += f" ({progress_pct}%)"
        
        self.status_label.configure(text=status_text)

        # Elapsed time
        # Use runtime.started_at if available, otherwise use job.created_at
        if runtime:
            started_at = runtime.started_at
        else:
            started_at = getattr(job, 'created_at', None)
        elapsed_text = self._format_elapsed(started_at)
        self.elapsed_label.configure(text=elapsed_text)

        # ETA display
        if runtime and runtime.eta_seconds is not None:
            # Use ETA from runtime status
            self.eta_label.configure(text=runtime.get_eta_display())
        elif runtime and runtime.progress > 0 and runtime.started_at:
            # Calculate ETA from progress
            eta_seconds = self._estimate_eta_from_progress(runtime.progress, runtime.started_at)
            self.eta_label.configure(text=self._format_eta(eta_seconds))
        else:
            # No ETA available
            self.eta_label.configure(text="ETA: calculating...")

        # Button states
        status_str = job.status if isinstance(job.status, str) else job.status.value
        is_running = status_str.upper() == "RUNNING"
        is_paused = status_str.upper() == "PAUSED"
        can_control = is_running or is_paused

        if is_paused:
            self.pause_resume_button.configure(text="Resume Job")
        else:
            self.pause_resume_button.configure(text="Pause Job")

        self.pause_resume_button.state(["!disabled"] if can_control else ["disabled"])
        self.cancel_button.state(["!disabled"] if can_control else ["disabled"])

        # Start timer for elapsed time updates (if job is running or paused)
        if is_running or is_paused:
            self._start_timer()
        else:
            self._stop_timer()

    def _on_pause_resume(self) -> None:
        """Handle pause/resume button click."""
        if not self.controller or not self._current_job:
            return

        # Handle status as string or enum (UnifiedJobSummary uses strings)
        status_str = self._current_job.status if isinstance(self._current_job.status, str) else self._current_job.status.value
        is_paused = status_str.upper() == "PAUSED"

        if is_paused:
            # Try multiple method names for compatibility
            method = (
                getattr(self.controller, "on_resume_current_job", None) or
                getattr(self.controller, "on_resume_job_v2", None)
            )
        else:
            method = (
                getattr(self.controller, "on_pause_current_job", None) or
                getattr(self.controller, "on_pause_job_v2", None)
            )

        if callable(method):
            method()

    def _on_cancel(self) -> None:
        """Handle cancel button click."""
        if not self.controller:
            return

        # Try multiple method names for compatibility
        method = (
            getattr(self.controller, "on_cancel_current_job", None) or
            getattr(self.controller, "on_cancel_job_v2", None)
        )
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

    def update_job(self, job: UnifiedJobSummary | None, queue_origin: int | None = None) -> None:
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
        job: Job | UnifiedJobSummary | None,
        summary: UnifiedJobSummary | None = None,
        queue_origin: int | None = None,
    ) -> None:
        """PR-CORE-D: Update the panel with job and UnifiedJobSummary.

        Args:
            job: The running Job object (with runtime attrs) or UnifiedJobSummary, or None if no job is running.
            summary: UnifiedJobSummary with PromptPack metadata (optional, for display).
            queue_origin: 1-based queue position the job came from, or None.
        """
        if self._dispatch_to_ui(lambda: self.update_job_with_summary(job, summary, queue_origin)):
            return
        self._current_job = job
        self._current_job_summary = summary
        self._queue_origin = queue_origin
        self._update_display()

    def update_progress(self, progress: float, eta_seconds: float | None = None) -> None:
        """Update just the progress display (updates status text with percentage).
        
        Note: Visual progress is shown in the timeline widget, this just updates
        the status text percentage.
        """
        if self._dispatch_to_ui(lambda: self.update_progress(progress, eta_seconds)):
            return
        if self._current_job:
            # Safely set progress if attribute exists
            if hasattr(self._current_job, 'progress'):
                self._current_job.progress = progress
            if eta_seconds is None:
                eta_seconds = self._estimate_eta_from_progress(
                    progress, getattr(self._current_job, "started_at", None)
                )
            # Safely set eta_seconds if attribute exists
            if hasattr(self._current_job, 'eta_seconds'):
                self._current_job.eta_seconds = eta_seconds

            # Update status text with percentage
            progress_pct = int(progress * 100)
            # Handle status as string or enum (UnifiedJobSummary uses strings)
            status_value = self._current_job.status if isinstance(self._current_job.status, str) else self._current_job.status.value
            status_text = f"Status: {status_value.title()}"
            if progress_pct > 0:
                status_text += f" ({progress_pct}%)"
            self.status_label.configure(text=status_text)
            self.eta_label.configure(text=self._format_eta(eta_seconds))

    def _start_timer(self) -> None:
        """Start the periodic timer to update elapsed time (1 second interval)."""
        if self._timer_id is None:
            self._tick()

    def _stop_timer(self) -> None:
        """Stop the periodic timer."""
        if self._timer_id is not None:
            try:
                self.after_cancel(self._timer_id)
            except Exception:
                pass
            self._timer_id = None

    def _tick(self) -> None:
        """Update elapsed time and schedule next tick."""
        # Update elapsed time if job is running
        if self._current_job:
            # Safely access started_at or created_at
            started_at = getattr(self._current_job, 'started_at', None) or getattr(self._current_job, 'created_at', None)
            if started_at:
                elapsed_text = self._format_elapsed(started_at)
                self.elapsed_label.configure(text=elapsed_text)
        
        # Schedule next tick in 1 second
        self._timer_id = self.after(1000, self._tick)

    def update_from_app_state(self, app_state: Any | None = None) -> None:
        """Update panel from app state."""
        if self._dispatch_to_ui(lambda: self.update_from_app_state(app_state)):
            return
        if app_state is None:
            app_state = self.app_state
        if app_state is None:
            return

        # Get running job (static NJR-derived data) from app state
        running_job = getattr(app_state, "running_job", None)
        self._current_job = running_job
        self._current_job_summary = running_job
        
        # Get runtime status (dynamic execution state) from app state
        runtime_status = getattr(app_state, "runtime_status", None)
        self._runtime_status = runtime_status
        
        # Update display with both static and dynamic data
        self._update_display()
