from __future__ import annotations

import tkinter as tk
from tkinter import messagebox, ttk
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
from src.learning.learning_paths import get_learning_records_path
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
        self.learning_record_writer = LearningRecordWriter(get_learning_records_path())

        # Initialize learning state and controller
        self.learning_state = LearningState()
        
        # PR-LEARN-002: Get LearningExecutionController from app_controller if available
        execution_controller = getattr(app_controller, "learning_execution_controller", None) if app_controller else None
        
        # PR-LEARN-012: If execution controller doesn't exist on app_controller, create it
        if not execution_controller and app_controller:
            from src.learning.execution_controller import LearningExecutionController
            job_service = getattr(app_controller, "job_service", None)
            if not job_service and pipeline_controller:
                job_service = getattr(pipeline_controller, "_job_service", None)
            
            if job_service:
                execution_controller = LearningExecutionController(
                    learning_state=self.learning_state,
                    job_service=job_service,
                )
                # Store on app_controller for future use
                if hasattr(app_controller, "__dict__"):
                    app_controller.learning_execution_controller = execution_controller
        
        self.learning_controller = LearningController(
            learning_state=self.learning_state,
            prompt_workspace_state=getattr(self.app_state, "prompt_workspace_state", None)
            if self.app_state
            else None,
            pipeline_controller=self.pipeline_controller,
            app_controller=app_controller,  # BUGFIX: Pass app_controller for stage card access
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
        self.header_frame.columnconfigure(0, weight=1)

        header_label = ttk.Label(
            self.header_frame,
            text="Learning Experiment Workspace",
            font=("TkDefaultFont", 14, "bold"),
            style=BODY_LABEL_STYLE,
        )
        header_label.grid(row=0, column=0, sticky="w")
        self._learning_enabled_var = tk.BooleanVar(
            value=self.app_state.learning_enabled if self.app_state else False
        )
        self._automation_mode_var = tk.StringVar(value="suggest_only")
        learning_toggle = ttk.Checkbutton(
            self.header_frame,
            text="Learning mode",
            variable=self._learning_enabled_var,
            command=self._on_learning_toggle,
        )
        learning_toggle.grid(row=0, column=4, sticky="e")
        mode_row = ttk.Frame(self.header_frame, style=SURFACE_FRAME_STYLE)
        mode_row.grid(row=0, column=3, sticky="e", padx=(8, 0))
        ttk.Label(mode_row, text="Automation", style=BODY_LABEL_STYLE).pack(side="left", padx=(0, 4))
        mode_combo = ttk.Combobox(
            mode_row,
            textvariable=self._automation_mode_var,
            values=["suggest_only", "apply_with_confirm", "auto_micro_experiment"],
            state="readonly",
            width=22,
        )
        mode_combo.pack(side="left")
        mode_combo.bind("<<ComboboxSelected>>", lambda _e: self._on_automation_mode_changed())
        help_btn = ttk.Button(
            mode_row,
            text="?",
            width=3,
            command=self._show_automation_help,
        )
        help_btn.pack(side="left", padx=(4, 0))
        ttk.Button(
            self.header_frame,
            text="Review learning runs",
            command=self._on_open_review,
        ).grid(row=0, column=2, sticky="e", padx=8)
        attach_tooltip(learning_toggle, "Enable learning mode to collect ratings and feedback.")
        attach_tooltip(
            mode_combo,
            "suggest_only: never apply; apply_with_confirm: manual apply; "
            "auto_micro_experiment: apply + submit one capped validation job.",
        )
        attach_tooltip(
            help_btn,
            "Automation mode help.",
        )
        attach_tooltip(header_label, "Learning mode: review runs, enable adaptive loops.")
        self._workflow_state_var = tk.StringVar(value="Workflow: idle")
        self.workflow_state_label = ttk.Label(
            self.header_frame,
            textvariable=self._workflow_state_var,
            style=BODY_LABEL_STYLE,
        )
        self.workflow_state_label.grid(row=1, column=0, columnspan=5, sticky="w", pady=(6, 0))
        self.learning_controller.add_workflow_state_listener(self._on_workflow_state_changed)
        self._on_workflow_state_changed(self.learning_controller.get_workflow_state())
        self._on_automation_mode_changed()

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
            self.body_frame,
            learning_controller=self.learning_controller,
            prompt_workspace_state=getattr(self.app_state, "prompt_workspace_state", None)
            if self.app_state
            else None,
            style=CARD_FRAME_STYLE,
        )
        self.experiment_panel.grid(row=0, column=0, sticky="nsew", padx=(0, 2), pady=4)

        # Center panel: Learning Plan Table
        self.plan_table = LearningPlanTable(self.body_frame, style=CARD_FRAME_STYLE)
        self.plan_table.grid(row=0, column=1, sticky="nsew", padx=2, pady=4)

        # Connect controller to plan table
        self.learning_controller._plan_table = self.plan_table
        self.plan_table.set_on_variant_selected(self.learning_controller.on_variant_selected)

        # Right panel: Learning Review
        self.review_panel = LearningReviewPanel(self.body_frame, style=CARD_FRAME_STYLE)
        self.review_panel.grid(row=0, column=2, sticky="nsew", padx=(2, 0), pady=4)

        # Connect controller to review panel (bidirectional)
        self.learning_controller._review_panel = self.review_panel
        self.review_panel.learning_controller = self.learning_controller  # PR-LEARN-014: Fix rating submission

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

    def _on_automation_mode_changed(self) -> None:
        mode = str(self._automation_mode_var.get() or "suggest_only")
        setter = getattr(self.learning_controller, "set_automation_mode", None)
        if callable(setter):
            try:
                setter(mode)
            except Exception:
                pass

    def _show_automation_help(self) -> None:
        messagebox.showinfo(
            "Automation Modes",
            "suggest_only: recommendations are shown only, never auto-applied.\n\n"
            "apply_with_confirm: recommendations can be applied to stage cards after user confirmation.\n\n"
            "auto_micro_experiment: applies recommendations, then submits one preview job as "
            "a validation run if queue capacity guardrails allow it.",
        )

    def _on_workflow_state_changed(self, state: str) -> None:
        label = str(state or "idle").replace("_", " ").title()
        self._workflow_state_var.set(f"Workflow: {label}")


LearningTabFrame = LearningTabFrame
