"""Status bar scaffold for GUI v2."""

from __future__ import annotations

import tkinter as tk
from tkinter import ttk

from src.gui.theme_v2 import SURFACE_FRAME_STYLE, STATUS_LABEL_STYLE, STATUS_STRONG_LABEL_STYLE, PADDING_SM
from .api_status_panel import APIStatusPanel, resolve_webui_state_display
from src.controller.webui_connection_controller import WebUIConnectionController, WebUIConnectionState


class StatusBarV2(ttk.Frame):
    """Status/ETA/progress container."""

    def __init__(self, master: tk.Misc, *, controller=None, theme=None, app_state=None, **kwargs) -> None:
        super().__init__(master, style=SURFACE_FRAME_STYLE, padding=PADDING_SM, **kwargs)
        self.controller = controller
        self.theme = theme
        self._has_validation_error = False
        self.app_state = app_state
        self.header_label = ttk.Label(self, text="Status", style=STATUS_LABEL_STYLE)
        self.header_label.pack(anchor=tk.W)

        self.body = ttk.Frame(self, style=SURFACE_FRAME_STYLE)
        self.body.pack(fill=tk.BOTH, expand=True)

        self.body_left = ttk.Frame(self.body, style=SURFACE_FRAME_STYLE)
        self.body_left.pack(side=tk.LEFT, fill=tk.X, expand=True)

        self.status_label = ttk.Label(
            self.body_left,
            text="Idle",
            style=STATUS_STRONG_LABEL_STYLE,
        )
        self.status_label.pack(side=tk.LEFT, padx=(0, 10))

        self.progress_bar = ttk.Progressbar(
            self.body_left,
            orient=tk.HORIZONTAL,
            mode="determinate",
            maximum=100,
            length=150,
            style="Horizontal.TProgressbar",
        )
        self.progress_bar.pack(side=tk.LEFT, fill=tk.X, expand=True)

        self.eta_label = ttk.Label(
            self.body_left,
            text="",
            style=STATUS_LABEL_STYLE,
        )
        self.eta_label.pack(side=tk.LEFT, padx=10)

        # WebUI status/controls on the right side of the same bar
        self.webui_panel = APIStatusPanel(self.body, style=SURFACE_FRAME_STYLE)
        self.webui_panel.pack(side=tk.RIGHT, padx=(8, 0))

        self._webui_controller: WebUIConnectionController | None = None

        self.set_idle()
        self._launch_button = self.webui_panel.launch_button
        self._retry_button = self.webui_panel.retry_button
        if self.controller:
            if hasattr(self.controller, "on_launch_webui_clicked"):
                self.webui_panel.set_launch_callback(self.controller.on_launch_webui_clicked)
            if hasattr(self.controller, "on_retry_webui_clicked"):
                self.webui_panel.set_retry_callback(self.controller.on_retry_webui_clicked)
        if app_state is not None:
            try:
                app_state.subscribe("status_text", self._sync_status_text)
            except Exception:
                pass

    # Status helpers -------------------------------------------------

    def set_idle(self) -> None:
        if self._has_validation_error:
            return
        self.status_label.config(text="Idle")
        self.update_progress(0.0)
        self.update_eta(None)

    def set_running(self) -> None:
        if self._has_validation_error:
            return
        self.status_label.config(text="Running...")

    def set_completed(self) -> None:
        if self._has_validation_error:
            return
        self.status_label.config(text="Completed")

    def set_error(self, message: str | None = None) -> None:
        if self._has_validation_error:
            return
        text = "Error"
        if message:
            cleaned = str(message).strip()
            if cleaned:
                text = f"Error: {cleaned}"
        self.status_label.config(text=text)

    # Progress / ETA helpers -----------------------------------------

    def update_progress(self, fraction: float | None = None) -> None:
        if fraction is None:
            fraction = 0.0
        try:
            value = float(fraction)
        except (TypeError, ValueError):
            value = 0.0
        value = max(0.0, min(1.0, value))
        self.progress_bar["value"] = value * 100.0

    def update_eta(self, seconds: float | None = None) -> None:
        if seconds is None:
            self.eta_label.config(text="")
            return
        try:
            total_seconds = max(0.0, float(seconds))
        except (TypeError, ValueError):
            self.eta_label.config(text="")
            return
        mins = int(total_seconds // 60)
        secs = int(total_seconds % 60)
        self.eta_label.config(text=f"ETA: {mins:02d}:{secs:02d}")

    def set_validation_error(self, message: str) -> None:
        self._has_validation_error = True
        self.status_label.config(text=f"Config Error: {message}")
        self.update_progress(0.0)
        self.update_eta(None)

    def clear_validation_error(self) -> None:
        if not self._has_validation_error:
            return
        self._has_validation_error = False
        self.set_idle()

    def set_webui_launch_callback(self, callback) -> None:
        if getattr(self, "webui_panel", None):
            try:
                self.webui_panel.set_launch_callback(callback)
            except Exception:
                pass

    def set_webui_retry_callback(self, callback) -> None:
        if getattr(self, "webui_panel", None):
            try:
                self.webui_panel.set_retry_callback(callback)
            except Exception:
                pass

    def attach_webui_connection_controller(self, connection_controller: WebUIConnectionController | None) -> None:
        if connection_controller is None:
            return
        self._webui_controller = connection_controller
        controller = getattr(self, "controller", None)
        callback = getattr(controller, "on_webui_ready", None)
        if callable(callback):
            connection_controller.register_on_ready(callback)

    def update_status(
        self,
        text: str | None = None,
        progress: float | None = None,
        eta: str | float | None = None,
    ) -> None:
        """Update the primary status lane."""
        if text is not None:
            self.status_label.config(text=text)
        if progress is not None:
            self.update_progress(progress)
        if eta is not None:
            # Accept either preformatted string or seconds.
            try:
                if isinstance(eta, str):
                    self.eta_label.config(text=eta)
                else:
                    self.update_eta(float(eta))
            except Exception:
                self.eta_label.config(text="")

    def update_webui_state(self, state: str | WebUIConnectionState | None) -> None:
        """Reflect WebUI connection state with a compact indicator."""
        state_enum, status_text, _ = resolve_webui_state_display(state)
        if state_enum is not None:
            state_key = state_enum.value
        else:
            try:
                state_key = str(state).lower()
            except Exception:
                state_key = ""
        if state_key == "connected":
            self._launch_button.state(["disabled"])
            self._retry_button.state(["disabled"])
        elif state_key == "connecting":
            self._launch_button.state(["disabled"])
            self._retry_button.state(["!disabled"])
        elif state_key == "error":
            self._launch_button.state(["!disabled"])
            self._retry_button.state(["!disabled"])
        else:
            self._launch_button.state(["!disabled"])
            self._retry_button.state(["!disabled"])
        fallback_state = state if state is not None else WebUIConnectionState.DISCONNECTED
        try:
            self.webui_panel.set_webui_state(fallback_state)
        except Exception:
            pass

    def _sync_status_text(self) -> None:
        if self.app_state is None:
            return
        try:
            text = getattr(self.app_state, "status_text", "")
            if text:
                self.status_label.config(text=text)
        except Exception:
            pass
