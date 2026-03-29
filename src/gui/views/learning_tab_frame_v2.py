from __future__ import annotations

import tkinter as tk
from pathlib import Path
from tkinter import filedialog, messagebox, ttk
from typing import Any

from src.controller.content_visibility_resolver import REDACTED_TEXT, ContentVisibilityResolver
from src.gui.app_state_v2 import AppStateV2
from src.gui.layout_v2 import configure_grid_columns
from src.gui.help_text.workflow_guidance_v2 import (
    build_discovered_review_guidance,
    build_staged_queue_guidance,
    build_staged_review_guidance,
    get_staged_queue_runtime_guidance,
    get_staged_review_runtime_guidance,
)
from src.gui.controllers.learning_controller import LearningController
from src.gui.learning_review_dialog_v2 import LearningReviewDialogV2
from src.gui.learning_state import LearningState
from src.gui.theme_v2 import BODY_LABEL_STYLE, CARD_FRAME_STYLE, SURFACE_FRAME_STYLE, style_text_widget
from src.gui.tooltip import attach_tooltip
from src.gui.ui_tokens import TOKENS
from src.gui.view_contracts.pipeline_layout_contract import (
    get_three_pane_workspace_column_specs,
    get_two_pane_workspace_column_specs,
)
from src.gui.view_contracts.status_banner_contract import update_status_banner
from src.gui.views.discovered_review_inbox_panel import DiscoveredReviewInboxPanel
from src.gui.views.discovered_review_table import DiscoveredReviewTable
from src.gui.views.experiment_design_panel import ExperimentDesignPanel
from src.gui.views.learning_plan_table import LearningPlanTable
from src.gui.views.learning_review_panel import LearningReviewPanel
from src.gui.widgets.action_explainer_panel_v2 import ActionExplainerPanel
from src.gui.widgets.tab_overview_panel_v2 import TabOverviewPanel, get_tab_overview_content
from src.gui.artifact_metadata_inspector_dialog import ArtifactMetadataInspectorDialog
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
        self._content_visibility_mode = str(
            getattr(getattr(self, "app_state", None), "content_visibility_mode", "nsfw") or "nsfw"
        )
        self._pending_visibility_refresh = False
        self.pipeline_controller = pipeline_controller
        self.app_controller = app_controller  # PR-LEARN-002: Store app_controller reference
        
        # Initialize learning record writer
        self.learning_record_writer = LearningRecordWriter(get_learning_records_path())
        self.experiment_store = LearningExperimentStore(get_learning_experiments_root())
        self._active_experiment_id: str | None = None

        # Initialize learning state and controller
        self.learning_state = LearningState()
        self._custom_discovered_scan_root: str | None = None
        
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
        self.rowconfigure(0, weight=0)  # Overview
        self.rowconfigure(1, weight=0)  # Header
        self.rowconfigure(2, weight=1)  # Body

        self.overview_panel = TabOverviewPanel(
            self,
            content=get_tab_overview_content("learning"),
            app_state=self.app_state,
        )
        self.overview_panel.grid(row=0, column=0, sticky="ew", padx=4, pady=(4, 2))
        self.bind("<Map>", self._on_map, add="+")

        # Header
        self.header_frame = ttk.Frame(self, padding=8, style=SURFACE_FRAME_STYLE)
        self.header_frame.grid(row=1, column=0, sticky="ew", padx=4, pady=(4, 2))
        self.header_frame.columnconfigure(0, weight=1)

        header_label = ttk.Label(
            self.header_frame,
            text="Learning Experiment Workspace",
            font=("TkDefaultFont", 14, "bold"),
            style=BODY_LABEL_STYLE,
        )
        header_label.grid(row=0, column=0, sticky="w")
        self._visibility_banner = ttk.Label(
            self.header_frame,
            text="",
            style=BODY_LABEL_STYLE,
            foreground=TOKENS.colors.status_info,
        )
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
        if self.app_state is not None and hasattr(self.app_state, "subscribe"):
            try:
                self.app_state.subscribe(
                    "content_visibility_mode",
                    self._on_content_visibility_mode_changed,
                )
            except Exception:
                pass
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
        self._mode_notebook.grid(row=2, column=0, sticky="nsew", padx=4, pady=(2, 4))

        # ---- Tab 1: Designed Experiments (existing 3-column layout) ----
        self.body_frame = ttk.Frame(self._mode_notebook, style=SURFACE_FRAME_STYLE)
        self._mode_notebook.add(self.body_frame, text="Designed Experiments")

        # Configure body layout
        configure_grid_columns(self.body_frame, get_three_pane_workspace_column_specs())
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
        configure_grid_columns(self._discovered_tab_frame, get_two_pane_workspace_column_specs())
        self._discovered_tab_frame.rowconfigure(1, weight=1)

        self.discovered_help_panel = ActionExplainerPanel(
            self._discovered_tab_frame,
            content=build_discovered_review_guidance(),
            app_state=self.app_state,
            wraplength=980,
        )
        self.discovered_help_panel.grid(row=0, column=0, columnspan=2, sticky="ew", padx=2, pady=(4, 0))

        self.discovered_inbox_panel = DiscoveredReviewInboxPanel(
            self._discovered_tab_frame,
            on_open_group=self._on_discovered_open_group,
            on_close_group=self._on_discovered_close_group,
            on_ignore_group=self._on_discovered_ignore_group,
            on_rescan=self._on_discovered_rescan,
            on_pick_scan_root=self._on_pick_discovered_scan_root,
            on_reset_scan_root=self._on_reset_discovered_scan_root,
        )
        self.discovered_inbox_panel.grid(row=1, column=0, sticky="nsew", padx=(0, 2), pady=4)

        self.discovered_review_table = DiscoveredReviewTable(
            self._discovered_tab_frame,
            on_rate_item=self._on_discovered_rate_item,
        )
        self.discovered_review_table.grid(row=1, column=1, sticky="nsew", padx=(2, 0), pady=4)

        # ---- Tab 3: Staged Curation ----
        self._staged_tab_frame = ttk.Frame(self._mode_notebook, style=SURFACE_FRAME_STYLE)
        self._mode_notebook.add(self._staged_tab_frame, text="Staged Curation")
        configure_grid_columns(self._staged_tab_frame, get_three_pane_workspace_column_specs())
        self._staged_tab_frame.rowconfigure(0, weight=1)

        self._staged_reason_tag_vars: dict[str, tk.BooleanVar] = {}
        self._staged_candidates_by_id: dict[str, dict[str, Any]] = {}
        self._staged_items_by_id: dict[str, Any] = {}
        self._staged_latest_events: dict[str, Any] = {}
        self._staged_current_group_id: str | None = None
        self._staged_syncing_face_tier = False
        self._staged_face_tier_var = tk.StringVar(value="medium")
        self._staged_job_status_var = tk.StringVar(value="No derived jobs submitted yet")
        self._staged_workflow_summary_var = tk.StringVar(value="Workflow summary: n/a")
        self._staged_replay_summary_var = tk.StringVar(value="Replay chain: n/a")
        self._staged_plan_preview_var = tk.StringVar(value="Derived plan preview: n/a")
        self._staged_effective_settings_var = tk.StringVar(value="Effective settings: select a candidate")
        self._staged_prior_review_var = tk.StringVar(value="Prior Review: none")
        self._staged_queue_guidance_var = tk.StringVar(
            value=get_staged_queue_runtime_guidance(0, 0, 0)
        )
        self._staged_review_guidance_var = tk.StringVar(
            value=get_staged_review_runtime_guidance(None)
        )
        self._staged_queue_buttons: dict[str, ttk.Button] = {}
        self._staged_review_buttons: dict[str, ttk.Button] = {}

        self.staged_inbox_panel = DiscoveredReviewInboxPanel(
            self._staged_tab_frame,
            on_open_group=self._on_staged_open_group,
            on_close_group=self._on_staged_close_group,
            on_ignore_group=self._on_staged_ignore_group,
            on_rescan=self._on_staged_rescan,
            on_pick_scan_root=self._on_pick_discovered_scan_root,
            on_reset_scan_root=self._on_reset_discovered_scan_root,
        )
        self.staged_inbox_panel.grid(row=0, column=0, sticky="nsew", padx=(0, 2), pady=4)

        staged_center = ttk.LabelFrame(
            self._staged_tab_frame,
            text="Candidates",
            padding=(6, 4),
        )
        staged_center.grid(row=0, column=1, sticky="nsew", padx=2, pady=4)
        staged_center.columnconfigure(0, weight=1)
        staged_center.rowconfigure(2, weight=1)

        self._staged_group_var = tk.StringVar(value="Open a discovered group to start staged curation")
        ttk.Label(
            staged_center,
            textvariable=self._staged_group_var,
            style=BODY_LABEL_STYLE,
            justify="left",
            anchor="w",
        ).grid(row=0, column=0, sticky="ew", pady=(0, 4))
        ttk.Label(
            staged_center,
            textvariable=self._staged_workflow_summary_var,
            style=BODY_LABEL_STYLE,
            justify="left",
            anchor="w",
        ).grid(row=1, column=0, sticky="ew", pady=(0, 4))

        candidate_frame = ttk.Frame(staged_center, style=SURFACE_FRAME_STYLE)
        candidate_frame.grid(row=2, column=0, sticky="nsew")
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
        staged_right.rowconfigure(2, weight=1)

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
        ttk.Label(
            staged_right,
            textvariable=self._staged_replay_summary_var,
            style=BODY_LABEL_STYLE,
            justify="left",
            anchor="w",
        ).grid(row=1, column=0, sticky="ew", pady=(0, 4))

        self._staged_preview_thumbnail = ImageThumbnail(
            staged_right,
            max_width=1400,
            max_height=1400,
        )
        self._staged_preview_thumbnail.grid(row=2, column=0, sticky="nsew")
        self._staged_preview_thumbnail.clear()

        plan_frame = ttk.LabelFrame(staged_right, text="Derived Stage Plan Preview", padding=(6, 4))
        plan_frame.grid(row=3, column=0, sticky="ew", pady=(6, 0))
        plan_frame.columnconfigure(0, weight=1)
        ttk.Label(
            plan_frame,
            textvariable=self._staged_plan_preview_var,
            style=BODY_LABEL_STYLE,
            justify="left",
            anchor="w",
        ).grid(row=0, column=0, sticky="ew")

        effective_frame = ttk.LabelFrame(staged_right, text="Effective Settings", padding=(6, 4))
        effective_frame.grid(row=4, column=0, sticky="ew", pady=(6, 0))
        effective_frame.columnconfigure(0, weight=1)
        ttk.Label(
            effective_frame,
            textvariable=self._staged_effective_settings_var,
            style=BODY_LABEL_STYLE,
            justify="left",
            anchor="w",
        ).grid(row=0, column=0, sticky="ew")

        prompt_frame = ttk.LabelFrame(staged_right, text="Source Prompt", padding=(6, 4))
        prompt_frame.grid(row=5, column=0, sticky="ew", pady=(6, 0))
        prompt_frame.columnconfigure(0, weight=1)
        self._staged_source_prompt_text = tk.Text(
            prompt_frame,
            height=4,
            wrap="word",
            state="disabled",
        )
        style_text_widget(self._staged_source_prompt_text, elevated=True)
        self._staged_source_prompt_text.grid(row=0, column=0, sticky="ew")

        negative_prompt_frame = ttk.LabelFrame(
            staged_right,
            text="Source Negative Prompt",
            padding=(6, 4),
        )
        negative_prompt_frame.grid(row=6, column=0, sticky="ew", pady=(6, 0))
        negative_prompt_frame.columnconfigure(0, weight=1)
        self._staged_source_negative_prompt_text = tk.Text(
            negative_prompt_frame,
            height=3,
            wrap="word",
            state="disabled",
        )
        style_text_widget(self._staged_source_negative_prompt_text, elevated=True)
        self._staged_source_negative_prompt_text.grid(row=0, column=0, sticky="ew")

        prior_review_frame = ttk.LabelFrame(staged_right, text="Prior Review", padding=(6, 4))
        prior_review_frame.grid(row=7, column=0, sticky="ew", pady=(6, 0))
        prior_review_frame.columnconfigure(0, weight=1)
        ttk.Label(
            prior_review_frame,
            textvariable=self._staged_prior_review_var,
            style=BODY_LABEL_STYLE,
            justify="left",
            anchor="w",
        ).grid(row=0, column=0, sticky="ew")
        ttk.Button(
            prior_review_frame,
            text="Inspect Metadata",
            command=self._open_staged_metadata_inspector,
        ).grid(row=1, column=0, sticky="w", pady=(6, 0))

        reason_frame = ttk.LabelFrame(staged_right, text="Reason Tags", padding=(6, 4))
        reason_frame.grid(row=8, column=0, sticky="ew", pady=(6, 0))
        for index, tag in enumerate(self.learning_controller.get_staged_curation_reason_tag_options()):
            var = tk.BooleanVar(value=False)
            self._staged_reason_tag_vars[tag] = var
            ttk.Checkbutton(
                reason_frame,
                text=tag.replace("_", " "),
                variable=var,
            ).grid(row=index // 2, column=index % 2, sticky="w", padx=(0, 8), pady=1)

        tier_frame = ttk.LabelFrame(staged_right, text="Face Triage Tier", padding=(6, 4))
        tier_frame.grid(row=9, column=0, sticky="ew", pady=(6, 0))
        tier_frame.columnconfigure(1, weight=1)
        ttk.Label(tier_frame, text="Tier", style=BODY_LABEL_STYLE).grid(
            row=0, column=0, sticky="w", pady=2
        )
        self._staged_face_tier_combo = ttk.Combobox(
            tier_frame,
            textvariable=self._staged_face_tier_var,
            values=self.learning_controller.get_staged_curation_face_triage_tier_options(),
            state="readonly",
            width=18,
        )
        self._staged_face_tier_combo.grid(row=0, column=1, sticky="ew", padx=(8, 0), pady=2)
        self._staged_face_tier_combo.bind(
            "<<ComboboxSelected>>",
            self._on_staged_face_triage_tier_changed,
        )

        notes_frame = ttk.LabelFrame(staged_right, text="Decision Notes", padding=(6, 4))
        notes_frame.grid(row=10, column=0, sticky="ew", pady=(6, 0))
        notes_frame.columnconfigure(0, weight=1)
        self._staged_notes_text = tk.Text(notes_frame, height=4, wrap="word")
        style_text_widget(self._staged_notes_text, elevated=True)
        self._staged_notes_text.grid(row=0, column=0, sticky="ew")

        self._staged_last_decision_var = tk.StringVar(value="Latest decision: none")
        ttk.Label(
            staged_right,
            textvariable=self._staged_last_decision_var,
            style=BODY_LABEL_STYLE,
        ).grid(row=11, column=0, sticky="w", pady=(6, 0))

        action_frame = ttk.Frame(staged_right, style=SURFACE_FRAME_STYLE)
        action_frame.grid(row=12, column=0, sticky="ew", pady=(6, 0))
        self._staged_action_frame = action_frame
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

        derive_frame = ttk.LabelFrame(staged_right, text="Derived Jobs", padding=(6, 4))
        derive_frame.grid(row=13, column=0, sticky="ew", pady=(6, 0))
        self._staged_derive_frame = derive_frame
        self.staged_queue_help_panel = ActionExplainerPanel(
            derive_frame,
            content=build_staged_queue_guidance(),
            app_state=self.app_state,
            wraplength=520,
        )
        self.staged_queue_help_panel.pack(fill="x", pady=(0, 6))
        self._staged_queue_buttons["refine"] = ttk.Button(
            derive_frame,
            text="Queue Refine Now",
            command=lambda: self._submit_staged_jobs("refine"),
        )
        self._staged_queue_buttons["refine"].pack(side="left", padx=(0, 4))
        attach_tooltip(
            self._staged_queue_buttons["refine"],
            "Bulk path. Enqueue every candidate currently marked To Refine. Use this after triage when the whole marked set is ready to run.",
        )
        self._staged_queue_buttons["face_triage"] = ttk.Button(
            derive_frame,
            text="Queue Face Now",
            command=lambda: self._submit_staged_jobs("face_triage"),
        )
        self._staged_queue_buttons["face_triage"].pack(side="left", padx=(0, 4))
        attach_tooltip(
            self._staged_queue_buttons["face_triage"],
            "Bulk path. Enqueue every candidate currently marked To Face. This does not open Review for per-image edits first.",
        )
        self._staged_queue_buttons["upscale"] = ttk.Button(
            derive_frame,
            text="Queue Upscale Now",
            command=lambda: self._submit_staged_jobs("upscale"),
        )
        self._staged_queue_buttons["upscale"].pack(side="left", padx=(0, 4))
        attach_tooltip(
            self._staged_queue_buttons["upscale"],
            "Bulk path. Enqueue every candidate currently marked To Upscale using the staged curation decisions already captured here.",
        )
        ttk.Label(
            derive_frame,
            textvariable=self._staged_queue_guidance_var,
            style=BODY_LABEL_STYLE,
            justify="left",
        ).pack(side="left", padx=(8, 0))
        review_frame = ttk.LabelFrame(staged_right, text="Edit in Review", padding=(6, 4))
        review_frame.grid(row=14, column=0, sticky="ew", pady=(6, 0))
        self._staged_review_frame = review_frame
        self.staged_review_help_panel = ActionExplainerPanel(
            review_frame,
            content=build_staged_review_guidance(),
            app_state=self.app_state,
            wraplength=520,
        )
        self.staged_review_help_panel.pack(fill="x", pady=(0, 6))
        self._staged_review_buttons["refine"] = ttk.Button(
            review_frame,
            text="Edit Refine in Review",
            command=lambda: self._open_staged_in_review("refine"),
        )
        self._staged_review_buttons["refine"].pack(side="left", padx=(0, 4))
        attach_tooltip(
            self._staged_review_buttons["refine"],
            "Deliberate path. Open only the selected candidate in Review when it is marked To Refine, so you can make custom edits before queueing.",
        )
        self._staged_review_buttons["face_triage"] = ttk.Button(
            review_frame,
            text="Edit Face in Review",
            command=lambda: self._open_staged_in_review("face_triage"),
        )
        self._staged_review_buttons["face_triage"].pack(side="left", padx=(0, 4))
        attach_tooltip(
            self._staged_review_buttons["face_triage"],
            "Deliberate path. Open only the selected candidate in Review when it is marked To Face for custom inspection or edits.",
        )
        self._staged_review_buttons["upscale"] = ttk.Button(
            review_frame,
            text="Edit Upscale in Review",
            command=lambda: self._open_staged_in_review("upscale"),
        )
        self._staged_review_buttons["upscale"].pack(side="left", padx=(0, 4))
        attach_tooltip(
            self._staged_review_buttons["upscale"],
            "Deliberate path. Open only the selected candidate in Review when it is marked To Upscale and needs manual adjustment first.",
        )
        ttk.Button(
            review_frame,
            text="Compare Latest Derived",
            command=self._compare_staged_latest_derived,
        ).pack(side="left", padx=(0, 4))
        ttk.Label(
            review_frame,
            textvariable=self._staged_review_guidance_var,
            style=BODY_LABEL_STYLE,
            justify="left",
        ).pack(side="left", padx=(8, 0))
        ttk.Label(
            staged_right,
            textvariable=self._staged_job_status_var,
            style=BODY_LABEL_STYLE,
            justify="left",
        ).grid(row=15, column=0, sticky="w", pady=(6, 0))

        # Refresh inbox when its tab is activated
        self._mode_notebook.bind("<<NotebookTabChanged>>", self._on_notebook_tab_changed)
        self._set_discovered_scan_root(None)
        self._update_staged_action_affordances(None)

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

    def _get_effective_discovered_scan_root(self) -> str:
        return str(self._custom_discovered_scan_root or self._resolve_discovered_output_root())

    def _set_discovered_scan_root(self, scan_root: str | None) -> None:
        self._custom_discovered_scan_root = str(scan_root) if scan_root else None
        if hasattr(self, "discovered_inbox_panel"):
            self.discovered_inbox_panel.set_scan_root(self._custom_discovered_scan_root)
        if hasattr(self, "staged_inbox_panel"):
            self.staged_inbox_panel.set_scan_root(self._custom_discovered_scan_root)

    def _on_pick_discovered_scan_root(self) -> None:
        selected = filedialog.askdirectory(
            title="Choose Learning Scan Folder",
            initialdir=self._get_effective_discovered_scan_root(),
            mustexist=True,
        )
        if not selected:
            return
        self._set_discovered_scan_root(selected)

    def _on_reset_discovered_scan_root(self) -> None:
        self._set_discovered_scan_root(None)

    def _on_discovered_rescan(self) -> None:
        self.discovered_inbox_panel.set_scanning(True)
        self.learning_controller.trigger_background_scan(
            output_root=self._get_effective_discovered_scan_root(),
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
        summary = self.learning_controller.get_staged_curation_workflow_summary(group_id) or {}
        decision_counts = dict(summary.get("decision_counts") or {})
        stage_counts = dict(summary.get("stage_counts") or {})
        summary_bits = [
            f"stages={', '.join(f'{k}:{v}' for k, v in sorted(stage_counts.items())) or 'n/a'}",
            f"decisions={', '.join(f'{k}:{v}' for k, v in sorted(decision_counts.items())) or 'n/a'}",
            f"rated={int(summary.get('rated_count', 0) or 0)}/{int(summary.get('candidate_count', 0) or 0)}",
        ]
        self._staged_workflow_summary_var.set("Workflow summary: " + " | ".join(summary_bits))
        self._staged_job_status_var.set("No derived jobs submitted yet")
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
            self._staged_replay_summary_var.set("Replay chain: n/a")
            self._staged_plan_preview_var.set("Derived plan preview: n/a")
            self._staged_effective_settings_var.set("Effective settings: select a candidate")
            self._staged_prior_review_var.set("Prior Review: none")
            self._staged_last_decision_var.set("Latest decision: none")
            self._staged_preview_thumbnail.clear()
            self._set_readonly_text(self._staged_source_prompt_text, "")
            self._set_readonly_text(self._staged_source_negative_prompt_text, "")
            self._clear_staged_reason_tags()
            self._staged_notes_text.delete("1.0", tk.END)
            self._staged_syncing_face_tier = True
            self._staged_face_tier_var.set("medium")
            self._staged_syncing_face_tier = False
            self._update_staged_action_affordances(None)
            return
        row = self._staged_candidates_by_id.get(candidate_id) or {}
        item = row.get("item")
        if item is None:
            return
        self.learning_controller.learning_state.selected_staged_curation_item_id = candidate_id
        self.learning_controller.learning_state.selected_staged_curation_group_id = self._staged_current_group_id
        latest = self._staged_latest_events.get(candidate_id)
        replay_summary = None
        source_context = None
        if self._staged_current_group_id:
            replay_summary = self.learning_controller.get_staged_curation_candidate_replay_summary(
                self._staged_current_group_id,
                candidate_id,
            )
            source_context = self.learning_controller.get_staged_curation_candidate_source_context(
                self._staged_current_group_id,
                candidate_id,
            )
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
        prior_review_summary = self.learning_controller.get_prior_review_summary(
            str(getattr(item, "artifact_path", "") or "")
        )
        source_prompt = ""
        source_negative_prompt = ""
        if isinstance(source_context, dict):
            source_prompt = str(source_context.get("source_prompt") or "")
            source_negative_prompt = str(source_context.get("source_negative_prompt") or "")
            effective_settings_summary = str(source_context.get("effective_settings_summary") or "").strip()
            target_stage = str(source_context.get("target_stage") or "").replace("_", " ")
            path_label = str(source_context.get("path_label") or "Queue Now")
            if target_stage:
                self._staged_plan_preview_var.set(
                    f"Target stage: {target_stage} | Path: {path_label}"
                )
            else:
                self._staged_plan_preview_var.set(f"Target stage: not queued yet | Path: {path_label}")
        else:
            effective_settings_summary = ""
            self._staged_plan_preview_var.set("Derived plan preview: n/a")
        self._staged_effective_settings_var.set(
            effective_settings_summary or "Effective settings: not available for this candidate yet"
        )
        resolver = self._visibility_resolver()
        visibility_subject = {
            "positive_prompt": source_prompt,
            "negative_prompt": source_negative_prompt,
            "name": str(getattr(item, "artifact_path", "") or ""),
        }
        self._set_readonly_text(
            self._staged_source_prompt_text,
            resolver.redact_text(source_prompt, item=visibility_subject),
        )
        self._set_readonly_text(
            self._staged_source_negative_prompt_text,
            resolver.redact_text(source_negative_prompt, item=visibility_subject),
        )
        self._staged_prior_review_var.set(self._format_prior_review_summary(prior_review_summary))
        if isinstance(replay_summary, dict):
            replay_bits = [
                f"root={replay_summary.get('root_candidate_id') or candidate_id}",
                f"parent={replay_summary.get('parent_candidate_id') or 'none'}",
                f"decision={replay_summary.get('decision') or 'unreviewed'}",
            ]
            source_stage = ""
            source_model = ""
            if isinstance(source_context, dict):
                source_stage = str(source_context.get("source_stage") or "")
                source_model = str(source_context.get("source_model") or "")
            source_summary = " / ".join([part for part in (source_stage, source_model) if part])
            if source_summary:
                replay_bits.append(f"source={source_summary}")
            prompt_summary = _truncate(" ".join(source_prompt.split()), 56) if source_prompt.strip() else ""
            if prompt_summary:
                replay_bits.append(f"prompt={prompt_summary}")
            face_tier = str(replay_summary.get("face_triage_tier") or "").strip()
            if face_tier:
                replay_bits.append(f"face_tier={face_tier}")
            latest_stage = str(replay_summary.get("latest_derived_stage") or "").strip()
            latest_path = str(replay_summary.get("latest_derived_path") or "").strip()
            if latest_stage:
                replay_bits.append(f"latest={latest_stage}")
            if latest_path:
                replay_bits.append(f"derived={Path(latest_path).name}")
            self._staged_replay_summary_var.set("Replay chain: " + " | ".join(replay_bits))
        else:
            self._staged_replay_summary_var.set("Replay chain: n/a")
        tier_value = str(getattr(item, "extra_fields", {}).get("face_triage_tier") or "medium")
        self._staged_syncing_face_tier = True
        self._staged_face_tier_var.set(tier_value)
        self._staged_syncing_face_tier = False
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
        self._update_staged_action_affordances(candidate_id)
        self._persist_learning_session_state()

    def _clear_staged_reason_tags(self) -> None:
        for var in self._staged_reason_tag_vars.values():
            var.set(False)

    def _collect_staged_reason_tags(self) -> list[str]:
        return [tag for tag, var in self._staged_reason_tag_vars.items() if bool(var.get())]

    def _open_staged_metadata_inspector(self) -> None:
        selection = self._staged_candidate_tree.selection()
        candidate_id = selection[0] if selection else None
        if not candidate_id:
            messagebox.showinfo("Metadata Inspector", "Select a candidate first.")
            return
        row = self._staged_candidates_by_id.get(candidate_id) or {}
        item = row.get("item")
        image_path = str(getattr(item, "artifact_path", "") or "").strip() if item is not None else ""
        if not image_path:
            messagebox.showinfo("Metadata Inspector", "Selected candidate does not have an artifact path.")
            return

        def _refresh() -> dict[str, Any] | None:
            return self.learning_controller.inspect_artifact_metadata(image_path)

        try:
            payload = self.learning_controller.inspect_artifact_metadata(image_path)
        except Exception as exc:
            messagebox.showerror("Metadata Inspector", str(exc))
            return
        ArtifactMetadataInspectorDialog(self, inspection_payload=payload, on_refresh=_refresh)

    @staticmethod
    def _format_prior_review_summary(summary: Any) -> str:
        if not isinstance(summary, dict):
            return "Prior Review: none"
        source_label_map = {
            "internal_learning_record": "internal learning record",
            "embedded_review_metadata": "embedded artifact metadata",
            "sidecar_review_metadata": "sidecar artifact metadata",
        }
        source_type = str(summary.get("source_type") or "")
        rating = summary.get("user_rating")
        quality = str(summary.get("quality_label") or "")
        timestamp = str(summary.get("review_timestamp") or "")
        notes = str(summary.get("user_notes") or "").strip()
        prompt_changed = bool(
            str(summary.get("prompt_delta") or "").strip()
            or str(summary.get("negative_prompt_delta") or "").strip()
        )
        bits = [
            f"Source: {source_label_map.get(source_type, source_type.replace('_', ' ') or 'portable metadata')}",
        ]
        if rating is not None:
            rating_text = f"Rating: {rating}"
            if quality:
                rating_text += f" ({quality})"
            bits.append(rating_text)
        elif quality:
            bits.append(f"Quality: {quality}")
        if timestamp:
            bits.append(f"Reviewed on: {timestamp}")
        if notes:
            notes_excerpt = notes if len(notes) <= 80 else f"{notes[:77]}..."
            bits.append(f"Notes: {notes_excerpt}")
        bits.append(f"Prompt changed: {'yes' if prompt_changed else 'no'}")
        return " | ".join(bits)

    @staticmethod
    def _target_stage_for_decision(decision: str) -> str | None:
        mapping = {
            "advanced_to_refine": "refine",
            "advanced_to_face_triage": "face_triage",
            "advanced_to_upscale": "upscale",
        }
        return mapping.get(str(decision or "").strip().lower())

    def _count_marked_candidates_for_stage(self, target_stage: str) -> int:
        count = 0
        for event in self._staged_latest_events.values():
            event_target = self._target_stage_for_decision(str(getattr(event, "decision", "") or ""))
            if event_target == target_stage:
                count += 1
        return count

    def _update_staged_action_affordances(self, candidate_id: str | None) -> None:
        selected_target = None
        if candidate_id:
            latest = self._staged_latest_events.get(candidate_id)
            selected_target = self._target_stage_for_decision(str(getattr(latest, "decision", "") or ""))

        for target_stage, button in self._staged_queue_buttons.items():
            marked_count = self._count_marked_candidates_for_stage(target_stage)
            button.configure(state=("normal" if marked_count > 0 else "disabled"))

        for target_stage, button in self._staged_review_buttons.items():
            button.configure(state=("normal" if selected_target == target_stage else "disabled"))

        refine_count = self._count_marked_candidates_for_stage("refine")
        face_count = self._count_marked_candidates_for_stage("face_triage")
        upscale_count = self._count_marked_candidates_for_stage("upscale")
        self._staged_queue_guidance_var.set(
            get_staged_queue_runtime_guidance(refine_count, face_count, upscale_count)
        )

        if not candidate_id:
            self._staged_review_guidance_var.set(get_staged_review_runtime_guidance(None, None))
            return

        if selected_target is None:
            self._staged_review_guidance_var.set(get_staged_review_runtime_guidance(None))
            return

        marked_count = self._count_marked_candidates_for_stage(selected_target)
        self._staged_review_guidance_var.set(
            get_staged_review_runtime_guidance(selected_target, marked_count)
        )

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
        self._update_staged_preview(candidate_id)
        self._persist_learning_session_state()

    def _on_staged_face_triage_tier_changed(self, _event: Any = None) -> None:
        if self._staged_syncing_face_tier:
            return
        selection = self._staged_candidate_tree.selection()
        candidate_id = selection[0] if selection else None
        if not self._staged_current_group_id or not candidate_id:
            return
        tier = str(self._staged_face_tier_var.get() or "medium")
        if not self.learning_controller.set_staged_curation_face_triage_tier(
            self._staged_current_group_id,
            candidate_id,
            tier,
        ):
            return
        row = self._staged_candidates_by_id.get(candidate_id) or {}
        item = row.get("item")
        if item is not None:
            extra_fields = dict(getattr(item, "extra_fields", {}) or {})
            extra_fields["face_triage_tier"] = tier
            item.extra_fields = extra_fields
        self._update_staged_preview(candidate_id)
        self._staged_job_status_var.set(f"Face triage tier set to {tier} for {candidate_id}")
        self._persist_learning_session_state()

    def _set_readonly_text(self, widget: tk.Text, value: str) -> None:
        widget.configure(state="normal")
        widget.delete("1.0", tk.END)
        widget.insert("1.0", value.strip() or "(not available)")
        widget.configure(state="disabled")

    def _visibility_resolver(self) -> ContentVisibilityResolver:
        return ContentVisibilityResolver(self._content_visibility_mode)

    def on_content_visibility_mode_changed(self, mode: str | None = None) -> None:
        self._content_visibility_mode = str(
            mode or getattr(getattr(self, "app_state", None), "content_visibility_mode", "nsfw") or "nsfw"
        )
        self._pending_visibility_refresh = False
        self._visibility_banner.configure(text="")
        review_panel = getattr(self, "review_panel", None)
        if review_panel is not None:
            callback = getattr(review_panel, "on_content_visibility_mode_changed", None)
            if callable(callback):
                try:
                    callback(self._content_visibility_mode)
                except Exception:
                    pass
        self._refresh_discovered_inbox()
        self._refresh_staged_curation_inbox()
        self._update_staged_preview(
            self.learning_state.selected_staged_curation_item_id
            if getattr(self.learning_state, "selected_staged_curation_item_id", None)
            else None
        )

    def _on_content_visibility_mode_changed(self) -> None:
        if not bool(self.winfo_ismapped()):
            self._pending_visibility_refresh = True
            self._content_visibility_mode = str(
                getattr(getattr(self, "app_state", None), "content_visibility_mode", "nsfw") or "nsfw"
            )
            return
        self.on_content_visibility_mode_changed()

    def _on_map(self, _event: Any = None) -> None:
        if not self._pending_visibility_refresh:
            return
        self.after_idle(lambda: self.on_content_visibility_mode_changed(self._content_visibility_mode))

    def _submit_staged_jobs(self, target_stage: str) -> None:
        if not self._staged_current_group_id:
            messagebox.showinfo("Staged Curation", "Open a staged-curation group first.")
            return
        try:
            submitted = self.learning_controller.submit_staged_curation_advancement(
                self._staged_current_group_id,
                target_stage,
            )
        except Exception as exc:
            self._staged_job_status_var.set(f"Failed to submit {target_stage} jobs: {exc}")
            messagebox.showerror("Staged Curation", f"Failed to submit {target_stage} jobs:\n{exc}")
            return
        if submitted <= 0:
            label = target_stage.replace("_", " ")
            self._staged_job_status_var.set(f"No staged-curation candidates are marked for {label}.")
            messagebox.showinfo(
                "Staged Curation",
                f"No candidates are currently marked for {label}.",
            )
            return
        label = target_stage.replace("_", " ")
        self._staged_job_status_var.set(f"Submitted {submitted} {label} job(s) to the queue.")
        self._persist_learning_session_state()

    def _open_staged_in_review(self, target_stage: str) -> None:
        if not self._staged_current_group_id:
            messagebox.showinfo("Staged Curation", "Open a staged-curation group first.")
            return

        selection = self._staged_candidate_tree.selection()
        candidate_id = selection[0] if selection else None
        if not candidate_id:
            messagebox.showinfo("Staged Curation", "Select a candidate first.")
            return

        latest = self._staged_latest_events.get(candidate_id)
        selected_target = self._target_stage_for_decision(str(getattr(latest, "decision", "") or ""))
        if selected_target != target_stage:
            label = target_stage.replace("_", " ")
            self._staged_job_status_var.set(
                f"Review stays single-candidate. Select one item marked for {label} first."
            )
            messagebox.showinfo(
                "Staged Curation",
                f"Select one candidate marked for {label} before opening Review.",
            )
            self._update_staged_action_affordances(candidate_id)
            return

        try:
            handoff = self.learning_controller.build_staged_curation_review_handoff(
                self._staged_current_group_id,
                target_stage,
                candidate_id=candidate_id,
            )
        except Exception as exc:
            self._staged_job_status_var.set(f"Failed to open {target_stage} in Review: {exc}")
            messagebox.showerror("Staged Curation", f"Failed to open {target_stage} in Review:\n{exc}")
            return

        if handoff is None or not handoff.image_paths:
            label = target_stage.replace("_", " ")
            self._staged_job_status_var.set(f"No staged-curation candidates are marked for {label}.")
            messagebox.showinfo(
                "Staged Curation",
                f"No candidates are currently marked for {label}.",
            )
            return

        main_window = getattr(self.app_controller, "main_window", None) if self.app_controller else None
        review_tab = getattr(main_window, "review_tab", None)
        if review_tab is None:
            messagebox.showerror("Review unavailable", "Review tab is not connected.")
            return

        loader = getattr(review_tab, "load_staged_curation_handoff", None)
        if not callable(loader):
            messagebox.showerror(
                "Review unavailable",
                "Connected Review tab does not support staged-curation handoff.",
            )
            return

        loader(handoff)
        notebook = getattr(main_window, "center_notebook", None)
        if notebook is not None:
            try:
                notebook.select(review_tab)
            except Exception:
                pass

        label = target_stage.replace("_", " ")
        marked_count = self._count_marked_candidates_for_stage(target_stage)
        self._staged_job_status_var.set(
            f"Opened the selected {label} candidate in Review. "
            f"Queue {label} now would enqueue {marked_count} marked candidate(s)."
        )
        self._persist_learning_session_state()

    def _compare_staged_latest_derived(self) -> None:
        selection = self._staged_candidate_tree.selection()
        candidate_id = selection[0] if selection else None
        if not candidate_id:
            messagebox.showinfo("Staged Curation", "Select a candidate first.")
            return

        row = self._staged_candidates_by_id.get(candidate_id) or {}
        item = row.get("item")
        image_path = Path(str(getattr(item, "artifact_path", "") or "").strip()) if item is not None else None
        if image_path is None or not str(image_path):
            messagebox.showinfo("Staged Curation", "The selected candidate does not have a source image.")
            return

        main_window = getattr(self.app_controller, "main_window", None) if self.app_controller else None
        review_tab = getattr(main_window, "review_tab", None)
        if review_tab is None:
            messagebox.showerror("Review unavailable", "Review tab is not connected.")
            return

        opener = getattr(review_tab, "open_staged_candidate_latest_derived_compare", None)
        if not callable(opener):
            messagebox.showerror(
                "Review unavailable",
                "Connected Review tab does not support latest-derived comparison.",
            )
            return

        opened = opener(
            image_path=image_path,
            candidate_id=str(candidate_id),
            workflow_title=str(self._staged_group_var.get() or ""),
        )
        if not opened:
            return

        notebook = getattr(main_window, "center_notebook", None)
        if notebook is not None:
            try:
                notebook.select(review_tab)
            except Exception:
                pass

        self._staged_job_status_var.set(
            f"Opened latest derived comparison in Review for {candidate_id}."
        )
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
            output_root=self._get_effective_discovered_scan_root(),
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
        self._staged_workflow_summary_var.set("Workflow summary: n/a")
        self._staged_replay_summary_var.set("Replay chain: n/a")
        self._staged_plan_preview_var.set("Derived plan preview: n/a")
        self._staged_effective_settings_var.set("Effective settings: select a candidate")
        self._staged_job_status_var.set("No derived jobs submitted yet")
        self._update_staged_action_affordances(None)
        self._update_staged_preview(None)


LearningTabFrame = LearningTabFrame


def _truncate(text: str, max_len: int) -> str:
    if len(text) <= max_len:
        return text
    return text[: max_len - 3] + "..."
