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
from src.gui.view_contracts.status_banner_contract import update_status_banner
from src.gui.views.experiment_design_panel import ExperimentDesignPanel
from src.gui.views.learning_plan_table import LearningPlanTable
from src.gui.views.learning_review_panel import LearningReviewPanel
from src.learning.learning_paths import get_learning_records_path
from src.learning.learning_record import LearningRecordWriter
from src.services.ui_state_store import get_ui_state_store


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
        self._summary_var = tk.StringVar(value="Plan: 0 variants | Images: 0/0")
        self.summary_label = ttk.Label(
            self.header_frame,
            textvariable=self._summary_var,
            style=BODY_LABEL_STYLE,
        )
        self.summary_label.grid(row=2, column=0, columnspan=5, sticky="w", pady=(2, 0))
        self.learning_controller.add_workflow_state_listener(self._on_workflow_state_changed)
        self.learning_controller.add_resume_state_listener(self._persist_learning_session_state)
        self._on_workflow_state_changed(self.learning_controller.get_workflow_state())
        self._on_automation_mode_changed()
        self._on_learning_toggle()
        self._schedule_summary_refresh()

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
        self._persist_learning_session_state()

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
        self._persist_learning_session_state()

    def _show_automation_help(self) -> None:
        messagebox.showinfo(
            "Automation Modes",
            "suggest_only: recommendations are shown only, never auto-applied.\n\n"
            "apply_with_confirm: recommendations can be applied to stage cards after user confirmation.\n\n"
            "auto_micro_experiment: applies recommendations, then submits one preview job as "
            "a validation run if queue capacity guardrails allow it.",
        )

    def _on_workflow_state_changed(self, state: str) -> None:
        contract = update_status_banner(state)
        self._workflow_state_var.set(contract.display_text)
        self._persist_learning_session_state()

    def _schedule_summary_refresh(self) -> None:
        self._refresh_summary()
        self.after(1000, self._schedule_summary_refresh)

    def _refresh_summary(self) -> None:
        getter = getattr(self.learning_controller, "get_learning_run_summary", None)
        if not callable(getter):
            self._summary_var.set("Plan: n/a")
            return
        summary = getter() or {}
        total_variants = int(summary.get("total_variants", 0) or 0)
        planned_images = int(summary.get("total_planned_images", 0) or 0)
        completed_images = int(summary.get("total_completed_images", 0) or 0)
        status_counts = summary.get("status_counts", {}) or {}
        pending = int(status_counts.get("pending", 0) or 0)
        queued = int(status_counts.get("queued", 0) or 0)
        running = int(status_counts.get("running", 0) or 0)
        failed = int(status_counts.get("failed", 0) or 0)
        cap = summary.get("queue_cap")
        depth = summary.get("queue_depth")
        queue_ok = bool(summary.get("queue_ok", True))
        queue_text = "Queue: ok"
        if cap is not None and depth is not None:
            queue_text = f"Queue: {depth}/{cap}"
        if not queue_ok:
            queue_text = f"{queue_text} (blocked)"
        self._summary_var.set(
            "Plan: "
            f"{total_variants} variants | Images: {completed_images}/{planned_images} | "
            f"Pending: {pending} Queued: {queued} Running: {running} Failed: {failed} | "
            f"{queue_text}"
        )

    def get_learning_session_state(self) -> dict[str, Any] | None:
        """Return learning tab session payload for app-level persistence."""
        exporter = getattr(self.learning_controller, "export_resume_state", None)
        payload = exporter() if callable(exporter) else None
        if payload is None:
            return None
        return {
            "enabled": bool(self._learning_enabled_var.get()),
            "automation_mode": str(self._automation_mode_var.get() or "suggest_only"),
            "session": payload,
        }

    def _persist_learning_session_state(self) -> None:
        """Persist learning session state immediately for resume-after-restart flows."""
        try:
            ui_store = get_ui_state_store()
            state = ui_store.load_state() or {}
            learning_state = self.get_learning_session_state()
            state["learning"] = learning_state if isinstance(learning_state, dict) else {}
            ui_store.save_state(state)
        except Exception:
            pass

    def _restore_experiment_panel(self) -> None:
        experiment = getattr(self.learning_controller.learning_state, "current_experiment", None)
        panel = getattr(self, "experiment_panel", None)
        if not experiment or panel is None:
            return
        try:
            if hasattr(panel, "name_var"):
                panel.name_var.set(str(getattr(experiment, "name", "") or ""))
            if hasattr(panel, "desc_var"):
                panel.desc_var.set(str(getattr(experiment, "description", "") or ""))
            if hasattr(panel, "stage_var"):
                panel.stage_var.set(str(getattr(experiment, "stage", "txt2img") or "txt2img"))
            if hasattr(panel, "variable_var"):
                panel.variable_var.set(
                    str(getattr(experiment, "variable_under_test", "") or "")
                )
            if hasattr(panel, "images_var"):
                panel.images_var.set(int(getattr(experiment, "images_per_value", 1) or 1))
            if hasattr(panel, "prompt_source_var"):
                prompt_text = str(getattr(experiment, "prompt_text", "") or "")
                panel.prompt_source_var.set("custom" if prompt_text else "workspace")
                if hasattr(panel, "custom_prompt_text"):
                    panel.custom_prompt_text.config(state=tk.NORMAL)
                    panel.custom_prompt_text.delete("1.0", tk.END)
                    panel.custom_prompt_text.insert("1.0", prompt_text)
                    if hasattr(panel, "_on_prompt_source_changed"):
                        panel._on_prompt_source_changed()
        except Exception:
            pass

    def restore_learning_session_state(self, payload: dict[str, Any] | None) -> bool:
        """Restore persisted learning tab session payload."""
        if not isinstance(payload, dict):
            return False
        try:
            enabled = bool(payload.get("enabled", True))
            self._learning_enabled_var.set(enabled)
            self._on_learning_toggle()
        except Exception:
            pass
        try:
            mode = str(payload.get("automation_mode", "suggest_only") or "suggest_only")
            self._automation_mode_var.set(mode)
            self._on_automation_mode_changed()
        except Exception:
            pass
        restore = getattr(self.learning_controller, "restore_resume_state", None)
        if callable(restore):
            try:
                restored = bool(restore(payload.get("session")))
                if restored:
                    self._restore_experiment_panel()
                return restored
            except Exception:
                return False
        return False


LearningTabFrame = LearningTabFrame
