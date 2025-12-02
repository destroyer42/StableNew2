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

    def __init__(self, master: tk.Misc, *, controller: Any | None = None, theme: Any | None = None, **kwargs):
        super().__init__(master, style=SURFACE_FRAME_STYLE, padding=(0, 0, 0, 0), **kwargs)
        self.controller = controller
        self.theme = theme

        title = ttk.Label(self, text="Run Controls", style=STATUS_STRONG_LABEL_STYLE)
        title.pack(anchor="w", pady=(0, 4))

        buttons_frame = ttk.Frame(self, style=SURFACE_FRAME_STYLE)
        buttons_frame.pack(fill=tk.X)
        buttons_frame.columnconfigure((0, 1, 2), weight=1)

        self.add_button = ttk.Button(
            buttons_frame,
            text="Add to Queue",
            style=PRIMARY_BUTTON_STYLE,
            command=lambda: self._invoke_controller("on_add_job_to_queue"),
        )
        self.add_button.grid(row=0, column=0, sticky="ew", padx=(0, 4))

        self.run_now_button = ttk.Button(
            buttons_frame,
            text="Run Now",
            style=PRIMARY_BUTTON_STYLE,
            command=lambda: self._invoke_controller("on_run_queue_now_clicked"),
        )
        self.run_now_button.grid(row=0, column=1, sticky="ew", padx=(0, 4))

        self.clear_draft_button = ttk.Button(
            buttons_frame,
            text="Clear Draft",
            style=SECONDARY_BUTTON_STYLE,
            command=lambda: self._invoke_controller("on_clear_job_draft"),
        )
        self.clear_draft_button.grid(row=0, column=2, sticky="ew")

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
