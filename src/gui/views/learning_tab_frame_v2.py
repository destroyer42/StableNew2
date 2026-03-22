from __future__ import annotations

import tkinter as tk
from pathlib import Path
from tkinter import filedialog, messagebox, ttk
from typing import Any

from src.gui.app_state_v2 import AppStateV2
from src.gui.controllers.learning_controller import LearningController
from src.gui.learning_review_dialog_v2 import LearningReviewDialogV2
from src.gui.learning_state import LearningState
from src.gui.theme_v2 import BODY_LABEL_STYLE, CARD_FRAME_STYLE, SURFACE_FRAME_STYLE
from src.gui.tooltip import attach_tooltip
from src.gui.view_contracts.status_banner_contract import update_status_banner
from src.gui.views.discovered_review_inbox_panel import DiscoveredReviewInboxPanel
from src.gui.views.discovered_review_table import DiscoveredReviewTable
from src.gui.views.experiment_design_panel import ExperimentDesignPanel
from src.gui.views.learning_plan_table import LearningPlanTable
from src.gui.views.learning_review_panel import LearningReviewPanel
from src.gui.widgets.image_thumbnail import ImageThumbnail
from src.learning.experiment_store import LearningExperimentStore
from src.learning.learning_paths import get_learning_experiments_root, get_learning_records_path
from src.learning.learning_record import LearningRecordWriter
from src.services.ui_state_store import get_ui_state_store
from src.state.output_routing import get_output_root
from src.utils.config import ConfigManager


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
        self.experiment_store = LearningExperimentStore(get_learning_experiments_root())
        self._active_experiment_id: str | None = None

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
        ttk.Button(
            self.header_frame,
            text="Save",
            command=self._on_save_experiment,
        ).grid(row=0, column=5, sticky="e", padx=(4, 0))
        ttk.Button(
            self.header_frame,
            text="Save As",
            command=self._on_save_experiment_as,
        ).grid(row=0, column=6, sticky="e", padx=(4, 0))
        ttk.Button(
            self.header_frame,
            text="Load",
            command=self._on_load_experiment,
        ).grid(row=0, column=7, sticky="e", padx=(4, 0))
        ttk.Button(
            self.header_frame,
            text="Resume Last",
            command=self._on_resume_last_experiment,
        ).grid(row=0, column=8, sticky="e", padx=(4, 0))
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

        # Body: mode notebook (Designed Experiments | Discovered Review Inbox)
        self._mode_notebook = ttk.Notebook(self)
        self._mode_notebook.grid(row=1, column=0, sticky="nsew", padx=4, pady=(2, 4))

        # ---- Tab 1: Designed Experiments (existing 3-column layout) ----
        self.body_frame = ttk.Frame(self._mode_notebook, style=SURFACE_FRAME_STYLE)
        self._mode_notebook.add(self.body_frame, text="Designed Experiments")

        # Configure body layout
        self.body_frame.columnconfigure(0, weight=1, uniform="learning_col")
        self.body_frame.columnconfigure(1, weight=3, uniform="learning_col")
        self.body_frame.columnconfigure(2, weight=2, uniform="learning_col")
        self.body_frame.rowconfigure(0, weight=1)
        self.body_frame.rowconfigure(1, weight=3)

        # Left panel: Experiment Design
        self.experiment_panel = ExperimentDesignPanel(
            self.body_frame,
            learning_controller=self.learning_controller,
            prompt_workspace_state=getattr(self.app_state, "prompt_workspace_state", None)
            if self.app_state
            else None,
            packs_dir=getattr(getattr(self.pipeline_controller, "_config_manager", None), "packs_dir", None),
            style=CARD_FRAME_STYLE,
        )
        self.experiment_panel.grid(row=0, column=0, rowspan=2, sticky="nsew", padx=(0, 2), pady=4)

        # Center panel: Learning Plan Table
        self.plan_table = LearningPlanTable(self.body_frame, style=CARD_FRAME_STYLE)
        self.plan_table.grid(row=0, column=1, columnspan=2, sticky="nsew", padx=2, pady=(4, 2))

        # Connect controller to plan table
        self.learning_controller._plan_table = self.plan_table
        self.plan_table.set_on_variant_selected(self.learning_controller.on_variant_selected)

        # Right panel: Learning Review
        self.review_panel = LearningReviewPanel(self.body_frame, style=CARD_FRAME_STYLE)
        self.review_panel.grid(row=1, column=1, columnspan=2, sticky="nsew", padx=2, pady=(2, 4))

        # Connect controller to review panel (bidirectional)
        self.learning_controller._review_panel = self.review_panel
        self.review_panel.learning_controller = self.learning_controller  # PR-LEARN-014: Fix rating submission

        # ---- Tab 2: Discovered Review Inbox ----
        self._discovered_tab_frame = ttk.Frame(self._mode_notebook, style=SURFACE_FRAME_STYLE)
        self._mode_notebook.add(self._discovered_tab_frame, text="Discovered Review Inbox")
        self._discovered_tab_frame.columnconfigure(0, weight=1)
        self._discovered_tab_frame.columnconfigure(1, weight=2)
        self._discovered_tab_frame.rowconfigure(0, weight=1)

        self.discovered_inbox_panel = DiscoveredReviewInboxPanel(
            self._discovered_tab_frame,
            on_open_group=self._on_discovered_open_group,
            on_close_group=self._on_discovered_close_group,
            on_ignore_group=self._on_discovered_ignore_group,
            on_rescan=self._on_discovered_rescan,
        )
        self.discovered_inbox_panel.grid(row=0, column=0, sticky="nsew", padx=(0, 2), pady=4)

        self.discovered_review_table = DiscoveredReviewTable(
            self._discovered_tab_frame,
            on_rate_item=self._on_discovered_rate_item,
        )
        self.discovered_review_table.grid(row=0, column=1, sticky="nsew", padx=(2, 0), pady=4)

        # ---- Tab 3: Staged Curation ----
        self._staged_tab_frame = ttk.Frame(self._mode_notebook, style=SURFACE_FRAME_STYLE)
        self._mode_notebook.add(self._staged_tab_frame, text="Staged Curation")
        self._staged_tab_frame.columnconfigure(0, weight=1)
        self._staged_tab_frame.columnconfigure(1, weight=2)
        self._staged_tab_frame.columnconfigure(2, weight=2)
        self._staged_tab_frame.rowconfigure(0, weight=1)

        self._staged_reason_tag_vars: dict[str, tk.BooleanVar] = {}
        self._staged_candidates_by_id: dict[str, dict[str, Any]] = {}
        self._staged_items_by_id: dict[str, Any] = {}
        self._staged_latest_events: dict[str, Any] = {}
        self._staged_current_group_id: str | None = None

        self.staged_inbox_panel = DiscoveredReviewInboxPanel(
            self._staged_tab_frame,
            on_open_group=self._on_staged_open_group,
            on_close_group=self._on_staged_close_group,
            on_ignore_group=self._on_staged_ignore_group,
            on_rescan=self._on_staged_rescan,
        )
        self.staged_inbox_panel.grid(row=0, column=0, sticky="nsew", padx=(0, 2), pady=4)

        staged_center = ttk.LabelFrame(
            self._staged_tab_frame,
            text="Candidates",
            padding=(6, 4),
        )
        staged_center.grid(row=0, column=1, sticky="nsew", padx=2, pady=4)
        staged_center.columnconfigure(0, weight=1)
        staged_center.rowconfigure(1, weight=1)

        self._staged_group_var = tk.StringVar(value="Open a discovered group to start staged curation")
        ttk.Label(
            staged_center,
            textvariable=self._staged_group_var,
            style=BODY_LABEL_STYLE,
            justify="left",
            anchor="w",
        ).grid(row=0, column=0, sticky="ew", pady=(0, 4))

        candidate_frame = ttk.Frame(staged_center, style=SURFACE_FRAME_STYLE)
        candidate_frame.grid(row=1, column=0, sticky="nsew")
        candidate_frame.columnconfigure(0, weight=1)
        candidate_frame.rowconfigure(0, weight=1)

        self._staged_candidate_tree = ttk.Treeview(
            candidate_frame,
            columns=("decision", "rating", "stage", "model", "steps", "cfg", "file"),
            show="headings",
            selectmode="browse",
        )
        for column_id, heading, width, anchor in (
            ("decision", "Decision", 130, "center"),
            ("rating", "Rating", 70, "center"),
            ("stage", "Stage", 80, "center"),
            ("model", "Model", 150, "w"),
            ("steps", "Steps", 55, "center"),
            ("cfg", "CFG", 55, "center"),
            ("file", "File", 220, "w"),
        ):
            self._staged_candidate_tree.heading(column_id, text=heading)
            self._staged_candidate_tree.column(column_id, width=width, anchor=anchor)
        self._staged_candidate_tree.grid(row=0, column=0, sticky="nsew")
        self._staged_candidate_scrollbar = ttk.Scrollbar(
            candidate_frame,
            orient="vertical",
            command=self._staged_candidate_tree.yview,
        )
        self._staged_candidate_scrollbar.grid(row=0, column=1, sticky="ns")
        self._staged_candidate_tree.configure(yscrollcommand=self._staged_candidate_scrollbar.set)
        self._staged_candidate_tree.bind("<<TreeviewSelect>>", self._on_staged_candidate_selected)

        staged_right = ttk.LabelFrame(
            self._staged_tab_frame,
            text="Selection Workspace",
            padding=(6, 4),
        )
        staged_right.grid(row=0, column=2, sticky="nsew", padx=(2, 0), pady=4)
        staged_right.columnconfigure(0, weight=1)
        staged_right.rowconfigure(1, weight=1)

        self._staged_preview_meta_var = tk.StringVar(
            value="Select a candidate to preview and record a staged-curation decision"
        )
        ttk.Label(
            staged_right,
            textvariable=self._staged_preview_meta_var,
            style=BODY_LABEL_STYLE,
            justify="left",
            anchor="w",
        ).grid(row=0, column=0, sticky="ew", pady=(0, 4))

        self._staged_preview_thumbnail = ImageThumbnail(
            staged_right,
            max_width=1400,
            max_height=1400,
        )
        self._staged_preview_thumbnail.grid(row=1, column=0, sticky="nsew")
        self._staged_preview_thumbnail.clear()

        reason_frame = ttk.LabelFrame(staged_right, text="Reason Tags", padding=(6, 4))
        reason_frame.grid(row=2, column=0, sticky="ew", pady=(6, 0))
        for index, tag in enumerate(self.learning_controller.get_staged_curation_reason_tag_options()):
            var = tk.BooleanVar(value=False)
            self._staged_reason_tag_vars[tag] = var
            ttk.Checkbutton(
                reason_frame,
                text=tag.replace("_", " "),
                variable=var,
            ).grid(row=index // 2, column=index % 2, sticky="w", padx=(0, 8), pady=1)

        notes_frame = ttk.LabelFrame(staged_right, text="Decision Notes", padding=(6, 4))
        notes_frame.grid(row=3, column=0, sticky="ew", pady=(6, 0))
        notes_frame.columnconfigure(0, weight=1)
        self._staged_notes_text = tk.Text(notes_frame, height=4, wrap="word")
        self._staged_notes_text.grid(row=0, column=0, sticky="ew")

        self._staged_last_decision_var = tk.StringVar(value="Latest decision: none")
        ttk.Label(
            staged_right,
            textvariable=self._staged_last_decision_var,
            style=BODY_LABEL_STYLE,
        ).grid(row=4, column=0, sticky="w", pady=(6, 0))

        action_frame = ttk.Frame(staged_right, style=SURFACE_FRAME_STYLE)
        action_frame.grid(row=5, column=0, sticky="ew", pady=(6, 0))
        for label, decision in (
            ("Reject", "rejected_hard"),
            ("Hold", "not_advanced"),
            ("To Refine", "advanced_to_refine"),
            ("To Face", "advanced_to_face_triage"),
            ("To Upscale", "advanced_to_upscale"),
            ("Final Keep", "curated_final"),
        ):
            ttk.Button(
                action_frame,
                text=label,
                command=lambda value=decision: self._apply_staged_decision(value),
            ).pack(side="left", padx=(0, 4))

        # Refresh inbox when its tab is activated
        self._mode_notebook.bind("<<NotebookTabChanged>>", self._on_notebook_tab_changed)

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

    def _build_store_payload(self) -> dict[str, Any] | None:
        if self.learning_controller.learning_state.current_experiment is None:
            return None
        payload = self.learning_controller.learning_state.to_dict()
        payload["workflow_state"] = str(self._workflow_state_var.get() or "")
        payload["learning_enabled"] = bool(self._learning_enabled_var.get())
        payload["automation_mode"] = str(self._automation_mode_var.get() or "suggest_only")
        return payload

    def get_learning_session_state(self) -> dict[str, Any] | None:
        """Return learning tab session payload for app-level persistence."""
        return {
            "enabled": bool(self._learning_enabled_var.get()),
            "automation_mode": str(self._automation_mode_var.get() or "suggest_only"),
            "last_experiment_id": self._active_experiment_id,
        }

    def _persist_learning_session_state(self) -> None:
        """Persist learning session state immediately for resume-after-restart flows."""
        try:
            payload = self._build_store_payload()
            if isinstance(payload, dict):
                experiment = self.learning_controller.learning_state.current_experiment
                display_name = str(getattr(experiment, "name", "") or "Learning Experiment")
                handle = self.experiment_store.save_session(
                    display_name=display_name,
                    payload=payload,
                    experiment_id=self._active_experiment_id,
                )
                self._active_experiment_id = handle.experiment_id
            ui_store = get_ui_state_store()
            state = ui_store.load_state() or {}
            learning_state = self.get_learning_session_state()
            state["learning"] = learning_state if isinstance(learning_state, dict) else {}
            ui_store.save_state(state)
        except Exception:
            pass

    def _restore_from_store_payload(
        self,
        payload: dict[str, Any] | None,
        *,
        experiment_id: str | None = None,
    ) -> bool:
        if not isinstance(payload, dict):
            return False
        try:
            enabled = bool(payload.get("learning_enabled", payload.get("enabled", True)))
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
        restored = bool(self.learning_controller.restore_resume_state(payload))
        if restored:
            self._active_experiment_id = experiment_id or self._active_experiment_id
            self._restore_experiment_panel()
        return restored

    def _save_to_store(self, *, force_new: bool) -> bool:
        payload = self._build_store_payload()
        if not isinstance(payload, dict):
            return False
        experiment = self.learning_controller.learning_state.current_experiment
        display_name = str(getattr(experiment, "name", "") or "Learning Experiment")
        handle = self.experiment_store.save_session(
            display_name=display_name,
            payload=payload,
            experiment_id=None if force_new else self._active_experiment_id,
        )
        self._active_experiment_id = handle.experiment_id
        self._persist_learning_session_state()
        return True

    def _on_save_experiment(self) -> None:
        if not self._save_to_store(force_new=False):
            messagebox.showinfo("Learning", "No experiment is available to save.")

    def _on_save_experiment_as(self) -> None:
        if not self._save_to_store(force_new=True):
            messagebox.showinfo("Learning", "No experiment is available to save.")

    def _on_load_experiment(self) -> None:
        session_path = filedialog.askopenfilename(
            parent=self,
            title="Load Learning Experiment",
            initialdir=str(self.experiment_store.root),
            filetypes=[("Learning Session", "session.json"), ("JSON Files", "*.json")],
        )
        if not session_path:
            return
        resolved = Path(session_path)
        experiment_id = resolved.parent.name
        payload = self.experiment_store.load_session(experiment_id)
        if not self._restore_from_store_payload(payload, experiment_id=experiment_id):
            messagebox.showerror("Learning", "Unable to load the selected experiment.")

    def _on_resume_last_experiment(self) -> None:
        last = self.experiment_store.load_last_session()
        if not last:
            messagebox.showinfo("Learning", "No saved learning experiment was found.")
            return
        experiment_id, payload = last
        if not self._restore_from_store_payload(payload, experiment_id=experiment_id):
            messagebox.showerror("Learning", "Unable to resume the last saved experiment.")

    def _restore_experiment_panel(self) -> None:
        experiment = getattr(self.learning_controller.learning_state, "current_experiment", None)
        panel = getattr(self, "experiment_panel", None)
        if not experiment or panel is None:
            return

        # Prefer delegating state restoration to the experiment panel itself,
        # falling back to the legacy attribute-based logic if needed.
        restore = getattr(panel, "restore_state", None)
        if callable(restore):
            try:
                restore(experiment)
            except Exception:
                # Swallow exceptions to match the previous best-effort behavior.
                pass
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
        experiment_id = str(payload.get("last_experiment_id") or "").strip() or None
        if experiment_id:
            stored = self.experiment_store.load_session(experiment_id)
            if self._restore_from_store_payload(stored, experiment_id=experiment_id):
                return True
        if isinstance(payload.get("session"), dict):
            restored = self._restore_from_store_payload(payload.get("session"))
            if restored and self._active_experiment_id is None:
                self._save_to_store(force_new=True)
            return restored
        try:
            enabled = bool(payload.get("enabled", True))
            self._learning_enabled_var.set(enabled)
            self._on_learning_toggle()
            mode = str(payload.get("automation_mode", "suggest_only") or "suggest_only")
            self._automation_mode_var.set(mode)
            self._on_automation_mode_changed()
        except Exception:
            pass
        return False

    # ------------------------------------------------------------------
    # PR-GUI-LEARN-041: Discovered-review event handlers
    # ------------------------------------------------------------------

    def _on_notebook_tab_changed(self, _event: Any = None) -> None:
        """Refresh the discovered inbox whenever its tab is activated."""
        try:
            selected = self._mode_notebook.index(self._mode_notebook.select())
            if selected == 1:
                self._refresh_discovered_inbox()
            elif selected == 2:
                self._refresh_staged_curation_inbox()
        except Exception:
            pass

    def _refresh_discovered_inbox(self) -> None:
        handles = self.learning_controller.refresh_discovered_inbox()
        self.discovered_inbox_panel.load_handles(handles)

    def _on_discovered_open_group(self, group_id: str) -> None:
        experiment = self.learning_controller.load_discovered_group(group_id)
        if experiment is None:
            return
        self.discovered_review_table.load_items(
            experiment.items,
            varying_fields=list(experiment.varying_fields or []),
            group_display_name=experiment.display_name or group_id,
        )

    def _on_discovered_close_group(self, group_id: str) -> None:
        self.learning_controller.close_discovered_group(group_id)
        self._refresh_discovered_inbox()

    def _on_discovered_ignore_group(self, group_id: str) -> None:
        self.learning_controller.ignore_discovered_group(group_id)
        self._refresh_discovered_inbox()

    def _resolve_discovered_output_root(self) -> str:
        config_manager = getattr(self.pipeline_controller, "_config_manager", None)
        configured_root = None

        getter = getattr(config_manager, "get_setting", None)
        if callable(getter):
            try:
                configured_root = getter("output_dir", None)
            except Exception:
                configured_root = None

        if not configured_root:
            try:
                configured_root = ConfigManager().get_setting("output_dir", "output")
            except Exception:
                configured_root = "output"

        return str(get_output_root(configured_root or "output", create=False))

    def _on_discovered_rescan(self) -> None:
        self.discovered_inbox_panel.set_scanning(True)
        self.learning_controller.trigger_background_scan(
            output_root=self._resolve_discovered_output_root(),
            on_complete=self._on_discovered_scan_complete,
        )

    def _on_discovered_scan_complete(self, new_count: int) -> None:
        self.discovered_inbox_panel.set_scanning(False)
        self._refresh_discovered_inbox()

    def _on_discovered_rate_item(self, item_id: str, rating: int) -> None:
        group_id = self.learning_controller.learning_state.selected_discovered_group_id
        if not group_id:
            return
        self.learning_controller.save_discovered_item_rating(group_id, item_id, rating)
        self.discovered_review_table.refresh_item_rating(item_id, rating)

    # ------------------------------------------------------------------
    # PR-LEARN-259B: Staged-curation event handlers
    # ------------------------------------------------------------------

    def _refresh_staged_curation_inbox(self) -> None:
        handles = self.learning_controller.list_staged_curation_handles()
        self.staged_inbox_panel.load_handles(handles)

    def _on_staged_open_group(self, group_id: str) -> None:
        payload = self.learning_controller.load_staged_curation_group(group_id)
        if not isinstance(payload, dict):
            return
        experiment = payload.get("experiment")
        candidates = list(payload.get("candidates") or [])
        latest_events = dict(payload.get("latest_events") or {})
        self._staged_current_group_id = group_id
        self._staged_latest_events = latest_events
        self._staged_items_by_id = {
            str(item.item_id): item for item in list(getattr(experiment, "items", []) or [])
        }
        self._staged_candidates_by_id = {}
        self._staged_group_var.set(
            f"{getattr(experiment, 'display_name', group_id)} | "
            f"{len(self._staged_items_by_id)} candidate(s) | "
            f"varying: {', '.join(list(getattr(experiment, 'varying_fields', []) or [])) or 'n/a'}"
        )
        self._render_staged_candidates(candidates, latest_events)
        self._clear_staged_reason_tags()
        self._staged_notes_text.delete("1.0", tk.END)

    def _render_staged_candidates(self, candidates: list[Any], latest_events: dict[str, Any]) -> None:
        self._staged_candidate_tree.delete(*self._staged_candidate_tree.get_children())
        self._staged_candidates_by_id = {}
        for candidate in candidates:
            item = self._staged_items_by_id.get(str(getattr(candidate, "candidate_id", "") or ""))
            if item is None:
                continue
            latest = latest_events.get(candidate.candidate_id)
            decision = str(getattr(latest, "decision", "") or "unreviewed").replace("_", " ")
            rating = "unrated"
            if int(getattr(item, "rating", 0) or 0) > 0:
                rating = f"{int(getattr(item, 'rating', 0))}/5"
            values = (
                decision,
                rating,
                str(getattr(item, "stage", "") or ""),
                _truncate(str(getattr(item, "model", "") or ""), 24),
                int(getattr(item, "steps", 0) or 0),
                f"{float(getattr(item, 'cfg_scale', 0.0) or 0.0):.1f}",
                _truncate(Path(str(getattr(item, "artifact_path", "") or "")).name, 32),
            )
            self._staged_candidates_by_id[candidate.candidate_id] = {
                "candidate": candidate,
                "item": item,
            }
            self._staged_candidate_tree.insert("", "end", iid=candidate.candidate_id, values=values)
        children = self._staged_candidate_tree.get_children()
        if children:
            selected_item_id = self.learning_controller.learning_state.selected_staged_curation_item_id
            first = selected_item_id if selected_item_id in children else children[0]
            self._staged_candidate_tree.selection_set(first)
            self._staged_candidate_tree.focus(first)
            self._update_staged_preview(first)
        else:
            self._update_staged_preview(None)

    def _on_staged_candidate_selected(self, _event: Any = None) -> None:
        selection = self._staged_candidate_tree.selection()
        candidate_id = selection[0] if selection else None
        self._update_staged_preview(candidate_id)

    def _update_staged_preview(self, candidate_id: str | None) -> None:
        if not candidate_id:
            self.learning_controller.learning_state.selected_staged_curation_item_id = None
            self._staged_preview_meta_var.set(
                "Select a candidate to preview and record a staged-curation decision"
            )
            self._staged_last_decision_var.set("Latest decision: none")
            self._staged_preview_thumbnail.clear()
            self._clear_staged_reason_tags()
            self._staged_notes_text.delete("1.0", tk.END)
            return
        row = self._staged_candidates_by_id.get(candidate_id) or {}
        item = row.get("item")
        if item is None:
            return
        self.learning_controller.learning_state.selected_staged_curation_item_id = candidate_id
        self.learning_controller.learning_state.selected_staged_curation_group_id = self._staged_current_group_id
        latest = self._staged_latest_events.get(candidate_id)
        dimensions = ""
        if int(getattr(item, "width", 0) or 0) and int(getattr(item, "height", 0) or 0):
            dimensions = f"{item.width} x {item.height}"
        self._staged_preview_meta_var.set(
            " | ".join(
                [
                    part
                    for part in (
                        str(getattr(item, "stage", "") or ""),
                        str(getattr(item, "model", "") or ""),
                        dimensions,
                        f"sampler={getattr(item, 'sampler', '')}" if getattr(item, "sampler", "") else "",
                    )
                    if part
                ]
            )
            or "Candidate selected"
        )
        self._staged_preview_thumbnail.load_image(str(getattr(item, "artifact_path", "") or ""))
        self._clear_staged_reason_tags()
        self._staged_notes_text.delete("1.0", tk.END)
        if latest is not None:
            self._staged_last_decision_var.set(
                f"Latest decision: {str(getattr(latest, 'decision', 'unreviewed')).replace('_', ' ')}"
            )
            for tag in list(getattr(latest, "reason_tags", []) or []):
                var = self._staged_reason_tag_vars.get(str(tag))
                if var is not None:
                    var.set(True)
            notes = str(getattr(latest, "notes", "") or "")
            if notes:
                self._staged_notes_text.insert("1.0", notes)
        else:
            self._staged_last_decision_var.set("Latest decision: unreviewed")
        self._persist_learning_session_state()

    def _clear_staged_reason_tags(self) -> None:
        for var in self._staged_reason_tag_vars.values():
            var.set(False)

    def _collect_staged_reason_tags(self) -> list[str]:
        return [tag for tag, var in self._staged_reason_tag_vars.items() if bool(var.get())]

    def _apply_staged_decision(self, decision: str) -> None:
        selection = self._staged_candidate_tree.selection()
        candidate_id = selection[0] if selection else None
        if not self._staged_current_group_id or not candidate_id:
            return
        notes = self._staged_notes_text.get("1.0", tk.END).strip()
        event = self.learning_controller.record_staged_curation_selection(
            self._staged_current_group_id,
            candidate_id,
            decision,
            reason_tags=self._collect_staged_reason_tags(),
            notes=notes,
        )
        if event is None:
            return
        self._staged_latest_events[candidate_id] = event
        latest_label = str(event.decision or "unreviewed").replace("_", " ")
        try:
            self._staged_candidate_tree.set(candidate_id, "decision", latest_label)
        except Exception:
            pass
        self._staged_last_decision_var.set(f"Latest decision: {latest_label}")
        self._refresh_staged_curation_inbox()
        self._persist_learning_session_state()

    def _on_staged_close_group(self, group_id: str) -> None:
        self.learning_controller.close_discovered_group(group_id)
        if self._staged_current_group_id == group_id:
            self._clear_staged_group()
        self._refresh_staged_curation_inbox()

    def _on_staged_ignore_group(self, group_id: str) -> None:
        self.learning_controller.ignore_discovered_group(group_id)
        if self._staged_current_group_id == group_id:
            self._clear_staged_group()
        self._refresh_staged_curation_inbox()

    def _on_staged_rescan(self) -> None:
        self.staged_inbox_panel.set_scanning(True)
        self.learning_controller.trigger_background_scan(
            output_root=self._resolve_discovered_output_root(),
            on_complete=self._on_staged_scan_complete,
        )

    def _on_staged_scan_complete(self, new_count: int) -> None:
        self.staged_inbox_panel.set_scanning(False)
        self._refresh_staged_curation_inbox()

    def _clear_staged_group(self) -> None:
        self._staged_current_group_id = None
        self._staged_candidates_by_id = {}
        self._staged_items_by_id = {}
        self._staged_latest_events = {}
        self._staged_candidate_tree.delete(*self._staged_candidate_tree.get_children())
        self._staged_group_var.set("Open a discovered group to start staged curation")
        self._update_staged_preview(None)


LearningTabFrame = LearningTabFrame


def _truncate(text: str, max_len: int) -> str:
    if len(text) <= max_len:
        return text
    return text[: max_len - 3] + "..."
