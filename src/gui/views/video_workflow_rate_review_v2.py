"""Rate & review section of the Evaluate view (VID-UX-384 follow-up).

Intent capture only.  It shows how far the selected eval run has been rated and offers the three ways to
rate it that already exist: the HTML report, the bounded Motion Review window and the paired Operator
Site's Video Review.  Every action delegates to the eval panel or to a callable the tab injects; the
section reads ``RunEntry`` (``video_eval_catalog``) and never touches ratings files or the controller.
"""

from __future__ import annotations

import sys
import tkinter as tk
from collections.abc import Callable
from tkinter import ttk
from typing import Any

from src.gui.widgets.responsive_wrap_v2 import bind_wraplength
from src.video.video_eval_catalog import RunEntry

#: Virtual event the tab raises on its toplevel; ``main.py`` binds it to the header Operator Site button.
OPEN_OPERATOR_SITE_EVENT = "<<OpenOperatorSite>>"
NO_RUN_TEXT = "No eval run selected. Queue a suite above, then build its report to start rating."
HINT_TEXT = (
    "Rate clips in the Operator Site's Video Review (saves go to the run's ratings.csv). "
    "Rebuild the report afterwards to refresh its metrics."
)
SITE_UNAVAILABLE_TEXT = "The Operator Site is available on Windows only."


def rating_status_text(run: RunEntry | None) -> str:
    """One line: which run, whether its report exists, and rated n of m."""

    if run is None:
        return NO_RUN_TEXT
    report = "report built" if run.built else "report pending (build it above)"
    if run.rated is None:
        rated = "ratings file unreadable"
    elif run.jobs and run.rated >= run.jobs:
        rated = f"all {run.jobs} clips rated"
    else:
        rated = f"rated {run.rated} of {run.jobs} clips"
    return f"{run.suite_id or run.path.name} · {report} · {rated}"


class RateReviewSection(ttk.Frame):
    def __init__(
        self,
        master: tk.Misc,
        *,
        open_report: Callable[[], None],
        open_motion_review: Callable[[], None],
        open_site: Callable[[], None],
        site_available: bool | None = None,
        **kwargs: Any,
    ) -> None:
        super().__init__(master, style="Panel.TFrame", **kwargs)
        self.columnconfigure(0, weight=1)
        self._site_available = sys.platform == "win32" if site_available is None else site_available
        self.status_var = tk.StringVar(master=self, value=NO_RUN_TEXT)
        self.status_label = ttk.Label(
            self, textvariable=self.status_var, style="Dark.TLabel", justify="left"
        )
        self.status_label.grid(row=0, column=0, sticky="ew")
        bind_wraplength(self.status_label)
        self.progress = ttk.Progressbar(self, maximum=1, value=0, mode="determinate")
        self.progress.grid(row=1, column=0, sticky="ew", pady=(4, 4))
        actions = ttk.Frame(self, style="Panel.TFrame")
        actions.grid(row=2, column=0, sticky="w")
        self.report_button = ttk.Button(actions, text="Open report", command=open_report)
        self.motion_button = ttk.Button(actions, text="Review Motion…", command=open_motion_review)
        self.site_button = ttk.Button(actions, text="Review on Operator Site", command=open_site)
        for button in (self.report_button, self.motion_button, self.site_button):
            button.pack(side="left", padx=(0, 4))
        hint = HINT_TEXT if self._site_available else f"{SITE_UNAVAILABLE_TEXT} {HINT_TEXT}"
        self.hint_label = ttk.Label(self, text=hint, style="Muted.TLabel", justify="left")
        self.hint_label.grid(row=3, column=0, sticky="ew", pady=(4, 0))
        bind_wraplength(self.hint_label)
        self.set_run(None)

    def set_run(self, run: RunEntry | None) -> None:
        self.status_var.set(rating_status_text(run))
        total = max(1, run.jobs) if run is not None else 1
        rated = run.rated if run is not None and run.rated is not None else 0
        self.progress.configure(maximum=total, value=min(rated, total))
        built = run is not None and run.built
        for button, enabled in (
            (self.report_button, run is not None and run.report_path is not None),
            (self.motion_button, run is not None and run.motion and built),
            (self.site_button, built and self._site_available),
        ):
            button.state(["!disabled"] if enabled else ["disabled"])


__all__ = [
    "HINT_TEXT",
    "NO_RUN_TEXT",
    "OPEN_OPERATOR_SITE_EVENT",
    "RateReviewSection",
    "rating_status_text",
]
