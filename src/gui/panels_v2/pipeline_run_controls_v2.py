"""Mini panel for pipeline queue/run controls in the V2 layout.

PR-203: Simplified controls - everything goes through the queue.
No more Mode: Direct/Queue confusion.
"""

from __future__ import annotations

import tkinter as tk
from tkinter import ttk
from typing import Any

from src.gui.theme_v2 import (
    SECONDARY_BUTTON_STYLE,
    STATUS_STRONG_LABEL_STYLE,
    SURFACE_FRAME_STYLE,
)


class PipelineRunControlsV2(ttk.Frame):
    """
    Simplified queue/run controls for V2.
    
    All jobs go through the queue - no direct mode.
    
    Controls:
    - Auto-run queue: checkbox to run next job automatically
    - Pause/Resume: toggle queue processing
    """

    def __init__(
        self,
        master: tk.Misc,
        *,
        controller: Any | None = None,
        app_state: Any | None = None,
        theme: Any | None = None,
        **kwargs: Any,
    ) -> None:
        super().__init__(master, style=SURFACE_FRAME_STYLE, padding=(8, 8, 8, 8), **kwargs)
        self.controller = controller
        self.app_state = app_state
        self.theme = theme
        self._is_queue_paused = False
        self._auto_run_enabled = False

        # Title
        title = ttk.Label(self, text="Run Controls", style=STATUS_STRONG_LABEL_STYLE)
        title.pack(fill="x", pady=(0, 8))

        # Options row
        options_frame = ttk.Frame(self, style=SURFACE_FRAME_STYLE)
        options_frame.pack(fill="x", pady=(0, 8))

        self.auto_run_var = tk.BooleanVar(value=False)
        self.auto_run_check = ttk.Checkbutton(
            options_frame,
            text="Auto-run queue",
            variable=self.auto_run_var,
            command=self._on_auto_run_changed,
        )
        self.auto_run_check.pack(side="left")

        # Pause/Resume toggle
        self.pause_resume_button = ttk.Button(
            options_frame,
            text="Pause Queue",
            style=SECONDARY_BUTTON_STYLE,
            command=self._on_pause_resume,
            width=12,
        )
        self.pause_resume_button.pack(side="right")

        # Status label
        self.status_label = ttk.Label(self, text="Queue: Idle")
        self.status_label.pack(fill="x", pady=(4, 0))

        self.update_from_app_state(self.app_state)

    def _invoke_controller(self, method_name: str, *args: Any) -> Any:
        """Safely invoke a controller method."""
        controller = self.controller
        if not controller:
            print(f"[PipelineRunControlsV2] No controller for {method_name}")
            return None
        method = getattr(controller, method_name, None)
        if callable(method):
            try:
                return method(*args)
            except Exception as exc:
                print(f"[PipelineRunControlsV2] {method_name} error: {exc!r}")
                import traceback
                traceback.print_exc()
        else:
            print(f"[PipelineRunControlsV2] {method_name} not found on controller")
        return None

    def _on_auto_run_changed(self) -> None:
        """Handle auto-run checkbox change."""
        enabled = self.auto_run_var.get()
        self._auto_run_enabled = enabled
        self._invoke_controller("on_set_auto_run_v2", enabled)

    def _on_pause_resume(self) -> None:
        """Toggle queue pause state."""
        if self._is_queue_paused:
            self._invoke_controller("on_resume_queue_v2")
        else:
            self._invoke_controller("on_pause_queue_v2")

    def update_from_app_state(self, app_state: Any | None = None) -> None:
        """Refresh UI to reflect queue state."""
        if app_state is None:
            app_state = self.app_state
        if app_state is None:
            return

        # Queue pause state
        is_paused = getattr(app_state, "is_queue_paused", False)
        self._is_queue_paused = is_paused

        # Auto-run state
        auto_run = getattr(app_state, "auto_run_queue", False)
        self._auto_run_enabled = auto_run
        self.auto_run_var.set(auto_run)

        # Running state
        running_job = getattr(app_state, "running_job", None)
        queue_items = getattr(app_state, "queue_items", [])
        queue_count = len(queue_items) if queue_items else 0

        # Update pause/resume button
        self.pause_resume_button.configure(
            text="Resume Queue" if is_paused else "Pause Queue"
        )

        # Update status label
        if running_job:
            status_text = "Queue: Running job..."
        elif is_paused:
            status_text = f"Queue: Paused ({queue_count} pending)"
        elif queue_count > 0:
            status_text = f"Queue: {queue_count} job{'s' if queue_count != 1 else ''} pending"
        else:
            status_text = "Queue: Idle"
        self.status_label.configure(text=status_text)

    def refresh_states(self) -> None:
        """Refresh button states from current app state."""
        self.update_from_app_state(self.app_state)


__all__ = ["PipelineRunControlsV2"]
