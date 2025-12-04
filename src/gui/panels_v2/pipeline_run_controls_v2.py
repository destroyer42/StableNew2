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
            print(f"[PipelineRunControlsV2] No controller for {method_name}")
            return
        method = getattr(controller, method_name, None)
        if callable(method):
            try:
                print(f"[PipelineRunControlsV2] Calling {method_name}")
                method()
                print(f"[PipelineRunControlsV2] {method_name} completed")
            except Exception as exc:
                print(f"[PipelineRunControlsV2] {method_name} error: {exc!r}")
                import traceback
                traceback.print_exc()
        else:
            print(f"[PipelineRunControlsV2] {method_name} not found on controller")

    def _on_run_clicked(self) -> None:
        controller = self.controller
        if not controller:
            print("[PipelineRunControlsV2] No controller for start_run_v2")
            return
        method = getattr(controller, "start_run_v2", None)
        if callable(method):
            try:
                print("[PipelineRunControlsV2] Calling start_run_v2")
                method()
                print("[PipelineRunControlsV2] start_run_v2 completed")
            except Exception as exc:
                print(f"[PipelineRunControlsV2] start_run_v2 error: {exc!r}")
                import traceback
                traceback.print_exc()
        else:
            print("[PipelineRunControlsV2] start_run_v2 not found on controller")

    def _on_stop_clicked(self) -> None:
        controller = self.controller
        if not controller:
            print("[PipelineRunControlsV2] No controller for on_stop_clicked")
            return
        method = getattr(controller, "on_stop_clicked", None)
        if callable(method):
            try:
                print("[PipelineRunControlsV2] Calling on_stop_clicked")
                method()
                print("[PipelineRunControlsV2] on_stop_clicked completed")
            except Exception as exc:
                print(f"[PipelineRunControlsV2] on_stop_clicked error: {exc!r}")
                import traceback
                traceback.print_exc()
        else:
            print("[PipelineRunControlsV2] on_stop_clicked not found on controller")

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

    def refresh_states(self) -> None:
        """Refresh button enable/disable states based on AppStateV2 run flags.

        Rules (PR-111):
        - Run Now: disabled during direct run
        - Run: disabled when queue paused OR direct run in progress
        - Add to Queue: disabled when no pack selected OR queue paused
        - Stop: enabled only when run in progress
        - Clear Draft: always enabled
        """
        app_state = self.app_state
        if app_state is None:
            return

        is_run_in_progress = getattr(app_state, "is_run_in_progress", False)
        is_direct_run = getattr(app_state, "is_direct_run_in_progress", False)
        is_queue_paused = getattr(app_state, "is_queue_paused", False)
        current_pack = getattr(app_state, "current_pack", None)
        has_pack = bool(current_pack)

        try:
            # Run Now: disabled during direct run
            run_now_disabled = is_direct_run
            self.run_now_button.configure(state="disabled" if run_now_disabled else "normal")

            # Run: disabled when queue paused OR direct run in progress
            run_disabled = is_queue_paused or is_direct_run
            self.run_button.configure(state="disabled" if run_disabled else "normal")

            # Add to Queue: disabled when no pack selected OR queue paused
            add_disabled = (not has_pack) or is_queue_paused
            self.add_button.configure(state="disabled" if add_disabled else "normal")

            # Stop: enabled only when run in progress
            self.stop_button.configure(state="normal" if is_run_in_progress else "disabled")

            # Clear Draft: always enabled
            self.clear_draft_button.configure(state="normal")
        except Exception:
            pass
