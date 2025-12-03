"""Mini panel for pipeline queue/run controls in the V2 layout."""

from __future__ import annotations

import tkinter as tk
from tkinter import ttk
from typing import Any

from src.gui.theme_v2 import (
    SECONDARY_BUTTON_STYLE,
    PRIMARY_BUTTON_STYLE,
    STATUS_STRONG_LABEL_STYLE,
    SURFACE_FRAME_STYLE,
)


class PipelineRunControlsV2(ttk.Frame):
    """Queue/run controls displayed next to the preview panel."""

    def __init__(self, master: tk.Misc, *, controller: Any | None = None, app_state: Any | None = None, theme: Any | None = None, **kwargs):
        super().__init__(master, style=SURFACE_FRAME_STYLE, padding=(0, 0, 0, 0), **kwargs)
        self.controller = controller
        self.app_state = app_state
        self.theme = theme
        self._current_run_mode = "direct"
        self._is_running = False

        title = ttk.Label(self, text="Run Controls", style=STATUS_STRONG_LABEL_STYLE)
        title.grid(row=0, column=0, sticky="w", pady=(0, 4))

        self.mode_label = ttk.Label(self, text="Mode: Direct", style=STATUS_STRONG_LABEL_STYLE)
        self.mode_label.grid(row=1, column=0, sticky="w")

        buttons_frame = ttk.Frame(self, style=SURFACE_FRAME_STYLE)
        buttons_frame.grid(row=2, column=0, sticky="ew", pady=(4, 0))
        buttons_frame.columnconfigure((0, 1, 2), weight=1)

        self.add_button = ttk.Button(
            buttons_frame,
            text="Add to Queue",
            style=SECONDARY_BUTTON_STYLE,
            command=lambda: self._invoke_controller("on_add_job_to_queue_v2"),
        )
        self.add_button.grid(row=0, column=0, sticky="ew", padx=(0, 4))

        self.run_now_button = ttk.Button(
            buttons_frame,
            text="Run Now",
            style=SECONDARY_BUTTON_STYLE,
            command=lambda: self._invoke_controller("on_run_job_now_v2"),
        )
        self.run_now_button.grid(row=0, column=1, sticky="ew", padx=(0, 4))

        self.run_button = ttk.Button(
            buttons_frame,
            text="Run",
            style=PRIMARY_BUTTON_STYLE,
            command=self._on_run_clicked,
        )
        self.run_button.grid(row=0, column=2, sticky="ew")

        self.stop_button = ttk.Button(
            buttons_frame,
            text="Stop",
            style=SECONDARY_BUTTON_STYLE,
            command=self._on_stop_clicked,
        )
        self.stop_button.grid(row=1, column=2, sticky="ew", pady=(8, 0))

        self.clear_draft_button = ttk.Button(
            buttons_frame,
            text="Clear Draft",
            style=SECONDARY_BUTTON_STYLE,
            command=lambda: self._invoke_controller("on_clear_job_draft"),
        )
        self.clear_draft_button.grid(row=1, column=0, columnspan=2, sticky="ew", pady=(8, 0))

        self.update_from_app_state(self.app_state)

    def _invoke_controller(self, method_name: str) -> None:
        controller = self.controller
        if not controller:
            return
        method = getattr(controller, method_name, None)
        if callable(method):
            try:
                method()
            except Exception:
                pass

    def _on_run_clicked(self) -> None:
        controller = self.controller
        if not controller:
            return
        method = getattr(controller, "start_run_v2", None)
        if callable(method):
            try:
                method()
            except Exception:
                pass

    def _on_stop_clicked(self) -> None:
        controller = self.controller
        if not controller:
            return
        method = getattr(controller, "on_stop_clicked", None)
        if callable(method):
            try:
                method()
            except Exception:
                pass

    def update_from_app_state(self, app_state: Any | None) -> None:
        """Refresh UI to reflect run mode and queue/running state."""
        if app_state is None:
            return

        pipeline_state = getattr(app_state, "pipeline_state", None)
        run_mode = (getattr(pipeline_state, "run_mode", None) or "direct").strip().lower() if pipeline_state else "direct"
        if run_mode not in {"direct", "queue"}:
            run_mode = "direct"
        queue_status = getattr(app_state, "queue_status", "idle")
        running_job = getattr(app_state, "running_job", None)
        self._current_run_mode = run_mode
        self._is_running = bool(running_job) or queue_status in ("running", "busy")

        self._apply_run_mode_to_ui()
        self._apply_running_state_to_ui()

    def _apply_run_mode_to_ui(self) -> None:
        mode = self._current_run_mode
        try:
            self.mode_label.configure(text=f"Mode: {'Direct' if mode == 'direct' else 'Queue'}")
        except Exception:
            pass

        try:
            if mode == "direct":
                self.run_button.configure(style=PRIMARY_BUTTON_STYLE)
                self.run_now_button.configure(style=SECONDARY_BUTTON_STYLE)
                self.add_button.configure(style=SECONDARY_BUTTON_STYLE)
            else:
                self.run_button.configure(style=SECONDARY_BUTTON_STYLE)
                self.run_now_button.configure(style=PRIMARY_BUTTON_STYLE)
                self.add_button.configure(style=PRIMARY_BUTTON_STYLE)
        except Exception:
            pass

    def _apply_running_state_to_ui(self) -> None:
        is_running = self._is_running
        try:
            self.run_button.configure(state="disabled" if is_running else "normal")
            self.run_now_button.configure(state="disabled" if is_running else "normal")
            self.add_button.configure(state="normal")
            self.stop_button.configure(state="normal" if is_running else "disabled")
        except Exception:
            pass
