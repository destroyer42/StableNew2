from __future__ import annotations

import tkinter as tk
from tkinter import ttk
from typing import Any

from src.gui.app_state_v2 import AppStateV2
from src.gui.controllers.learning_controller import LearningController
from src.gui.learning_review_dialog_v2 import LearningReviewDialogV2
from src.gui.learning_state import LearningState
from src.gui.theme_v2 import BODY_LABEL_STYLE, CARD_FRAME_STYLE, SURFACE_FRAME_STYLE
from src.gui.tooltip import attach_tooltip
from src.gui.views.experiment_design_panel import ExperimentDesignPanel
from src.gui.views.learning_plan_table import LearningPlanTable
from src.gui.views.learning_review_panel import LearningReviewPanel
from src.learning.learning_record import LearningRecordWriter


class LearningTabFrame(ttk.Frame):
    """Learning tab with header and three-column workspace layout."""

    def __init__(
        self,
        master: tk.Misc,
        app_state: AppStateV2 | None = None,
        pipeline_controller: Any | None = None,
        app_controller: Any | None = None,  # PR-LEARN-002: For LearningExecutionController access
        *args: Any,
        **kwargs: Any,
    ) -> None:
        super().__init__(master, *args, **kwargs)
        self.app_state = app_state
        self.pipeline_controller = pipeline_controller
        self.app_controller = app_controller  # PR-LEARN-002: Store app_controller reference

        # Initialize learning record writer
        self.learning_record_writer = LearningRecordWriter("data/learning_records.jsonl")

        # Initialize learning state and controller
        self.learning_state = LearningState()
        
        # PR-LEARN-002: Get LearningExecutionController from app_controller if available
        execution_controller = getattr(app_controller, "learning_execution_controller", None) if app_controller else None
        
        self.learning_controller = LearningController(
            learning_state=self.learning_state,
            prompt_workspace_state=getattr(self.app_state, "prompt_workspace_state", None)
            if self.app_state
            else None,
            pipeline_controller=self.pipeline_controller,
            learning_record_writer=self.learning_record_writer,
            execution_controller=execution_controller,  # PR-LEARN-002: Pass execution controller
        )

        # Configure main layout
        self.columnconfigure(0, weight=1)
        self.rowconfigure(0, weight=0)  # Header
        self.rowconfigure(1, weight=1)  # Body

        # Header
        self.header_frame = ttk.Frame(self, padding=8, style=SURFACE_FRAME_STYLE)
        self.header_frame.grid(row=0, column=0, sticky="ew", padx=4, pady=(4, 2))

        header_label = ttk.Label(
            self.header_frame,
            text="Learning Experiment Workspace",
            font=("TkDefaultFont", 14, "bold"),
            style=BODY_LABEL_STYLE,
        )
        header_label.pack(side="left", anchor="w")
        self._learning_enabled_var = tk.BooleanVar(
            value=self.app_state.learning_enabled if self.app_state else False
        )
        learning_toggle = ttk.Checkbutton(
            self.header_frame,
            text="Learning mode",
            variable=self._learning_enabled_var,
            command=self._on_learning_toggle,
        )
        learning_toggle.pack(side="right")
        ttk.Button(
            self.header_frame,
            text="Review learning runs",
            command=self._on_open_review,
        ).pack(side="right", padx=8)
        attach_tooltip(learning_toggle, "Enable learning mode to collect ratings and feedback.")
        attach_tooltip(header_label, "Learning mode: review runs, enable adaptive loops.")

        # Body with three columns
        self.body_frame = ttk.Frame(self, style=SURFACE_FRAME_STYLE)
        self.body_frame.grid(row=1, column=0, sticky="nsew", padx=4, pady=(2, 4))

        # Configure body layout
        self.body_frame.columnconfigure(0, weight=1, uniform="learning_col")
        self.body_frame.columnconfigure(1, weight=2, uniform="learning_col")
        self.body_frame.columnconfigure(2, weight=1, uniform="learning_col")
        self.body_frame.rowconfigure(0, weight=1)

        # Left panel: Experiment Design
        self.experiment_panel = ExperimentDesignPanel(
            self.body_frame, learning_controller=self.learning_controller, style=CARD_FRAME_STYLE
        )
        self.experiment_panel.grid(row=0, column=0, sticky="nsew", padx=(0, 2), pady=4)

        # Center panel: Learning Plan Table
        self.plan_table = LearningPlanTable(self.body_frame, style=CARD_FRAME_STYLE)
        self.plan_table.grid(row=0, column=1, sticky="nsew", padx=2, pady=4)

        # Connect controller to plan table
        self.learning_controller._plan_table = self.plan_table

        # Right panel: Learning Review
        self.review_panel = LearningReviewPanel(self.body_frame, style=CARD_FRAME_STYLE)
        self.review_panel.grid(row=0, column=2, sticky="nsew", padx=(2, 0), pady=4)

        # Connect controller to review panel
        self.learning_controller._review_panel = self.review_panel

    def _on_learning_toggle(self) -> None:
        """Handle the learning mode toggle button."""
        enabled = bool(self._learning_enabled_var.get())
        ctrl = getattr(self.learning_controller, "set_learning_enabled", None)
        if callable(ctrl):
            try:
                ctrl(enabled)
            except Exception:
                pass
        if self.app_state:
            try:
                self.app_state.set_learning_enabled(enabled)
            except Exception:
                pass

    def _on_open_review(self) -> None:
        """Open the learning review dialog with the latest records."""
        fetch = getattr(self.learning_controller, "list_recent_records", None)
        records = []
        if callable(fetch):
            try:
                records = fetch(limit=10)
            except Exception:
                records = []
        try:
            LearningReviewDialogV2(self, self.learning_controller, records)
        except Exception:
            pass


LearningTabFrame = LearningTabFrame
