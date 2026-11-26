"""Evaluate view container for the Video Workflow tab (VID-UX-384).

Presentation only.  It owns the headings and the empty state of the "Evaluate" half of the tab; the
panels it shows (``VideoEvalPanel``, ``WorkflowExperimentPanel``) are built and wired by the tab and
parented here, so their controller calls are unchanged.  Always expanded: the eval controls are never
behind a disclosure.
"""

from __future__ import annotations

import tkinter as tk
from tkinter import ttk
from typing import Any

from src.gui.widgets.responsive_wrap_v2 import bind_wraplength
from src.gui.widgets.scrollable_frame_v2 import ScrollableFrame

EXPERIMENT_EMPTY_TEXT = (
    "Compare one control becomes available when the selected engine declares a control you can "
    "vary (for example a motion prompt or pose strength). Pick an engine on the Create view that "
    "has one, then come back here."
)


class VideoWorkflowEvaluateView(ttk.Frame):
    """Full-width scrolling container: Eval plans and runs, then Compare one control."""

    def __init__(self, master: tk.Misc, **kwargs: Any) -> None:
        super().__init__(master, style="Panel.TFrame", **kwargs)
        self.columnconfigure(0, weight=1)
        self.rowconfigure(0, weight=1)
        self._scroll = ScrollableFrame(self, style="Panel.TFrame")
        self._scroll.grid(row=0, column=0, sticky="nsew")
        self._scroll.inner.columnconfigure(0, weight=1)
        body = ttk.Frame(self._scroll.inner, style="Panel.TFrame", padding=8)
        body.grid(row=0, column=0, sticky="nsew")
        body.columnconfigure(0, weight=1)
        self.body = body
        self.eval_heading = ttk.Label(body, text="Eval plans & runs", style="Dark.TLabel")
        self.eval_heading.grid(row=0, column=0, sticky="w", pady=(0, 4))
        self.eval_host = ttk.Frame(body, style="Panel.TFrame")
        self.eval_host.grid(row=1, column=0, sticky="ew", pady=(0, 12))
        self.eval_host.columnconfigure(0, weight=1)
        self.experiment_heading = ttk.Label(body, text="Compare one control", style="Dark.TLabel")
        self.experiment_heading.grid(row=2, column=0, sticky="w", pady=(0, 4))
        self.experiment_host = ttk.Frame(body, style="Panel.TFrame")
        self.experiment_host.grid(row=3, column=0, sticky="ew")
        self.experiment_host.columnconfigure(0, weight=1)
        self.experiment_empty_label = ttk.Label(
            self.experiment_host, text=EXPERIMENT_EMPTY_TEXT, style="Muted.TLabel", justify="left"
        )
        self.experiment_empty_label.grid(row=1, column=0, sticky="ew")
        bind_wraplength(self.experiment_empty_label)
        self.rate_heading = ttk.Label(body, text="Rate & review", style="Dark.TLabel")
        self.rate_heading.grid(row=4, column=0, sticky="w", pady=(12, 4))
        self.rate_host = ttk.Frame(body, style="Panel.TFrame")
        self.rate_host.grid(row=5, column=0, sticky="ew")
        self.rate_host.columnconfigure(0, weight=1)
        self._experiment_panel: Any = None

    # ``compare_section`` used to be a DisclosureSection; the Evaluate view is never collapsed.
    def is_expanded(self) -> bool:
        return True

    def set_expanded(self, _expanded: bool) -> None:
        return None

    def adopt_experiment_panel(self, panel: Any) -> None:
        self._experiment_panel = panel
        self.sync()

    def sync(self) -> None:
        """Show the empty state exactly while the experiment panel has nothing to offer."""

        panel = self._experiment_panel
        offered = panel is not None and panel.winfo_manager() != ""
        if offered:
            self.experiment_empty_label.grid_remove()
        else:
            self.experiment_empty_label.grid()


__all__ = ["EXPERIMENT_EMPTY_TEXT", "VideoWorkflowEvaluateView"]
