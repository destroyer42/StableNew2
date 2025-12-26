"""V2 Queue Panel (PR-CORE1-A3: NJR-only display).

Displays ordered job list with manipulation controls.
All display data comes from UnifiedJobSummary (derived from NJR snapshots).
Panel consumers must only invoke its API from the Tk main thread (e.g., via `AppController._run_in_gui_thread` or a similar dispatcher).
"""

from __future__ import annotations

import logging
import threading
import tkinter as tk
from collections.abc import Callable
from tkinter import ttk
from typing import Any

logger = logging.getLogger(__name__)

from src.gui.theme_v2 import (
    ACCENT_GOLD,
    ASWF_ERROR_RED,
    SECONDARY_BUTTON_STYLE,
    STATUS_LABEL_STYLE,
    STATUS_STRONG_LABEL_STYLE,
    SURFACE_FRAME_STYLE,
    TEXT_PRIMARY,
)
from src.pipeline.job_models_v2 import (
    JobQueueItemDTO,
    NormalizedJobRecord,
    UnifiedJobSummary,
)


class QueuePanelV2(ttk.Frame):
    """
    Queue panel displaying ordered list of queued jobs.

    Features:
    - Selectable job list
    - Move Up/Down buttons to reorder
    - Remove selected job
    - Clear all queued jobs
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
        self._jobs: list[UnifiedJobSummary] = []
        self._is_queue_paused = False
        self._auto_run_enabled = False
        self._running_job_id: str | None = None  # PR-GUI-F2: Track running job for highlighting
        self._summaries: list[UnifiedJobSummary] = []

        # Title row
        title_frame = ttk.Frame(self, style=SURFACE_FRAME_STYLE)
        title_frame.pack(fill="x", pady=(0, 4))

        title = ttk.Label(title_frame, text="Queue", style=STATUS_STRONG_LABEL_STYLE)
        title.pack(side="left")

        self.count_label = ttk.Label(title_frame, text="(0 jobs)", style=STATUS_STRONG_LABEL_STYLE)
        self.count_label.pack(side="left", padx=(8, 0))

        # PR-GUI-F1: Queue controls (pause, auto-run, status) live here
        # These were moved from PipelineRunControlsV2 for unified queue management
        controls_frame = ttk.Frame(self, style=SURFACE_FRAME_STYLE)
        controls_frame.pack(fill="x", pady=(0, 4))

        self.auto_run_var = tk.BooleanVar(value=False)
        self.auto_run_check = ttk.Checkbutton(
            controls_frame,
            text="Auto-run queue",
            variable=self.auto_run_var,
            command=self._on_auto_run_changed,
            style="Dark.TCheckbutton",
        )
        self.auto_run_check.pack(side="left")

        self.pause_resume_button = ttk.Button(
            controls_frame,
            text="Pause Queue",
            style=SECONDARY_BUTTON_STYLE,
            command=self._on_pause_resume,
            width=12,
        )
        self.pause_resume_button.pack(side="right")

        # PR-GUI-F3: Send Job button - dispatches top job from queue manually
        self.send_job_button = ttk.Button(
            controls_frame,
            text="Send Job",
            style=SECONDARY_BUTTON_STYLE,
            command=self._on_send_job,
            width=10,
        )
        self.send_job_button.pack(side="right", padx=(0, 4))
        # Queue status label with dark-mode styling
        self.queue_status_label = ttk.Label(
            self,
            text="Queue: Idle",
            style=STATUS_LABEL_STYLE,
        )
        self.queue_status_label.pack(anchor="w", pady=(0, 2))

        # Queue ETA label (estimated total time)
        self.queue_eta_label = ttk.Label(
            self,
            text="",
            style=STATUS_LABEL_STYLE,
        )
        self.queue_eta_label.pack(anchor="w", pady=(0, 4))

        # Job listbox with scrollbar
        list_frame = ttk.Frame(self, style=SURFACE_FRAME_STYLE)
        list_frame.pack(fill="both", expand=True, pady=(4, 8))

        self.job_listbox = tk.Listbox(
            list_frame,
            height=6,
            selectmode=tk.SINGLE,
            exportselection=False,
            bg="#2a2a2a",
            fg="#e0e0e0",
            selectbackground="#4a90d9",
            selectforeground="#ffffff",
            highlightthickness=1,
            highlightbackground="#3a3a3a",
            highlightcolor="#4a90d9",
            relief="flat",
            font=("Segoe UI", 9),
        )
        self.job_listbox.pack(side="left", fill="both", expand=True)

        scrollbar = ttk.Scrollbar(list_frame, orient="vertical", command=self.job_listbox.yview)
        scrollbar.pack(side="right", fill="y")
        self.job_listbox.configure(yscrollcommand=scrollbar.set)

        # Bind selection event
        self.job_listbox.bind("<<ListboxSelect>>", self._on_selection_changed)

        # Button row
        button_frame = ttk.Frame(self, style=SURFACE_FRAME_STYLE)
        button_frame.pack(fill="x")
        button_frame.columnconfigure((0, 1, 2, 3, 4, 5), weight=1)

        # Move to front button
        self.move_to_front_button = ttk.Button(
            button_frame,
            text="⇈ Front",
            style=SECONDARY_BUTTON_STYLE,
            command=self._on_move_to_front,
            width=8,
        )
        self.move_to_front_button.grid(row=0, column=0, sticky="ew", padx=(0, 2))

        self.move_up_button = ttk.Button(
            button_frame,
            text="▲ Up",
            style=SECONDARY_BUTTON_STYLE,
            command=self._on_move_up,
            width=8,
        )
        self.move_up_button.grid(row=0, column=1, sticky="ew", padx=(2, 2))

        self.move_down_button = ttk.Button(
            button_frame,
            text="▼ Down",
            style=SECONDARY_BUTTON_STYLE,
            command=self._on_move_down,
            width=8,
        )
        self.move_down_button.grid(row=0, column=2, sticky="ew", padx=(2, 2))

        # Move to back button
        self.move_to_back_button = ttk.Button(
            button_frame,
            text="⇊ Back",
            style=SECONDARY_BUTTON_STYLE,
            command=self._on_move_to_back,
            width=8,
        )
        self.move_to_back_button.grid(row=0, column=3, sticky="ew", padx=(2, 2))

        self.remove_button = ttk.Button(
            button_frame,
            text="Remove",
            style=SECONDARY_BUTTON_STYLE,
            command=self._on_remove,
            width=8,
        )
        self.remove_button.grid(row=0, column=4, sticky="ew", padx=(2, 2))

        self.clear_button = ttk.Button(
            button_frame,
            text="Clear All",
            style=SECONDARY_BUTTON_STYLE,
            command=self._on_clear,
            width=8,
        )
        self.clear_button.grid(row=0, column=5, sticky="ew", padx=(2, 0))

        # Initial button state
        self._update_button_states()

        # PR-PIPE-003: Bind keyboard shortcuts
        self._bind_keyboard_shortcuts()

        if self.app_state and hasattr(self.app_state, "subscribe"):
            try:
                self.app_state.subscribe("queue_job_summaries", self._on_queue_summaries_changed)
            except Exception:
                pass
            try:
                self.app_state.subscribe("running_job_summary", self._on_running_summary_changed)
            except Exception:
                pass
            # PR-CORE-D: Subscribe to lifecycle events for real-time updates
            try:
                self.app_state.subscribe("log_events", self._on_lifecycle_event)
            except Exception:
                pass
            try:
                self.app_state.subscribe("queue_jobs", self._on_queue_jobs_changed)
            except Exception:
                pass
            self._on_queue_summaries_changed()
            self._on_running_summary_changed()

    def _dispatch_to_ui(self, fn: Callable[[], None]) -> bool:
        """Ensure widget mutations occur on the Tk main thread."""
        if threading.current_thread().name != "MainThread" and hasattr(self, "after"):
            try:
                self.after(0, fn)
                return True
            except Exception:
                return False
        return False

    def _on_selection_changed(self, event: tk.Event[tk.Listbox] | None = None) -> None:
        """Handle selection change in the listbox."""
        self._update_button_states()

    def _get_selected_index(self) -> int | None:
        """Get the currently selected index, or None if nothing selected."""
        selection = self.job_listbox.curselection()  # type: ignore[no-untyped-call]
        if selection:
            return int(selection[0])
        return None

    def _get_selected_job(self) -> UnifiedJobSummary | None:
        """Get the currently selected job, or None if nothing selected."""
        idx = self._get_selected_index()
        if idx is not None and 0 <= idx < len(self._jobs):
            return self._jobs[idx]
        return None

    def _format_queue_eta(self, total_seconds: float) -> str:
        """Format total queue ETA to human-readable string."""
        if total_seconds < 60:
            return f"Est. total: {int(total_seconds)}s"
        elif total_seconds < 3600:
            mins = int(total_seconds // 60)
            secs = int(total_seconds % 60)
            return f"Est. total: {mins}m {secs}s"
        else:
            hours = int(total_seconds // 3600)
            mins = int((total_seconds % 3600) // 60)
            return f"Est. total: {hours}h {mins}m"

    def _compute_queue_eta(self) -> tuple[float, str]:
        """Compute queue ETA using duration stats service.
        
        Returns:
            Tuple of (total_seconds, confidence_indicator)
            confidence_indicator: '~' for history-based, '?' for fallback, '~?' for mixed
        """
        count = len(self._jobs)
        if count == 0:
            return (0.0, "")

        # Try to get stats service from controller
        stats_service = None
        if self.controller:
            stats_service = getattr(self.controller, "duration_stats_service", None)

        if stats_service is None:
            # Fallback to old hardcoded estimate
            return (count * 60.0, "?")

        try:
            total_seconds, jobs_with_estimates = stats_service.get_queue_total_estimate(
                self._jobs
            )
        except Exception:
            return (count * 60.0, "?")

        # Determine confidence indicator
        if jobs_with_estimates == count:
            confidence = "~"  # All based on history
        elif jobs_with_estimates > 0:
            confidence = "~?"  # Mixed
        else:
            confidence = "?"  # All fallback

        return (total_seconds, confidence)

    def _update_button_states(self) -> None:
        """Update button enabled/disabled states based on selection and queue contents."""
        idx = self._get_selected_index()
        has_selection = idx is not None
        has_jobs = len(self._jobs) > 0
        has_multiple_jobs = len(self._jobs) > 1

        # Move to front: enabled if selection exists and not already first
        can_move_to_front = has_selection and idx is not None and idx > 0
        self.move_to_front_button.state(["!disabled"] if can_move_to_front else ["disabled"])

        # Move up: enabled if selection is not first
        can_move_up = has_selection and idx is not None and idx > 0
        self.move_up_button.state(["!disabled"] if can_move_up else ["disabled"])

        # Move down: enabled if selection is not last
        can_move_down = has_selection and idx is not None and idx < len(self._jobs) - 1
        self.move_down_button.state(["!disabled"] if can_move_down else ["disabled"])

        # Move to back: enabled if selection exists and not already last
        can_move_to_back = has_selection and idx is not None and idx < len(self._jobs) - 1
        self.move_to_back_button.state(["!disabled"] if can_move_to_back else ["disabled"])

        # Remove: enabled if something is selected
        self.remove_button.state(["!disabled"] if has_selection else ["disabled"])

        # Clear: enabled if there are any jobs
        self.clear_button.state(["!disabled"] if has_jobs else ["disabled"])

        # PR-GUI-F3: Send Job - enabled if queue has jobs and not currently running a job
        # Also respects pause state (controller handles actual pause blocking)
        running_job = getattr(self.app_state, "running_job", None) if self.app_state else None
        can_send = has_jobs and running_job is None
        self.send_job_button.state(["!disabled"] if can_send else ["disabled"])

    def _on_move_up(self) -> None:
        """Move the selected job up in the queue with visual feedback."""
        job = self._get_selected_job()
        idx = self._get_selected_index()
        
        if not job or idx is None:
            return
        
        # Check if already at top
        if idx == 0:
            # Subtle feedback: item is already at top
            self._show_boundary_feedback("top")
            return
        
        # Perform the move
        if self.controller:
            move_fn = getattr(self.controller, "move_queue_job_up", None) or getattr(
                self.controller, "on_queue_move_up_v2", None
            )
            if callable(move_fn):
                move_fn(job.job_id)
            
            # Update selection to follow the moved item
            new_idx = idx - 1
            
            # Schedule visual feedback after listbox updates
            def _apply_feedback() -> None:
                self._select_index(new_idx)
                self._flash_move(new_idx)
                self._emit_status_message(f"Moved job to position #{new_idx + 1}")
            
            # Small delay to let update_jobs complete
            self.after(50, _apply_feedback)

    def _on_move_down(self) -> None:
        """Move the selected job down in the queue with visual feedback."""
        job = self._get_selected_job()
        idx = self._get_selected_index()
        
        if not job or idx is None:
            return
        
        # Check if already at bottom
        if idx >= len(self._jobs) - 1:
            self._show_boundary_feedback("bottom")
            return
        
        # Perform the move
        if self.controller:
            move_fn = getattr(self.controller, "move_queue_job_down", None) or getattr(
                self.controller, "on_queue_move_down_v2", None
            )
            if callable(move_fn):
                move_fn(job.job_id)
            
            new_idx = idx + 1
            
            def _apply_feedback() -> None:
                self._select_index(new_idx)
                self._flash_move(new_idx)
                self._emit_status_message(f"Moved job to position #{new_idx + 1}")
            
            self.after(50, _apply_feedback)

    def _on_move_to_front(self) -> None:
        """Move the selected job to the front of the queue."""
        job = self._get_selected_job()
        idx = self._get_selected_index()
        
        if not job or idx is None:
            return
        
        # Check if already at front
        if idx == 0:
            self._show_boundary_feedback("top")
            return
        
        # Perform the move
        if self.controller:
            move_fn = getattr(self.controller, "move_queue_job_to_front", None)
            if callable(move_fn):
                move_fn(job.job_id)
            
            # Update selection to follow the moved item (now at front)
            new_idx = 0
            
            def _apply_feedback() -> None:
                self._select_index(new_idx)
                self._flash_move(new_idx)
                self._emit_status_message(f"Moved job to front (position #1)")
            
            self.after(50, _apply_feedback)

    def _on_move_to_back(self) -> None:
        """Move the selected job to the back of the queue."""
        job = self._get_selected_job()
        idx = self._get_selected_index()
        
        if not job or idx is None:
            return
        
        # Check if already at back
        if idx >= len(self._jobs) - 1:
            self._show_boundary_feedback("bottom")
            return
        
        # Perform the move
        if self.controller:
            move_fn = getattr(self.controller, "move_queue_job_to_back", None)
            if callable(move_fn):
                move_fn(job.job_id)
            
            # Update selection to follow the moved item (now at back)
            new_idx = len(self._jobs) - 1
            
            def _apply_feedback() -> None:
                self._select_index(new_idx)
                self._flash_move(new_idx)
                self._emit_status_message(f"Moved job to back (position #{new_idx + 1})")
            
            self.after(50, _apply_feedback)

    def _on_remove(self) -> None:
        """Remove the selected job from the queue with feedback."""
        job = self._get_selected_job()
        idx = self._get_selected_index()
        
        if not job:
            return
        
        if self.controller:
            self.controller.on_queue_remove_job_v2(job.job_id)
            self._emit_status_message(f"Removed job from position #{idx + 1}" if idx is not None else "Removed job")
            
            # Select next item if available
            if self._jobs and idx is not None:
                new_idx = min(idx, len(self._jobs) - 1)
                if new_idx >= 0:
                    self.after(50, lambda: self._select_index(new_idx))

    def _on_clear(self) -> None:
        """Clear all jobs from the queue."""
        if self.controller:
            self.controller.on_queue_clear_v2()

    # PR-PIPE-003: Visual feedback methods
    
    def _flash_item(self, index: int, color: str = "#4a90d9", duration_ms: int = 300) -> None:
        """Briefly highlight a listbox item to indicate action completion."""
        if index < 0 or index >= self.job_listbox.size():
            return
        
        # Store original colors
        try:
            original_bg = self.job_listbox.cget("bg")
            original_select_bg = self.job_listbox.cget("selectbackground")
        except Exception:
            return
        
        # Apply highlight to the specific item
        try:
            self.job_listbox.itemconfig(index, bg=color, selectbackground=color)
        except Exception:
            return
        
        def _restore() -> None:
            try:
                if self.job_listbox.winfo_exists():
                    self.job_listbox.itemconfig(index, bg=original_bg, selectbackground=original_select_bg)
            except tk.TclError:
                pass  # Widget destroyed
        
        # Schedule restore
        self.after(duration_ms, _restore)

    def _flash_success(self, index: int) -> None:
        """Flash item green to indicate success."""
        self._flash_item(index, color="#4a9f4a", duration_ms=250)

    def _flash_move(self, index: int) -> None:
        """Flash item blue to indicate move completed."""
        self._flash_item(index, color="#4a90d9", duration_ms=300)

    def _show_boundary_feedback(self, boundary: str) -> None:
        """Show subtle feedback when job is at queue boundary."""
        idx = self._get_selected_index()
        if idx is not None:
            # Brief orange flash to indicate "can't go further"
            self._flash_item(idx, color="#d9a04a", duration_ms=150)

    def _emit_status_message(self, message: str, level: str = "info") -> None:
        """Emit a status message via controller or status bar."""
        # Try controller's append_log
        if self.controller and hasattr(self.controller, "_append_log"):
            prefix = {
                "info": "[queue]",
                "success": "[queue] ✓",
                "warning": "[queue] ⚠",
                "error": "[queue] ✗"
            }
            self.controller._append_log(f"{prefix.get(level, '[queue]')} {message}")
        
        # Try status bar if available
        if self.app_state and hasattr(self.app_state, "set_status_message"):
            try:
                self.app_state.set_status_message(message)
            except Exception:
                pass

    def _bind_keyboard_shortcuts(self) -> None:
        """Bind keyboard shortcuts for queue operations."""
        # Alt+Up: Move selected job up
        self.job_listbox.bind("<Alt-Up>", lambda e: self._on_move_up())
        
        # Alt+Down: Move selected job down
        self.job_listbox.bind("<Alt-Down>", lambda e: self._on_move_down())
        
        # Delete: Remove selected job
        self.job_listbox.bind("<Delete>", lambda e: self._on_remove())
        
        # Ctrl+Delete: Clear all (with confirmation)
        self.job_listbox.bind("<Control-Delete>", lambda e: self._on_clear_with_confirm())

    def _on_clear_with_confirm(self) -> None:
        """Clear all with confirmation dialog."""
        if not self._jobs:
            return
        
        from tkinter import messagebox
        if messagebox.askyesno("Clear Queue", f"Remove all {len(self._jobs)} jobs from queue?"):
            self._on_clear()
            self._emit_status_message(f"Cleared {len(self._jobs)} jobs from queue")

    def _select_index(self, index: int) -> None:
        """Select a specific index in the listbox."""
        self.job_listbox.selection_clear(0, tk.END)
        if 0 <= index < len(self._jobs):
            self.job_listbox.selection_set(index)
            self.job_listbox.see(index)
        self._update_button_states()

    def update_jobs(self, jobs: list[UnifiedJobSummary]) -> None:
        """Update the job list display.

        PR-GUI-F2: Displays order numbers and highlights the running job.
        """
        if self._dispatch_to_ui(lambda: self.update_jobs(jobs)):
            return
        # Remember selection
        old_selection = self._get_selected_index()
        old_job_id = (
            self._jobs[old_selection].job_id
            if old_selection is not None and old_selection < len(self._jobs)
            else None
        )

        self._jobs = list(jobs)
        self.job_listbox.delete(0, tk.END)

        # PR-PIPE-002: Get stats service for per-job ETA
        stats_service = None
        if self.controller:
            stats_service = getattr(self.controller, "duration_stats_service", None)

        for i, job in enumerate(self._jobs):
            # PR-GUI-F2: Add 1-based order number prefix
            order_num = i + 1
            base_summary = job.get_display_summary()

            # PR-PIPE-002: Add individual job ETA
            eta_str = ""
            if stats_service:
                estimate = stats_service.get_estimate_for_job(job)
                try:
                    estimate_val = float(estimate) if estimate is not None else None
                except (TypeError, ValueError):
                    estimate_val = None
                if estimate_val:
                    if estimate_val < 60:
                        eta_str = f" ({int(estimate_val)}s)"
                    else:
                        mins = int(estimate_val // 60)
                        eta_str = f" (~{mins}m)"

            # PR-GUI-F2: Mark running job with indicator
            if self._running_job_id and job.job_id == self._running_job_id:
                display_text = f"#{order_num} ▶ {base_summary}{eta_str}"
            else:
                display_text = f"#{order_num}  {base_summary}{eta_str}"

            self.job_listbox.insert(tk.END, display_text)

        # Update count label
        count = len(self._jobs)
        self.count_label.configure(text=f"({count} job{'s' if count != 1 else ''})")

        # PR-PIPE-002: Update ETA label using duration stats
        if count > 0:
            total_seconds, confidence = self._compute_queue_eta()
            eta_text = self._format_queue_eta(total_seconds)
            # Add confidence indicator
            if confidence:
                eta_text = f"{eta_text} {confidence}"
            self.queue_eta_label.configure(text=eta_text)
        else:
            self.queue_eta_label.configure(text="")

        # Restore selection if possible
        if old_job_id:
            for i, job in enumerate(self._jobs):
                if job.job_id == old_job_id:
                    self._select_index(i)
                    break
            else:
                # Job was removed, try to keep similar position
                if old_selection is not None and self._jobs:
                    new_idx = min(old_selection, len(self._jobs) - 1)
                    self._select_index(new_idx)

        self._update_button_states()

    def set_normalized_jobs(self, jobs: list[NormalizedJobRecord]) -> None:
        """Update the job list from NormalizedJobRecord objects.

        Converts each NormalizedJobRecord to UnifiedJobSummary and displays.
        This provides a bridge from JobBuilderV2 output to the queue display.

        Args:
            jobs: List of NormalizedJobRecord instances from JobBuilderV2.
        """
        queue_jobs: list[UnifiedJobSummary] = []
        for record in jobs:
            # Convert NormalizedJobRecord to UnifiedJobSummary
            queue_job = UnifiedJobSummary.from_normalized_record(record)
            queue_jobs.append(queue_job)

        self.update_jobs(queue_jobs)

    def update_from_app_state(self, app_state: Any | None = None) -> None:
        """Update panel from app state."""
        if app_state is None:
            app_state = self.app_state
        if app_state is None:
            return

        # Get queue items from app state
        queue_jobs = getattr(app_state, "queue_jobs", None)
        if queue_jobs:
            self.update_jobs(queue_jobs)
        # Note: queue_items is legacy, we only display UnifiedJobSummary objects now

        # Update queue control states
        is_paused = getattr(app_state, "is_queue_paused", False)
        self._is_queue_paused = is_paused

        auto_run = getattr(app_state, "auto_run_queue", False)
        self._auto_run_enabled = auto_run
        self.auto_run_var.set(auto_run)

        running_job = getattr(app_state, "running_job", None)
        queue_count = len(self._jobs)

        # Update pause/resume button
        self.pause_resume_button.configure(text="Resume Queue" if is_paused else "Pause Queue")

        # Update status label
        self._update_queue_status_display(is_paused, running_job, queue_count)

    # ------------------------------------------------------------------
    # Queue control callbacks (PR-GUI-F1: moved from PipelineRunControlsV2)
    # ------------------------------------------------------------------

    def _on_auto_run_changed(self) -> None:
        """Handle auto-run checkbox change."""
        enabled = self.auto_run_var.get()
        self._auto_run_enabled = enabled
        if self.controller:
            self.controller.on_set_auto_run_v2(enabled)

    def _on_pause_resume(self) -> None:
        """Toggle queue pause state."""
        if self._is_queue_paused:
            if self.controller:
                self.controller.on_resume_queue_v2()
        else:
            if self.controller:
                self.controller.on_pause_queue_v2()

    def _on_send_job(self) -> None:
        """Handle Send Job button click.

        PR-GUI-F3: Dispatches the top job from the queue immediately.
        Respects pause state (JobService handles this).
        """
        if self.controller:
            self.controller.on_queue_send_job_v2()

    def _update_queue_status_display(
        self, is_paused: bool, running_job: Any | None, queue_count: int
    ) -> None:
        """Update the queue status label text and color."""
        if running_job:
            status_text = "Queue: Running job..."
            color = ACCENT_GOLD
        elif is_paused:
            status_text = f"Queue: Paused ({queue_count} pending)"
            color = ASWF_ERROR_RED
        elif queue_count > 0:
            status_text = f"Queue: {queue_count} job{'s' if queue_count != 1 else ''} pending"
            color = TEXT_PRIMARY
        else:
            status_text = "Queue: Idle"
            color = TEXT_PRIMARY
        self.queue_status_label.configure(text=status_text, foreground=color)

    def update_queue_status(self, status: str | None) -> None:
        """Update the queue status from a status string.

        This provides an API compatible with the old PreviewPanelV2.update_queue_status().
        """
        if self._dispatch_to_ui(lambda: self.update_queue_status(status)):
            return
        normalized = (status or "idle").lower()
        if normalized == "running":
            color = ACCENT_GOLD
        elif normalized == "paused":
            color = ASWF_ERROR_RED
        else:
            color = TEXT_PRIMARY
        self.queue_status_label.configure(
            text=f"Queue: {normalized.title()}",
            foreground=color,
        )

    def refresh_states(self) -> None:
        """Refresh control states from current app state."""
        self.update_from_app_state(self.app_state)

    # ------------------------------------------------------------------
    # PR-GUI-F2: Running Job Integration
    # ------------------------------------------------------------------

    def set_running_job(self, job: UnifiedJobSummary | None) -> None:
        """Set the currently running job for highlighting in the queue list.

        PR-GUI-F2: When a job is running, its entry in the queue list
        is visually distinguished with a ▶ indicator.

        Args:
            job: The running UnifiedJobSummary, or None if no job is running.
        """
        if self._dispatch_to_ui(lambda: self.set_running_job(job)):
            return
        new_id = job.job_id if job else None
        if new_id != self._running_job_id:
            self._running_job_id = new_id
            # Refresh the display to show/hide the running indicator
            self.update_jobs(self._jobs)

    def get_running_job_queue_position(self) -> int | None:
        """Get the 1-based queue position of the running job, if present.

        PR-GUI-F2: Returns the order number of the running job in the queue,
        or None if the running job is not in the queue list.
        """
        if not self._running_job_id:
            return None
        for i, job in enumerate(self._jobs):
            if job.job_id == self._running_job_id:
                return i + 1  # 1-based
        return None

    # -------------------------------------------------------------------------
    # PR-D: DTO-based Queue Management
    # -------------------------------------------------------------------------

    def upsert_job(self, dto: JobQueueItemDTO) -> None:
        """Add or update a job in the queue based on DTO.

        PR-D: Core method for queue panel updates via JobService callbacks.

        Args:
            dto: JobQueueItemDTO with current job state
        """
        if self._dispatch_to_ui(lambda: self.upsert_job(dto)):
            return
        # Check if job already exists
        for i, job in enumerate(self._jobs):
            if job.job_id == dto.job_id:
                # Job already in list - update_jobs will be called by controller
                # We don't modify in place since UnifiedJobSummary is frozen
                return

        # Job not found - this method is deprecated in favor of update_jobs with full list
        # Just trigger a refresh from app state
        logger.warning(f"upsert_job called for new job {dto.job_id} - should use update_jobs instead")
        self.update_from_app_state()

    def remove_job(self, job_id: str) -> None:
        """Remove a job from the queue by ID.

        PR-D: Core method for removing completed/cancelled jobs.

        Args:
            job_id: The job ID to remove
        """
        if self._dispatch_to_ui(lambda: self.remove_job(job_id)):
            return
        self._jobs = [job for job in self._jobs if job.job_id != job_id]
        self.update_jobs(self._jobs)

    # -------------------------------------------------------------------------
    # PR-CORE-D: Lifecycle Event Integration
    # -------------------------------------------------------------------------

    def _on_lifecycle_event(self) -> None:
        """Handle lifecycle events from app_state (PR-CORE-D).

        Responds to SUBMITTED, QUEUED, RUNNING, CANCELLED events.
        """
        if not self.app_state:
            return

        log_events = getattr(self.app_state, "log_events", None)
        if not log_events:
            return

        # Process the most recent event
        if log_events:
            latest_event = log_events[-1]
            event_type = getattr(latest_event, "event_type", None)
            job_id = getattr(latest_event, "job_id", None)

            if event_type == "RUNNING" and job_id:
                self._running_job_id = job_id
                self._refresh_display()
            elif event_type in ("COMPLETED", "FAILED", "CANCELLED") and job_id:
                # Remove from queue display if completed/failed/cancelled
                self.remove_job(job_id)
                if self._running_job_id == job_id:
                    self._running_job_id = None
                self._refresh_display()

    def _on_queue_jobs_changed(self) -> None:
        """Handle queue_jobs changes from app_state (PR-CORE-D)."""
        if not self.app_state:
            return

        queue_jobs = getattr(self.app_state, "queue_jobs", None)
        if queue_jobs is not None:
            self.update_jobs(queue_jobs)

    def _on_queue_summaries_changed(self) -> None:
        """Handle queue summaries changes (legacy compatibility)."""
        # Fallback to queue_jobs if available
        self._on_queue_jobs_changed()

    def _refresh_display(self) -> None:
        """Refresh the queue list using the current app_state snapshot."""
        if not self.app_state:
            return
        queue_jobs = getattr(self.app_state, "queue_jobs", None) or []
        try:
            self.update_jobs(queue_jobs)
        except Exception as exc:
            logger.debug(f"[QueuePanelV2] Failed to refresh display: {exc}")

    def _on_running_summary_changed(self) -> None:
        """Handle running job summary changes (legacy compatibility)."""
        if not self.app_state:
            return

        running_job = getattr(self.app_state, "running_job", None)
        if running_job:
            self._running_job_id = getattr(running_job, "job_id", None)
            self._refresh_display()

    @staticmethod
    def _format_queue_item_with_pack_metadata(summary: UnifiedJobSummary) -> str:
        """PR-CORE-D: Format queue item with PromptPack metadata.

        Args:
            summary: UnifiedJobSummary with PromptPack provenance

        Returns:
            Formatted string like "Row 3: Angelic Warriors v2/b1 Seed: 12345"
        """
        parts = []

        # Row index FIRST for easy distinction
        row_idx = getattr(summary, "prompt_pack_row_index", None)
        if row_idx is not None:
            parts.append(f"Row {row_idx + 1}:")

        # Pack name
        pack_name = getattr(summary, "prompt_pack_name", None)
        if pack_name:
            parts.append(pack_name)

        # Variant/batch indices
        variant_idx = getattr(summary, "variant_index", None)
        batch_idx = getattr(summary, "batch_index", None)
        if variant_idx is not None or batch_idx is not None:
            v_text = f"v{variant_idx + 1}" if variant_idx is not None else "v?"
            b_text = f"b{batch_idx + 1}" if batch_idx is not None else "b?"
            parts.append(f"[{v_text}/{b_text}]")

        # Seed
        seed = getattr(summary, "seed", None)
        if seed is not None and seed != -1:
            parts.append(f"Seed:{seed}")

        return " ".join(parts) if parts else "Unknown Job"


__all__ = ["QueuePanelV2"]
