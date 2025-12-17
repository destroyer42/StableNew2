# Subsystem: Learning
# Role: Hosts the full learning tab layout in the GUI.

from __future__ import annotations

import tkinter as tk
from tkinter import ttk
from typing import Any

from src.gui.app_state_v2 import AppStateV2
from src.gui.controllers.learning_controller import LearningController
from src.gui.learning_state import LearningState
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
        *args,
        **kwargs,
    ) -> None:
        super().__init__(master, *args, **kwargs)
        self.app_state = app_state
        self.pipeline_controller = pipeline_controller

        # Initialize learning record writer
        self.learning_record_writer = LearningRecordWriter("data/learning_records.jsonl")

        # Initialize learning state and controller
        self.learning_state = LearningState()
        self.learning_controller = LearningController(
            learning_state=self.learning_state,
            prompt_workspace_state=getattr(self.app_state, "prompt_workspace_state", None)
            if self.app_state
            else None,
            pipeline_controller=self.pipeline_controller,
            learning_record_writer=self.learning_record_writer,
        )

        # Configure main layout
        self.columnconfigure(0, weight=1)
        self.rowconfigure(0, weight=0)  # Header
        self.rowconfigure(1, weight=1)  # Body

        # Header
        self.header_frame = ttk.Frame(self, padding=8, style="Panel.TFrame")
        self.header_frame.grid(row=0, column=0, sticky="ew", padx=4, pady=(4, 2))

        header_label = ttk.Label(
            self.header_frame,
            text="Learning Experiment Workspace",
            font=("TkDefaultFont", 14, "bold"),
        )
        header_label.pack(anchor="w")

        # Body with three columns
        self.body_frame = ttk.Frame(self, style="Panel.TFrame")
        self.body_frame.grid(row=1, column=0, sticky="nsew", padx=4, pady=(2, 4))

        # Configure body layout
        self.body_frame.columnconfigure(0, weight=1, uniform="learning_col")
        self.body_frame.columnconfigure(1, weight=2, uniform="learning_col")
        self.body_frame.columnconfigure(2, weight=1, uniform="learning_col")
        self.body_frame.rowconfigure(0, weight=1)

        # Left panel: Experiment Design
        self.experiment_panel = ExperimentDesignPanel(
            self.body_frame, learning_controller=self.learning_controller, style="Panel.TFrame"
        )
        self.experiment_panel.grid(row=0, column=0, sticky="nsew", padx=(0, 2), pady=4)

        # Center panel: Learning Plan Table
        self.plan_table = LearningPlanTable(self.body_frame, style="Panel.TFrame")
        self.plan_table.grid(row=0, column=1, sticky="nsew", padx=2, pady=4)

        # Connect controller to plan table
        self.learning_controller._plan_table = self.plan_table

        # Right panel: Learning Review
        self.review_panel = LearningReviewPanel(self.body_frame, style="Panel.TFrame")
        self.review_panel.grid(row=0, column=2, sticky="nsew", padx=(2, 0), pady=4)

        # Connect controller to review panel
        self.learning_controller._review_panel = self.review_panel
