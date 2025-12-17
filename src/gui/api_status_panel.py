"""
APIStatusPanel - UI component for displaying API connection status.

Shows current WebUI/API connection health and exposes launch/retry hooks.
"""

from __future__ import annotations

import logging
import tkinter as tk
from tkinter import ttk

from src.controller.webui_connection_controller import WebUIConnectionState

from . import theme as theme_mod

logger = logging.getLogger(__name__)

WEBUI_STATUS_DISPLAY: dict[WebUIConnectionState, tuple[str, str]] = {
    WebUIConnectionState.READY: ("WebUI: Ready", "green"),
    WebUIConnectionState.CONNECTING: ("WebUI: Connecting", "yellow"),
    WebUIConnectionState.ERROR: ("WebUI: Error", "red"),
    WebUIConnectionState.DISCONNECTED: ("WebUI: Disconnected", "orange"),
    WebUIConnectionState.DISABLED: ("WebUI: Disabled", "gray"),
}


def resolve_webui_state_display(
    state: WebUIConnectionState | str | None,
) -> tuple[WebUIConnectionState | None, str, str]:
    """Normalize a WebUI state into the enum, text label, and color."""
    normalized_state: WebUIConnectionState | None = None
    text = "WebUI: Unknown"
    color = "gray"
    try:
        if isinstance(state, WebUIConnectionState):
            normalized_state = state
        elif state is not None:
            normalized_state = WebUIConnectionState(str(state).strip().lower())
    except Exception:
        normalized_state = None
    if normalized_state in WEBUI_STATUS_DISPLAY:
        text, color = WEBUI_STATUS_DISPLAY[normalized_state]
    return normalized_state, text, color


class APIStatusPanel(ttk.Frame):
    """A UI panel for API connection status display."""

    def __init__(self, parent: tk.Widget, coordinator: object | None = None, **kwargs):
        super().__init__(parent, **kwargs)
        self.parent = parent
        self.coordinator = coordinator
        self._reconnect_callback = None
        self._launch_callback = None
        self._retry_callback = None
        self._build_ui()

    def _build_ui(self):
        surface_style = getattr(theme_mod, "SURFACE_FRAME_STYLE", "Dark.TFrame")
        status_frame = ttk.Frame(self, style=surface_style, relief=tk.SUNKEN)
        status_frame.pack(fill=tk.X, expand=True)

        self.status_indicator = ttk.Label(
            status_frame,
            text="?",
            style=getattr(theme_mod, "STATUS_STRONG_LABEL_STYLE", "Dark.TLabel"),
            foreground="#888888",
            font=("Segoe UI", 12, "bold"),
        )
        self.status_indicator.pack(side=tk.LEFT, padx=(5, 2))

        self.status_label = ttk.Label(
            status_frame,
            text="Not connected",
            style=getattr(theme_mod, "STATUS_LABEL_STYLE", "Dark.TLabel"),
            font=("Segoe UI", 9),
        )
        self.status_label.pack(side=tk.LEFT, padx=(2, 5))

        button_frame = ttk.Frame(status_frame, style=surface_style)
        button_frame.pack(side=tk.RIGHT, padx=(6, 4))
        self.launch_button = ttk.Button(
            button_frame,
            text="Launch WebUI",
            command=self._on_launch_clicked,
            style=getattr(theme_mod, "PRIMARY_BUTTON_STYLE", "TButton"),
        )
        self.launch_button.pack(side=tk.LEFT, padx=(0, 4))
        self.retry_button = ttk.Button(
            button_frame,
            text="Retry",
            command=self._on_retry_clicked,
            style=getattr(theme_mod, "GHOST_BUTTON_STYLE", "TButton"),
        )
        self.retry_button.pack(side=tk.LEFT, padx=(0, 0))

    def set_status(self, text: str, color: str = "gray") -> None:
        color_map = {
            "green": "#4CAF50",
            "yellow": "#FF9800",
            "orange": "#FF9800",
            "red": "#f44336",
            "gray": "#888888",
            "grey": "#888888",
        }
        hex_color = color_map.get(color.lower(), color)
        self.status_indicator.config(foreground=hex_color)
        self.status_label.config(text=text)
        try:
            self.update_idletasks()
        except Exception:
            pass
        logger.debug("API status set to: %s (%s)", text, color)

    def set_webui_state(self, state: WebUIConnectionState | str | None) -> None:
        _, text, color = resolve_webui_state_display(state)
        self.set_status(text, color=color)

    def set_reconnect_callback(self, callback):
        self._reconnect_callback = callback

    def set_launch_callback(self, callback):
        self._launch_callback = callback

    def set_retry_callback(self, callback):
        self._retry_callback = callback

    def _on_reconnect_clicked(self):
        if callable(self._reconnect_callback):
            try:
                self._reconnect_callback()
            except Exception:
                logger.debug("Reconnect callback failed", exc_info=True)

    def _on_launch_clicked(self):
        if callable(self._launch_callback):
            try:
                self._launch_callback()
            except Exception:
                logger.debug("Launch callback failed", exc_info=True)

    def _on_retry_clicked(self):
        if callable(self._retry_callback):
            try:
                self._retry_callback()
            except Exception:
                logger.debug("Retry callback failed", exc_info=True)


__all__ = ["APIStatusPanel", "resolve_webui_state_display"]
