"""Right-pane media and status column of the Video Workflow tab (VID-UX-384).

Presentation only.  ``VideoWorkflowMediaPane`` builds the Show media switch, the source preview, the
motion-readiness details and Recent outputs, all driven by one tab-level ``show_media_var``.  The pure
helpers decide when the readiness details earn a place on screen and what the header chip says.  The
pane reads no workflow record and talks to no controller: the tab hands it callables.
"""

from __future__ import annotations

import tkinter as tk
from collections.abc import Callable
from pathlib import Path
from tkinter import ttk
from typing import Any

from src.gui.views.video_workflow_motion_readiness_panel_v2 import WorkflowMotionReadinessPanel
from src.gui.views.video_workflow_recent_outputs_panel_v2 import WorkflowRecentOutputsPanel
from src.gui.widgets.media_inspector import MediaInspector


def readiness_has_warning(view: Any) -> bool:
    return bool(view.advisory_lines) or view.source_state == "error"


def readiness_is_relevant(view: Any, *, follow_clip_task: bool, opened: bool) -> bool:
    """Details show for the driving-clip task, an engine that takes a driving video, a problem, or on request."""

    return bool(
        follow_clip_task or view.accepts_driving_video or readiness_has_warning(view) or opened
    )


def readiness_chip_text(view: Any, *, has_source: bool) -> str:
    if not has_source:
        return "Source: none selected"
    if view.source_state == "error":
        return "Source problem - details"
    if view.source_state == "loading":
        return "Checking source..."
    if readiness_has_warning(view):
        return "Source ready - see notes"
    detail = next((line for line in view.source_lines if line), "")
    detail = detail.removeprefix("Source:").strip()
    return f"Source ready · {detail}"[:72] if detail else "Source ready"


class VideoWorkflowMediaPane:
    """Builds the right pane's widgets into ``host`` and keeps them in step with Show media."""

    def __init__(
        self,
        host: ttk.Frame,
        *,
        show_media_var: tk.BooleanVar,
        readiness_kwargs: dict[str, Any],
        recent_kwargs: dict[str, Any],
    ) -> None:
        self.show_media_var = show_media_var
        self.check = ttk.Checkbutton(
            host, text="Show media", variable=show_media_var, style="Dark.TCheckbutton"
        )
        self.check.grid(row=0, column=0, sticky="w", pady=(0, 6))
        # The exact source image the operator chose.  It decodes through the shared media inspector, so the
        # application content-visibility policy applies; its own checkbox is replaced by the tab's.
        self.source_preview = MediaInspector(
            host,
            placeholder_text="Choose a source image to preview it here",
            show_control=False,
            allow_original=False,
            shown_var=show_media_var,
            edge=256,
        )
        self.source_preview.grid(row=1, column=0, sticky="ew", pady=(0, 8))
        # PR-VID-196: exact prepared-source preview, bounded driving-video facts, geometry/timing
        # advisories and workflow-aware motion guidance.  Read-only; shown only when it is relevant.
        self.readiness_panel = WorkflowMotionReadinessPanel(host, **readiness_kwargs)
        self.readiness_panel.grid(row=2, column=0, sticky="ew", pady=(0, 8))
        self.readiness_panel.grid_remove()
        # PR-VID-UX-314: the newest finished clips with an in-app looping preview.
        self.recent_panel = WorkflowRecentOutputsPanel(
            host, shown_var=show_media_var, **recent_kwargs
        )
        self.recent_panel.grid(row=3, column=0, sticky="ew")

    def apply_show_media(self) -> None:
        shown = bool(self.show_media_var.get())
        for inspector in (self.source_preview, self.recent_panel.preview):
            inspector.set_visibility(shown)
        self.readiness_panel.render()

    def sync_source(self, path: str) -> None:
        if path and Path(path).is_file():
            self.source_preview.set_media(path, "image")
        else:
            self.source_preview.set_media(None)


MediaPaneBuilder = Callable[..., VideoWorkflowMediaPane]

__all__ = [
    "VideoWorkflowMediaPane",
    "readiness_chip_text",
    "readiness_has_warning",
    "readiness_is_relevant",
]
