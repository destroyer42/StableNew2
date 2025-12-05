"""V2 Queue Panel - displays ordered job list with manipulation controls."""

from __future__ import annotations

import tkinter as tk
from tkinter import ttk
from typing import Any

from src.gui.theme_v2 import (
    SECONDARY_BUTTON_STYLE,
    STATUS_STRONG_LABEL_STYLE,
    SURFACE_FRAME_STYLE,
)
from src.pipeline.job_models_v2 import QueueJobV2


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
        **kwargs,
    ):
        super().__init__(master, style=SURFACE_FRAME_STYLE, padding=(8, 8, 8, 8), **kwargs)
        self.controller = controller
        self.app_state = app_state
        self._jobs: list[QueueJobV2] = []

        # Title row
        title_frame = ttk.Frame(self, style=SURFACE_FRAME_STYLE)
        title_frame.pack(fill="x", pady=(0, 4))

        title = ttk.Label(title_frame, text="Queue", style=STATUS_STRONG_LABEL_STYLE)
        title.pack(side="left")

        self.count_label = ttk.Label(title_frame, text="(0 jobs)", style=STATUS_STRONG_LABEL_STYLE)
        self.count_label.pack(side="left", padx=(8, 0))

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
        button_frame.columnconfigure((0, 1, 2, 3), weight=1)

        self.move_up_button = ttk.Button(
            button_frame,
            text="▲ Up",
            style=SECONDARY_BUTTON_STYLE,
            command=self._on_move_up,
            width=8,
        )
        self.move_up_button.grid(row=0, column=0, sticky="ew", padx=(0, 2))

        self.move_down_button = ttk.Button(
            button_frame,
            text="▼ Down",
            style=SECONDARY_BUTTON_STYLE,
            command=self._on_move_down,
            width=8,
        )
        self.move_down_button.grid(row=0, column=1, sticky="ew", padx=(2, 2))

        self.remove_button = ttk.Button(
            button_frame,
            text="Remove",
            style=SECONDARY_BUTTON_STYLE,
            command=self._on_remove,
            width=8,
        )
        self.remove_button.grid(row=0, column=2, sticky="ew", padx=(2, 2))

        self.clear_button = ttk.Button(
            button_frame,
            text="Clear All",
            style=SECONDARY_BUTTON_STYLE,
            command=self._on_clear,
            width=8,
        )
        self.clear_button.grid(row=0, column=3, sticky="ew", padx=(2, 0))

        # Initial button state
        self._update_button_states()

    def _on_selection_changed(self, event: tk.Event | None = None) -> None:
        """Handle selection change in the listbox."""
        self._update_button_states()

    def _get_selected_index(self) -> int | None:
        """Get the currently selected index, or None if nothing selected."""
        selection = self.job_listbox.curselection()
        if selection:
            return selection[0]
        return None

    def _get_selected_job(self) -> QueueJobV2 | None:
        """Get the currently selected job, or None if nothing selected."""
        idx = self._get_selected_index()
        if idx is not None and 0 <= idx < len(self._jobs):
            return self._jobs[idx]
        return None

    def _update_button_states(self) -> None:
        """Update button enabled/disabled states based on selection and queue contents."""
        idx = self._get_selected_index()
        has_selection = idx is not None
        has_jobs = len(self._jobs) > 0

        # Move up: enabled if selection is not first
        can_move_up = has_selection and idx > 0
        self.move_up_button.state(["!disabled"] if can_move_up else ["disabled"])

        # Move down: enabled if selection is not last
        can_move_down = has_selection and idx < len(self._jobs) - 1
        self.move_down_button.state(["!disabled"] if can_move_down else ["disabled"])

        # Remove: enabled if something is selected
        self.remove_button.state(["!disabled"] if has_selection else ["disabled"])

        # Clear: enabled if there are any jobs
        self.clear_button.state(["!disabled"] if has_jobs else ["disabled"])

    def _on_move_up(self) -> None:
        """Move the selected job up in the queue."""
        job = self._get_selected_job()
        if job and self.controller:
            method = getattr(self.controller, "on_queue_move_up_v2", None)
            if callable(method):
                method(job.job_id)
                # Maintain selection after move
                idx = self._get_selected_index()
                if idx is not None and idx > 0:
                    self._select_index(idx - 1)

    def _on_move_down(self) -> None:
        """Move the selected job down in the queue."""
        job = self._get_selected_job()
        if job and self.controller:
            method = getattr(self.controller, "on_queue_move_down_v2", None)
            if callable(method):
                method(job.job_id)
                # Maintain selection after move
                idx = self._get_selected_index()
                if idx is not None and idx < len(self._jobs) - 1:
                    self._select_index(idx + 1)

    def _on_remove(self) -> None:
        """Remove the selected job from the queue."""
        job = self._get_selected_job()
        if job and self.controller:
            method = getattr(self.controller, "on_queue_remove_job_v2", None)
            if callable(method):
                method(job.job_id)

    def _on_clear(self) -> None:
        """Clear all jobs from the queue."""
        if self.controller:
            method = getattr(self.controller, "on_queue_clear_v2", None)
            if callable(method):
                method()

    def _select_index(self, index: int) -> None:
        """Select a specific index in the listbox."""
        self.job_listbox.selection_clear(0, tk.END)
        if 0 <= index < len(self._jobs):
            self.job_listbox.selection_set(index)
            self.job_listbox.see(index)
        self._update_button_states()

    def update_jobs(self, jobs: list[QueueJobV2]) -> None:
        """Update the job list display."""
        # Remember selection
        old_selection = self._get_selected_index()
        old_job_id = self._jobs[old_selection].job_id if old_selection is not None and old_selection < len(self._jobs) else None

        self._jobs = list(jobs)
        self.job_listbox.delete(0, tk.END)

        for job in self._jobs:
            display_text = job.get_display_summary()
            self.job_listbox.insert(tk.END, display_text)

        # Update count label
        count = len(self._jobs)
        self.count_label.configure(text=f"({count} job{'s' if count != 1 else ''})")

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

    def update_from_app_state(self, app_state: Any | None = None) -> None:
        """Update panel from app state."""
        if app_state is None:
            app_state = self.app_state
        if app_state is None:
            return

        # Get queue items from app state
        queue_items = getattr(app_state, "queue_items", None)
        if queue_items is not None:
            self.update_jobs(queue_items)


__all__ = ["QueuePanelV2"]
