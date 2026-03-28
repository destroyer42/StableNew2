from __future__ import annotations

import tkinter as tk
from pathlib import Path
from tkinter import filedialog, messagebox, ttk
from typing import Any

from src.controller.content_visibility_resolver import REDACTED_TEXT, ContentVisibilityResolver
from src.gui.layout_v2 import configure_grid_columns
from src.queue.job_history_store import JobHistoryEntry
from src.gui.help_text.workflow_guidance_v2 import (
    REVIEW_DEFAULT_WORKFLOW_HINT,
    build_review_action_guidance,
    get_review_handoff_hint,
)
from src.gui.artifact_metadata_inspector_dialog import ArtifactMetadataInspectorDialog
from src.gui.controllers.review_workflow_adapter import ReviewWorkflowAdapter, ReviewWorkspaceHandoff
from src.gui.theme_v2 import apply_toplevel_theme, style_canvas_widget, style_listbox_widget, style_text_widget
from src.gui.tooltip import attach_tooltip
from src.gui.ui_tokens import TOKENS
from src.gui.view_contracts.pipeline_layout_contract import (
    PRIMARY_CONTROL_MIN_WIDTH,
    get_single_pair_form_column_specs,
    get_two_pane_workspace_column_specs,
)
from src.gui.widgets.action_explainer_panel_v2 import ActionExplainerPanel
from src.gui.widgets.tab_overview_panel_v2 import TabOverviewPanel, get_tab_overview_content
from src.gui.widgets.thumbnail_widget_v2 import ThumbnailWidget
from src.utils.image_metadata import (
    extract_embedded_metadata,
    resolve_model_vae_fields,
    resolve_prompt_fields,
)

try:
    from PIL import Image, ImageTk

    PIL_AVAILABLE = True
except ImportError:
    PIL_AVAILABLE = False


class ReviewTabFrame(ttk.Frame):
    """MVP tab for reviewing existing images and reprocessing with prompt edits."""

    def __init__(
        self,
        master: tk.Misc,
        *,
        app_controller: Any = None,
        app_state: Any = None,
        **kwargs: Any,
    ) -> None:
        super().__init__(master, **kwargs)
        self.app_controller = app_controller
        self.app_state = app_state
        self._workflow_adapter = ReviewWorkflowAdapter()
        self._default_workflow_hint = REVIEW_DEFAULT_WORKFLOW_HINT

        self.selected_images: list[Path] = []
        self._image_index_by_row: list[Path] = []

        self.stage_img2img_var = tk.BooleanVar(value=False)
        self.stage_adetailer_var = tk.BooleanVar(value=True)
        self.stage_upscale_var = tk.BooleanVar(value=False)
        self.prompt_mode_var = tk.StringVar(value="append")
        self.negative_mode_var = tk.StringVar(value="append")
        self._prompt_prev_mode = "append"
        self._negative_prev_mode = "append"
        self._prompt_mode_edits: dict[str, str] = {
            "append": "",
            "replace": "",
            "modify": "",
        }
        self._negative_mode_edits: dict[str, str] = {
            "append": "",
            "replace": "",
            "modify": "",
        }
        self.batch_size_var = tk.IntVar(value=1)
        self.rating_var = tk.IntVar(value=3)
        self.anatomy_rating_var = tk.IntVar(value=3)
        self.composition_rating_var = tk.IntVar(value=3)
        self.prompt_adherence_rating_var = tk.IntVar(value=3)
        self.quality_var = tk.StringVar(value="okay")
        self._effective_settings_var = tk.StringVar(value="Effective settings: select an image")
        self._prior_review_summary_var = tk.StringVar(value="Prior Review Summary: none")
        self._feedback_undo_stack: list[list[dict[str, str]]] = []
        self._selected_base_prompt = ""
        self._selected_base_negative_prompt = ""
        self._selected_image_path: Path | None = None
        self._compare_window: tk.Toplevel | None = None
        self._compare_canvas: tk.Canvas | None = None
        self._compare_photo: Any = None
        self._compare_mode = "single"
        self._history_import_window: tk.Toplevel | None = None
        self._active_handoff: ReviewWorkspaceHandoff | None = None
        self._content_visibility_mode = str(
            getattr(getattr(self, "app_state", None), "content_visibility_mode", "nsfw") or "nsfw"
        )

        self.columnconfigure(0, weight=1)
        self.rowconfigure(0, weight=0)
        self.rowconfigure(1, weight=0)
        self.rowconfigure(2, weight=1)
        self.rowconfigure(3, weight=0)

        self.overview_panel = TabOverviewPanel(
            self,
            content=get_tab_overview_content("review"),
            app_state=self.app_state,
        )
        self.overview_panel.grid(row=0, column=0, sticky="ew", padx=6, pady=(6, 0))

        self._build_header()
        self._build_body()
        self._build_controls()

        self.prompt_mode_var.trace_add("write", lambda *_: self._on_prompt_mode_changed())
        self.negative_mode_var.trace_add("write", lambda *_: self._on_negative_mode_changed())
        self.stage_img2img_var.trace_add("write", lambda *_: self._refresh_effective_settings())
        self.stage_adetailer_var.trace_add("write", lambda *_: self._refresh_effective_settings())
        self.stage_upscale_var.trace_add("write", lambda *_: self._refresh_effective_settings())
        self.prompt_text.bind("<KeyRelease>", lambda _e: self._refresh_prompt_diff())
        self.negative_text.bind("<KeyRelease>", lambda _e: self._refresh_prompt_diff())
        self._set_readonly_text(self.current_prompt_text, "")
        self._set_readonly_text(self.current_negative_text, "")
        self._sync_edit_box_to_mode("prompt")
        self._sync_edit_box_to_mode("negative")
        self._refresh_prompt_diff()
        if self.app_state is not None and hasattr(self.app_state, "subscribe"):
            try:
                self.app_state.subscribe(
                    "content_visibility_mode",
                    self._on_content_visibility_mode_changed,
                )
            except Exception:
                pass
        self.on_content_visibility_mode_changed(self._content_visibility_mode)

    def _build_header(self) -> None:
        header = ttk.Frame(self, style="Panel.TFrame", padding=8)
        header.grid(row=1, column=0, sticky="ew", padx=6, pady=(6, 4))
        header.columnconfigure(5, weight=1)

        ttk.Button(
            header,
            text="Select Images",
            style="Dark.TButton",
            command=self._on_select_images,
        ).grid(row=0, column=0, sticky="w", padx=(0, 6))

        ttk.Button(
            header,
            text="Select Folder",
            style="Dark.TButton",
            command=self._on_select_folder,
        ).grid(row=0, column=1, sticky="w", padx=(0, 6))

        ttk.Button(
            header,
            text="Clear",
            style="Dark.TButton",
            command=self._on_clear,
        ).grid(row=0, column=2, sticky="w")

        self.import_selected_button = ttk.Button(
            header,
            text="Import Selected to Learning",
            style="Dark.TButton",
            command=self._on_import_selected_to_staged_curation,
        )
        self.import_selected_button.grid(row=0, column=3, sticky="w", padx=(6, 0))

        self.import_recent_button = ttk.Button(
            header,
            text="Import Recent Job",
            style="Dark.TButton",
            command=self._on_open_history_import_picker,
        )
        self.import_recent_button.grid(row=0, column=4, sticky="w", padx=(6, 0))

        self.selection_label = ttk.Label(
            header,
            text="No images selected",
            style="Dark.TLabel",
        )
        self.selection_label.grid(row=0, column=5, sticky="e")
        self.visibility_banner = ttk.Label(header, text="", style="Dark.TLabel")

        self.workflow_hint_label = ttk.Label(
            header,
            text=self._default_workflow_hint,
            style="Dark.TLabel",
        )
        self.workflow_hint_label.grid(row=1, column=0, columnspan=5, sticky="w", pady=(6, 0))
        self.action_help_panel = ActionExplainerPanel(
            header,
            content=build_review_action_guidance(),
            app_state=self.app_state,
            wraplength=980,
        )
        self.action_help_panel.grid(row=2, column=0, columnspan=6, sticky="ew", pady=(8, 0))
        self.import_selected_tooltip = attach_tooltip(
            self.import_selected_button,
            "Move the selected reviewed images into Learning staged curation. This records them as evidence candidates; it does not queue a new reprocess job by itself.",
        )
        self.import_recent_tooltip = attach_tooltip(
            self.import_recent_button,
            "Open a recent history job and import its outputs into this Review workspace so you can inspect metadata or make deliberate edits.",
        )

    def _build_body(self) -> None:
        body = ttk.Frame(self, style="Panel.TFrame")
        body.grid(row=2, column=0, sticky="nsew", padx=6, pady=4)
        configure_grid_columns(body, get_two_pane_workspace_column_specs())
        body.rowconfigure(0, weight=1)
        self._body_frame = body

        left = ttk.LabelFrame(body, text="Images", style="Dark.TLabelframe", padding=8)
        left.grid(row=0, column=0, sticky="nsew", padx=(0, 6))
        left.columnconfigure(0, weight=1)
        left.rowconfigure(0, weight=1)

        self.images_list = tk.Listbox(
            left,
            bg=TOKENS.colors.surface_secondary,
            fg=TOKENS.colors.text_primary,
            selectbackground=TOKENS.colors.accent_primary,
            selectforeground=TOKENS.colors.text_primary,
            selectmode=tk.EXTENDED,
            borderwidth=0,
            highlightthickness=1,
            highlightbackground=TOKENS.colors.border_subtle,
            exportselection=False,
        )
        style_listbox_widget(self.images_list)
        self.images_list.grid(row=0, column=0, sticky="nsew")
        self.images_list.bind("<<ListboxSelect>>", self._on_image_select)

        list_scroll = ttk.Scrollbar(left, orient="vertical", command=self.images_list.yview)
        list_scroll.grid(row=0, column=1, sticky="ns")
        self.images_list.configure(yscrollcommand=list_scroll.set)

        right = ttk.LabelFrame(body, text="Preview & Metadata", style="Dark.TLabelframe", padding=8)
        right.grid(row=0, column=1, sticky="nsew")
        right.columnconfigure(0, weight=1)

        preview_actions = ttk.Frame(right, style="Panel.TFrame")
        preview_actions.grid(row=0, column=0, sticky="ew", pady=(0, 6))
        ttk.Button(
            preview_actions,
            text="Prev",
            style="Dark.TButton",
            command=self._show_previous_image,
        ).pack(side="left")
        ttk.Button(
            preview_actions,
            text="Next",
            style="Dark.TButton",
            command=self._show_next_image,
        ).pack(side="left", padx=(6, 0))
        ttk.Button(
            preview_actions,
            text="Large Compare",
            style="Dark.TButton",
            command=self._open_compare_viewer,
        ).pack(side="left", padx=(12, 0))
        ttk.Button(
            preview_actions,
            text="Compare Latest Derived",
            style="Dark.TButton",
            command=self._open_latest_derived_compare,
        ).pack(side="left", padx=(6, 0))
        ttk.Button(
            preview_actions,
            text="Inspect Metadata",
            style="Dark.TButton",
            command=self._open_metadata_inspector,
        ).pack(side="left", padx=(6, 0))

        self.preview = ThumbnailWidget(right, width=620, height=620, placeholder_text="Select an image")
        self.preview.grid(row=1, column=0, sticky="n", pady=(0, 8))
        self.preview._canvas.bind("<Double-Button-1>", lambda _event: self._open_compare_viewer())

        self.meta_label = ttk.Label(
            right,
            text="Metadata: n/a",
            style="Dark.TLabel",
            justify="left",
            wraplength=620,
        )
        self.meta_label.grid(row=2, column=0, sticky="ew")

        prior_review_box = ttk.LabelFrame(
            right,
            text="Prior Review Summary",
            style="Dark.TLabelframe",
            padding=8,
        )
        prior_review_box.grid(row=3, column=0, sticky="ew", pady=(8, 0))
        prior_review_box.columnconfigure(0, weight=1)
        ttk.Label(
            prior_review_box,
            textvariable=self._prior_review_summary_var,
            style="Dark.TLabel",
            justify="left",
            wraplength=620,
        ).grid(row=0, column=0, sticky="ew")

    def _build_controls(self) -> None:
        controls = ttk.Frame(self, style="Panel.TFrame")
        controls.grid(row=3, column=0, sticky="ew", padx=6, pady=(4, 6))
        configure_grid_columns(
            controls,
            get_two_pane_workspace_column_specs(
                left_min_width=420,
                right_min_width=360,
            ),
        )
        self._controls_frame = controls

        prompt_box = ttk.LabelFrame(
            controls,
            text="Current Prompts + Edits",
            style="Dark.TLabelframe",
            padding=8,
        )
        prompt_box.grid(row=0, column=0, sticky="nsew", padx=(0, 6))
        configure_grid_columns(prompt_box, get_single_pair_form_column_specs())
        prompt_box.rowconfigure(1, weight=0)
        prompt_box.rowconfigure(3, weight=0)

        ttk.Label(prompt_box, text="Current + prompt", style="Dark.TLabel").grid(
            row=0, column=0, columnspan=2, sticky="w", pady=(0, 4)
        )
        self.current_prompt_text = tk.Text(
            prompt_box,
            height=3,
            bg=TOKENS.colors.surface_tertiary,
            fg=TOKENS.colors.text_muted,
            insertbackground=TOKENS.colors.text_muted,
            wrap="word",
            borderwidth=1,
            relief="solid",
        )
        style_text_widget(self.current_prompt_text, elevated=True)
        self.current_prompt_text.configure(
            fg=TOKENS.colors.text_muted,
            insertbackground=TOKENS.colors.text_muted,
        )
        self.current_prompt_text.grid(row=1, column=0, columnspan=2, sticky="ew", pady=(0, 8))

        ttk.Label(prompt_box, text="Positive mode", style="Dark.TLabel").grid(
            row=2, column=0, sticky="w", padx=(0, 6), pady=(0, 4)
        )
        ttk.Combobox(
            prompt_box,
            textvariable=self.prompt_mode_var,
            values=["append", "replace", "modify"],
            state="readonly",
            style="Dark.TCombobox",
            width=10,
        ).grid(row=2, column=1, sticky="w", pady=(0, 4))

        self.prompt_text = tk.Text(
            prompt_box,
            height=4,
            bg=TOKENS.colors.surface_secondary,
            fg=TOKENS.colors.text_primary,
            insertbackground=TOKENS.colors.text_primary,
            wrap="word",
            borderwidth=1,
            relief="solid",
        )
        style_text_widget(self.prompt_text, elevated=True)
        self.prompt_text.grid(row=3, column=0, columnspan=2, sticky="ew", pady=(0, 8))

        ttk.Label(prompt_box, text="Current - prompt", style="Dark.TLabel").grid(
            row=4, column=0, columnspan=2, sticky="w", pady=(0, 4)
        )
        self.current_negative_text = tk.Text(
            prompt_box,
            height=3,
            bg=TOKENS.colors.surface_tertiary,
            fg=TOKENS.colors.text_muted,
            insertbackground=TOKENS.colors.text_muted,
            wrap="word",
            borderwidth=1,
            relief="solid",
        )
        style_text_widget(self.current_negative_text, elevated=True)
        self.current_negative_text.configure(
            fg=TOKENS.colors.text_muted,
            insertbackground=TOKENS.colors.text_muted,
        )
        self.current_negative_text.grid(row=5, column=0, columnspan=2, sticky="ew", pady=(0, 8))

        ttk.Label(prompt_box, text="Negative mode", style="Dark.TLabel").grid(
            row=6, column=0, sticky="w", padx=(0, 6), pady=(0, 4)
        )
        ttk.Combobox(
            prompt_box,
            textvariable=self.negative_mode_var,
            values=["append", "replace", "modify"],
            state="readonly",
            style="Dark.TCombobox",
            width=10,
        ).grid(row=6, column=1, sticky="w", pady=(0, 4))

        self.negative_text = tk.Text(
            prompt_box,
            height=4,
            bg=TOKENS.colors.surface_secondary,
            fg=TOKENS.colors.text_primary,
            insertbackground=TOKENS.colors.text_primary,
            wrap="word",
            borderwidth=1,
            relief="solid",
        )
        style_text_widget(self.negative_text, elevated=True)
        self.negative_text.grid(row=7, column=0, columnspan=2, sticky="ew")

        diff_box = ttk.LabelFrame(
            prompt_box,
            text="Before / After Diff",
            style="Dark.TLabelframe",
            padding=8,
        )
        diff_box.grid(row=8, column=0, columnspan=2, sticky="ew", pady=(8, 0))
        diff_box.columnconfigure(0, weight=1)

        self.diff_before_label = ttk.Label(
            diff_box,
            text="Before: (select an image)",
            style="Dark.TLabel",
            justify="left",
            wraplength=520,
        )
        self.diff_before_label.grid(row=0, column=0, sticky="ew", pady=(0, 4))

        self.diff_after_label = ttk.Label(
            diff_box,
            text="After: (no changes)",
            style="Dark.TLabel",
            justify="left",
            wraplength=520,
        )
        self.diff_after_label.grid(row=1, column=0, sticky="ew")

        run_box = ttk.LabelFrame(
            controls,
            text="Reprocess",
            style="Dark.TLabelframe",
            padding=8,
        )
        run_box.grid(row=0, column=1, sticky="nsew")
        run_box.columnconfigure(0, weight=1)

        ttk.Checkbutton(
            run_box,
            text="img2img",
            variable=self.stage_img2img_var,
            style="Dark.TCheckbutton",
        ).grid(row=0, column=0, sticky="w", pady=(0, 2))
        ttk.Checkbutton(
            run_box,
            text="adetailer",
            variable=self.stage_adetailer_var,
            style="Dark.TCheckbutton",
        ).grid(row=1, column=0, sticky="w", pady=(0, 2))
        ttk.Checkbutton(
            run_box,
            text="upscale",
            variable=self.stage_upscale_var,
            style="Dark.TCheckbutton",
        ).grid(row=2, column=0, sticky="w", pady=(0, 8))

        effective_box = ttk.LabelFrame(
            run_box,
            text="Effective Reprocess Settings",
            style="Dark.TLabelframe",
            padding=8,
        )
        effective_box.grid(row=3, column=0, sticky="ew", pady=(0, 8))
        effective_box.columnconfigure(0, weight=1)
        ttk.Label(
            effective_box,
            textvariable=self._effective_settings_var,
            style="Dark.TLabel",
            justify="left",
            wraplength=520,
        ).grid(row=0, column=0, sticky="ew")

        batch_row = ttk.Frame(run_box, style="Panel.TFrame")
        batch_row.grid(row=4, column=0, sticky="ew", pady=(0, 8))
        ttk.Label(batch_row, text="Batch size", style="Dark.TLabel").pack(side="left", padx=(0, 8))
        ttk.Spinbox(
            batch_row,
            from_=1,
            to=64,
            increment=1,
            textvariable=self.batch_size_var,
            width=6,
            style="Dark.TSpinbox",
        ).pack(side="left")
        ttk.Label(batch_row, text="(groups by compatible settings)", style="Dark.TLabel").pack(
            side="left", padx=(8, 0)
        )
        batch_help_btn = ttk.Button(
            batch_row,
            text="?",
            width=3,
            style="Dark.TButton",
            command=self._show_batch_logic_help,
        )
        batch_help_btn.pack(side="left", padx=(8, 0))
        attach_tooltip(
            batch_help_btn,
            "Batching only combines images with identical effective prompt/model/config. "
            "Different settings are split into separate jobs.",
        )

        self.reprocess_selected_button = ttk.Button(
            run_box,
            text="Reprocess Selected",
            style="Primary.TButton",
            command=lambda: self._reprocess(batch_all=False),
        )
        self.reprocess_selected_button.grid(row=5, column=0, sticky="ew", pady=(0, 6))

        self.reprocess_all_button = ttk.Button(
            run_box,
            text="Reprocess All",
            style="Dark.TButton",
            command=lambda: self._reprocess(batch_all=True),
        )
        self.reprocess_all_button.grid(row=6, column=0, sticky="ew")
        attach_tooltip(
            self.reprocess_selected_button,
            "Queue only the currently selected images for reprocessing with the checked stages and prompt edits shown in Review.",
        )
        attach_tooltip(
            self.reprocess_all_button,
            "Queue every loaded image with the current Review settings. Use this only after confirming the effective settings summary and batch behavior.",
        )

        feedback_box = ttk.LabelFrame(
            run_box,
            text="Review Feedback",
            style="Dark.TLabelframe",
            padding=8,
        )
        feedback_box.grid(row=7, column=0, sticky="ew", pady=(8, 0))
        configure_grid_columns(feedback_box, get_single_pair_form_column_specs())
        ttk.Label(feedback_box, text="Rating", style="Dark.TLabel").grid(
            row=0, column=0, sticky="w", padx=(0, 6), pady=(0, 4)
        )
        ttk.Spinbox(
            feedback_box,
            from_=1,
            to=5,
            increment=1,
            textvariable=self.rating_var,
            width=6,
            style="Dark.TSpinbox",
        ).grid(row=0, column=1, sticky="w", pady=(0, 4))
        ttk.Label(feedback_box, text="Quality", style="Dark.TLabel").grid(
            row=1, column=0, sticky="w", padx=(0, 6), pady=(0, 4)
        )
        ttk.Combobox(
            feedback_box,
            textvariable=self.quality_var,
            values=["reject", "poor", "okay", "good", "excellent"],
            state="readonly",
            style="Dark.TCombobox",
            width=12,
        ).grid(row=1, column=1, sticky="w", pady=(0, 4))
        ttk.Label(feedback_box, text="Notes", style="Dark.TLabel").grid(
            row=2, column=0, sticky="nw", padx=(0, 6)
        )
        self.feedback_notes = tk.Text(
            feedback_box,
            height=3,
            bg=TOKENS.colors.surface_secondary,
            fg=TOKENS.colors.text_primary,
            insertbackground=TOKENS.colors.text_primary,
            wrap="word",
            borderwidth=1,
            relief="solid",
        )
        style_text_widget(self.feedback_notes, elevated=True)
        self.feedback_notes.grid(row=2, column=1, sticky="ew")
        feedback_btn = ttk.Button(
            feedback_box,
            text="Save Feedback",
            style="Dark.TButton",
            command=self._save_feedback,
        )
        feedback_btn.grid(row=3, column=0, columnspan=2, sticky="ew", pady=(6, 0))
        ttk.Button(
            feedback_box,
            text="Save Feedback (Selected Batch)",
            style="Dark.TButton",
            command=self._save_feedback_batch,
        ).grid(row=4, column=0, columnspan=2, sticky="ew", pady=(6, 0))
        ttk.Button(
            feedback_box,
            text="Undo Last Save",
            style="Dark.TButton",
            command=self._undo_last_feedback_save,
        ).grid(row=5, column=0, columnspan=2, sticky="ew", pady=(6, 0))
        attach_tooltip(
            feedback_btn,
            "Saves rating and prompt-change context into the Learning records store.",
        )
        ttk.Label(feedback_box, text="Subscores", style="Dark.TLabel").grid(
            row=6, column=0, sticky="w", padx=(0, 6), pady=(8, 4)
        )
        subscores = ttk.Frame(feedback_box, style="Panel.TFrame")
        subscores.grid(row=6, column=1, sticky="w", pady=(8, 4))
        subscores.columnconfigure(1, minsize=PRIMARY_CONTROL_MIN_WIDTH // 3)
        subscores.columnconfigure(3, minsize=PRIMARY_CONTROL_MIN_WIDTH // 3)
        subscores.columnconfigure(5, minsize=PRIMARY_CONTROL_MIN_WIDTH // 3)
        ttk.Label(subscores, text="Anatomy", style="Dark.TLabel").grid(row=0, column=0, sticky="w")
        ttk.Spinbox(
            subscores,
            from_=1,
            to=5,
            increment=1,
            textvariable=self.anatomy_rating_var,
            width=4,
            style="Dark.TSpinbox",
        ).grid(row=0, column=1, sticky="w", padx=(6, 12))
        ttk.Label(subscores, text="Composition", style="Dark.TLabel").grid(row=0, column=2, sticky="w")
        ttk.Spinbox(
            subscores,
            from_=1,
            to=5,
            increment=1,
            textvariable=self.composition_rating_var,
            width=4,
            style="Dark.TSpinbox",
        ).grid(row=0, column=3, sticky="w", padx=(6, 12))
        ttk.Label(subscores, text="Prompt Fit", style="Dark.TLabel").grid(row=0, column=4, sticky="w")
        ttk.Spinbox(
            subscores,
            from_=1,
            to=5,
            increment=1,
            textvariable=self.prompt_adherence_rating_var,
            width=4,
            style="Dark.TSpinbox",
        ).grid(row=0, column=5, sticky="w", padx=(6, 0))

    def _selected_stages(self) -> list[str]:
        stages: list[str] = []
        if self.stage_img2img_var.get():
            stages.append("img2img")
        if self.stage_adetailer_var.get():
            stages.append("adetailer")
        if self.stage_upscale_var.get():
            stages.append("upscale")
        return stages

    def _on_select_images(self) -> None:
        files = filedialog.askopenfilenames(
            title="Select images to review/reprocess",
            filetypes=[
                ("Image files", "*.png *.jpg *.jpeg *.webp"),
                ("All files", "*.*"),
            ],
        )
        if not files:
            return
        self._set_selected_images([Path(f) for f in files])

    def _on_select_folder(self) -> None:
        folder = filedialog.askdirectory(title="Select folder with images")
        if not folder:
            return
        root = Path(folder)
        paths = sorted(
            [
                p
                for p in root.rglob("*")
                if p.is_file() and p.suffix.lower() in {".png", ".jpg", ".jpeg", ".webp"}
            ]
        )
        self._set_selected_images(paths)

    def _on_clear(self) -> None:
        self.selected_images = []
        self._image_index_by_row = []
        self.images_list.delete(0, tk.END)
        self.selection_label.config(text="No images selected")
        self.meta_label.config(text="Metadata: n/a")
        self._selected_base_prompt = ""
        self._selected_base_negative_prompt = ""
        self._selected_image_path = None
        self._reset_mode_edits_for_current_image()
        self._apply_content_visibility_mode()
        self._refresh_prompt_diff()
        self.preview.clear()
        self._active_handoff = None
        self._compare_mode = "single"
        self._effective_settings_var.set("Effective settings: select an image")
        self._prior_review_summary_var.set("Prior Review Summary: none")
        self.workflow_hint_label.config(text=self._default_workflow_hint)

    def load_staged_curation_handoff(self, handoff: ReviewWorkspaceHandoff) -> None:
        image_paths = [Path(path) for path in list(handoff.image_paths or [])]
        if not image_paths:
            raise ValueError("No staged-curation images were provided for Review handoff")

        self._active_handoff = handoff
        self._set_selected_images(image_paths)
        self.workflow_hint_label.config(text=get_review_handoff_hint(len(image_paths)))

        self.stage_img2img_var.set(bool(handoff.stage_img2img))
        self.stage_adetailer_var.set(bool(handoff.stage_adetailer))
        self.stage_upscale_var.set(bool(handoff.stage_upscale))

        self._selected_base_prompt = str(handoff.base_prompt or self._selected_base_prompt or "")
        self._selected_base_negative_prompt = str(
            handoff.base_negative_prompt or self._selected_base_negative_prompt or ""
        )
        self._apply_content_visibility_mode()

        prompt_mode = str(handoff.prompt_mode or "append")
        negative_mode = str(handoff.negative_prompt_mode or "append")
        self.prompt_mode_var.set(prompt_mode)
        self.negative_mode_var.set(negative_mode)
        self._prompt_mode_edits = {
            "append": "",
            "replace": "",
            "modify": self._selected_base_prompt,
        }
        self._negative_mode_edits = {
            "append": "",
            "replace": "",
            "modify": self._selected_base_negative_prompt,
        }
        if prompt_mode in self._prompt_mode_edits:
            self._prompt_mode_edits[prompt_mode] = str(handoff.prompt_delta or "")
        if negative_mode in self._negative_mode_edits:
            self._negative_mode_edits[negative_mode] = str(handoff.negative_prompt_delta or "")
        self._prompt_prev_mode = prompt_mode
        self._negative_prev_mode = negative_mode
        self._set_text(self.prompt_text, self._prompt_mode_edits.get(prompt_mode, ""))
        self._set_text(self.negative_text, self._negative_mode_edits.get(negative_mode, ""))
        self._refresh_prompt_diff()

    def _set_selected_images(self, paths: list[Path]) -> None:
        deduped: list[Path] = []
        seen: set[str] = set()
        for path in paths:
            key = str(path.resolve())
            if key in seen:
                continue
            seen.add(key)
            deduped.append(path)

        self.selected_images = deduped
        self._image_index_by_row = list(self.selected_images)
        self.images_list.delete(0, tk.END)
        for p in self.selected_images:
            self.images_list.insert(tk.END, p.name)
        self.selection_label.config(text=f"{len(self.selected_images)} image(s) selected")
        if self.selected_images:
            self.images_list.selection_clear(0, tk.END)
            self.images_list.selection_set(0)
            self._show_image(self.selected_images[0])

    def _on_image_select(self, _event: tk.Event) -> None:
        idxs = self.images_list.curselection()
        if not idxs:
            return
        idx = int(idxs[0])
        if idx < 0 or idx >= len(self._image_index_by_row):
            return
        self._show_image(self._image_index_by_row[idx])

    def _show_image(self, path: Path) -> None:
        self._selected_image_path = path
        self.preview.set_image_from_path(path)
        self._refresh_prior_review_summary(path)
        result = extract_embedded_metadata(path)
        if result.status != "ok" or not isinstance(result.payload, dict):
            self.meta_label.config(text=f"Metadata: {result.status}")
            self._selected_base_prompt = ""
            self._selected_base_negative_prompt = ""
            self._reset_mode_edits_for_current_image()
            self._apply_content_visibility_mode()
            self._refresh_prompt_diff()
            return

        stage_manifest = result.payload.get("stage_manifest", {})
        if not isinstance(stage_manifest, dict):
            stage_manifest = {}
        generation = result.payload.get("generation", {})
        if not isinstance(generation, dict):
            generation = {}
        resolved_prompt, resolved_negative_prompt = resolve_prompt_fields(result.payload)
        model, vae = resolve_model_vae_fields(result.payload)
        preview_prompt = str(resolved_prompt).strip()
        if len(preview_prompt) > 120:
            preview_prompt = f"{preview_prompt[:117]}..."
        self._selected_base_prompt = resolved_prompt
        self._selected_base_negative_prompt = resolved_negative_prompt
        self._reset_mode_edits_for_current_image()
        self._apply_content_visibility_mode()
        self._refresh_prompt_diff()
        resolver = self._visibility_resolver()
        self.meta_label.config(
            text=(
                f"Metadata: ok | model={model or 'n/a'} | vae={vae or 'n/a'}\n"
                f"Prompt: {resolver.redact_text(preview_prompt, item=self._current_visibility_subject()) or '(empty)'}"
            )
        )

    def _refresh_prior_review_summary(self, image_path: Path) -> None:
        learning_controller = self._resolve_learning_controller()
        getter = getattr(learning_controller, "get_prior_review_summary", None) if learning_controller is not None else None
        if not callable(getter):
            self._prior_review_summary_var.set("Prior Review Summary: unavailable")
            return
        try:
            summary = getter(str(image_path))
        except Exception:
            self._prior_review_summary_var.set("Prior Review Summary: unavailable")
            return
        self._prior_review_summary_var.set(self._format_prior_review_summary(summary))

    @staticmethod
    def _format_prior_review_summary(summary: Any) -> str:
        if not isinstance(summary, dict):
            return "Prior Review Summary: none"
        source_type = str(summary.get("source_type") or "unknown")
        source_label_map = {
            "internal_learning_record": "internal learning record",
            "embedded_review_metadata": "embedded artifact metadata",
            "sidecar_review_metadata": "sidecar artifact metadata",
        }
        source_label = source_label_map.get(source_type, source_type.replace("_", " "))
        rating = summary.get("user_rating")
        quality = str(summary.get("quality_label") or "")
        timestamp = str(summary.get("review_timestamp") or "")
        notes = str(summary.get("user_notes") or "").strip()
        prompt_mode = str(summary.get("prompt_mode") or "").strip()
        prompt_changed = bool(
            str(summary.get("prompt_delta") or "").strip()
            or str(summary.get("negative_prompt_delta") or "").strip()
            or str(summary.get("prompt_before") or "").strip() != str(summary.get("prompt_after") or "").strip()
            or str(summary.get("negative_prompt_before") or "").strip() != str(summary.get("negative_prompt_after") or "").strip()
        )
        bits = [f"Source: {source_label}"]
        if rating is not None:
            rating_text = f"Rating: {rating}"
            if quality:
                rating_text += f" ({quality})"
            bits.append(rating_text)
        elif quality:
            bits.append(f"Quality: {quality}")
        if timestamp:
            bits.append(f"Reviewed: {timestamp}")
        if notes:
            trimmed = notes if len(notes) <= 120 else f"{notes[:117]}..."
            bits.append(f"Notes: {trimmed}")
        bits.append(f"Prompt change: {prompt_mode or ('yes' if prompt_changed else 'no')}")
        return "\n".join(bits)

    def _show_previous_image(self) -> None:
        self._step_selected_image(-1)

    def _show_next_image(self) -> None:
        self._step_selected_image(1)

    def _step_selected_image(self, delta: int) -> None:
        if not self._image_index_by_row:
            return
        current = self.images_list.curselection()
        current_index = int(current[0]) if current else 0
        next_index = max(0, min(len(self._image_index_by_row) - 1, current_index + int(delta)))
        self.images_list.selection_clear(0, tk.END)
        self.images_list.selection_set(next_index)
        self.images_list.activate(next_index)
        self.images_list.see(next_index)
        self._show_image(self._image_index_by_row[next_index])

    def _open_compare_viewer(self) -> None:
        image_path = self._selected_image_path
        if image_path is None:
            return
        if not PIL_AVAILABLE:
            messagebox.showinfo("Viewer unavailable", "Large compare viewer requires Pillow.")
            return
        self._compare_mode = "single"
        self._render_compare_viewer(image_path)

    def _open_metadata_inspector(self) -> None:
        image_path = self._selected_image_path
        if image_path is None:
            messagebox.showinfo("Metadata Inspector", "Select an image first.")
            return
        learning_controller = self._resolve_learning_controller()
        inspector = getattr(learning_controller, "inspect_artifact_metadata", None) if learning_controller is not None else None
        if not callable(inspector):
            messagebox.showerror("Metadata Inspector", "Metadata inspector is unavailable.")
            return

        def _refresh() -> dict[str, Any] | None:
            refreshed = inspector(str(image_path))
            return dict(refreshed) if isinstance(refreshed, dict) else None

        try:
            payload = inspector(str(image_path))
        except Exception as exc:
            messagebox.showerror("Metadata Inspector", str(exc))
            return
        if not isinstance(payload, dict):
            messagebox.showerror("Metadata Inspector", "Inspector returned an invalid payload.")
            return
        ArtifactMetadataInspectorDialog(self, inspection_payload=payload, on_refresh=_refresh)

    def _lookup_handoff_source_metadata(self, image_path: Path) -> dict[str, Any] | None:
        handoff = self._active_handoff
        if handoff is None:
            return None
        source_map = dict(getattr(handoff, "source_metadata_by_path", {}) or {})
        return source_map.get(str(image_path)) or source_map.get(str(image_path.resolve()))

    def _get_selected_latest_derived_descendant(self) -> dict[str, Any] | None:
        image_path = self._selected_image_path
        if image_path is None:
            return None
        source_metadata = self._lookup_handoff_source_metadata(image_path)
        selection_meta = source_metadata.get("curation_source_selection") if isinstance(source_metadata, dict) else None
        if not isinstance(selection_meta, dict):
            return None
        candidate_id = str(selection_meta.get("candidate_id") or "").strip()
        if not candidate_id:
            return None
        learning_controller = self._resolve_learning_controller()
        if learning_controller is None:
            return None
        getter = getattr(learning_controller, "get_staged_curation_candidate_latest_descendant", None)
        if not callable(getter):
            return None
        latest = getter(candidate_id)
        return latest if isinstance(latest, dict) else None

    def _open_latest_derived_compare(self, *, show_errors: bool = True) -> bool:
        image_path = self._selected_image_path
        if image_path is None:
            if show_errors:
                messagebox.showinfo("Compare unavailable", "Select a staged-curation source image first.")
            return False
        if not PIL_AVAILABLE:
            if show_errors:
                messagebox.showinfo("Viewer unavailable", "Large compare viewer requires Pillow.")
            return False
        latest = self._get_selected_latest_derived_descendant()
        latest_path_value = str((latest or {}).get("artifact_path") or "").strip()
        if not latest_path_value:
            if show_errors:
                messagebox.showinfo(
                    "No latest derived",
                    "No derived descendant has been found yet for the selected staged-curation source.",
                )
            return False
        self._compare_mode = "latest_derived"
        target_stage = str((latest or {}).get("target_stage") or "derived").replace("_", " ")
        self._render_compare_viewer(
            image_path,
            secondary_path=Path(latest_path_value),
            title_prefix=f"Source vs Latest Derived ({target_stage})",
        )
        return True

    def open_staged_candidate_latest_derived_compare(
        self,
        *,
        image_path: Path,
        candidate_id: str,
        workflow_title: str = "",
    ) -> bool:
        self.load_staged_curation_handoff(
            ReviewWorkspaceHandoff(
                source="staged_curation",
                workflow_title=workflow_title,
                target_stage="",
                image_paths=[image_path],
                base_prompt="",
                base_negative_prompt="",
                prompt_delta="",
                negative_prompt_delta="",
                prompt_mode="append",
                negative_prompt_mode="append",
                stage_img2img=False,
                stage_adetailer=False,
                stage_upscale=False,
                source_candidate_ids=[candidate_id],
                source_metadata_by_path={
                    str(image_path): {
                        "curation_source_selection": {
                            "candidate_id": candidate_id,
                        }
                    }
                },
            )
        )
        return self._open_latest_derived_compare()

    def _render_compare_viewer(
        self,
        image_path: Path,
        *,
        secondary_path: Path | None = None,
        title_prefix: str = "Large Compare",
    ) -> None:
        try:
            with Image.open(image_path) as image:
                left_image = image.convert("RGBA")
            if secondary_path is not None:
                with Image.open(secondary_path) as image:
                    right_image = image.convert("RGBA")
                gutter = 24
                image_width = left_image.size[0] + right_image.size[0] + gutter
                image_height = max(left_image.size[1], right_image.size[1])
                composite = Image.new("RGBA", (image_width, image_height), (20, 20, 20, 255))
                composite.paste(left_image, (0, 0))
                composite.paste(right_image, (left_image.size[0] + gutter, 0))
                photo = ImageTk.PhotoImage(composite)
            else:
                image_width, image_height = left_image.size
                photo = ImageTk.PhotoImage(left_image)
        except Exception as exc:
            messagebox.showerror("Viewer failed", f"Failed to open image: {exc}")
            return

        if self._compare_window and self._compare_window.winfo_exists():
            viewer = self._compare_window
            for child in viewer.winfo_children():
                child.destroy()
        else:
            viewer = tk.Toplevel(self)
            self._compare_window = viewer
            apply_toplevel_theme(viewer)
            viewer.bind("<Left>", lambda _event: self._show_previous_image_and_refresh_viewer())
            viewer.bind("<Right>", lambda _event: self._show_next_image_and_refresh_viewer())
            viewer.bind("<Escape>", lambda _event: viewer.destroy())

        viewer.title(f"{title_prefix} - {image_path.name}")
        viewer.transient(self.winfo_toplevel())
        viewer.resizable(True, True)
        viewer.minsize(720, 520)

        frame = ttk.Frame(viewer, padding=6)
        frame.pack(fill=tk.BOTH, expand=True)
        frame.columnconfigure(0, weight=1)
        frame.rowconfigure(1, weight=1)

        nav = ttk.Frame(frame, style="Panel.TFrame")
        nav.grid(row=0, column=0, sticky="ew", pady=(0, 6))
        ttk.Button(nav, text="Prev", style="Dark.TButton", command=self._show_previous_image_and_refresh_viewer).pack(side="left")
        ttk.Button(nav, text="Next", style="Dark.TButton", command=self._show_next_image_and_refresh_viewer).pack(side="left", padx=(6, 0))
        ttk.Label(
            nav,
            text="Left/Right arrows cycle through the loaded review images",
            style="Dark.TLabel",
        ).pack(side="left", padx=(12, 0))

        compare_label = f"Source: {image_path.name}"
        if secondary_path is not None:
            compare_label += f"    Latest derived: {secondary_path.name}"
        ttk.Label(
            frame,
            text=compare_label,
            style="Dark.TLabel",
            justify="left",
        ).grid(row=1, column=0, sticky="w", pady=(0, 6))

        canvas = tk.Canvas(frame, bg=TOKENS.colors.surface_secondary, highlightthickness=0)
        style_canvas_widget(canvas, elevated=True)
        canvas.grid(row=2, column=0, sticky="nsew")
        v_scroll = ttk.Scrollbar(frame, orient=tk.VERTICAL, command=canvas.yview)
        h_scroll = ttk.Scrollbar(frame, orient=tk.HORIZONTAL, command=canvas.xview)
        canvas.configure(yscrollcommand=v_scroll.set, xscrollcommand=h_scroll.set)
        v_scroll.grid(row=2, column=1, sticky="ns")
        h_scroll.grid(row=3, column=0, sticky="ew")

        self._compare_canvas = canvas
        self._compare_photo = photo
        canvas.create_image(0, 0, image=photo, anchor="nw")
        canvas.configure(scrollregion=(0, 0, image_width, image_height))

        width = min(max(image_width + 60, 960), int(viewer.winfo_screenwidth() * 0.92))
        height = min(max(image_height + 120, 720), int(viewer.winfo_screenheight() * 0.92))
        viewer.geometry(f"{width}x{height}")
        viewer.lift()
        viewer.focus_force()

    def _show_previous_image_and_refresh_viewer(self) -> None:
        self._step_selected_image(-1)
        if self._selected_image_path is not None:
            if self._compare_mode == "latest_derived":
                self._open_latest_derived_compare(show_errors=False)
            else:
                self._render_compare_viewer(self._selected_image_path)

    def _show_next_image_and_refresh_viewer(self) -> None:
        self._step_selected_image(1)
        if self._selected_image_path is not None:
            if self._compare_mode == "latest_derived":
                self._open_latest_derived_compare(show_errors=False)
            else:
                self._render_compare_viewer(self._selected_image_path)

    def _on_import_selected_to_staged_curation(self) -> None:
        learning_controller = self._resolve_learning_controller()
        if learning_controller is None:
            messagebox.showerror("Learning unavailable", "Learning controller is not connected.")
            return
        selected = self._get_selected_review_paths()
        if not selected:
            messagebox.showwarning("No selection", "Select one or more images to import.")
            return
        importer = getattr(learning_controller, "import_review_images_to_staged_curation", None)
        if not callable(importer):
            messagebox.showerror("Unsupported", "Connected learning controller does not support staged-curation import.")
            return
        group_id = importer([str(path) for path in selected], display_name=self._build_import_display_name(selected))
        if not group_id:
            messagebox.showerror("Import failed", "Unable to build a staged-curation group from the selected images.")
            return
        messagebox.showinfo("Imported", f"Imported {len(selected)} image(s) into Staged Curation.\nGroup: {group_id}")

    def _on_open_history_import_picker(self) -> None:
        history_items = list(getattr(self.app_state, "history_items", []) or [])
        if not history_items:
            messagebox.showinfo("No history", "No recent job history is available to import.")
            return
        if self._history_import_window and self._history_import_window.winfo_exists():
            self._history_import_window.destroy()
        window = tk.Toplevel(self)
        self._history_import_window = window
        window.title("Import Recent Job To Staged Curation")
        window.transient(self.winfo_toplevel())
        apply_toplevel_theme(window)
        window.geometry("900x420")
        window.minsize(720, 320)

        frame = ttk.Frame(window, padding=8)
        frame.pack(fill="both", expand=True)
        frame.columnconfigure(0, weight=1)
        frame.rowconfigure(0, weight=1)

        tree = ttk.Treeview(
            frame,
            columns=("status", "pack", "job_id"),
            show="headings",
            selectmode="browse",
        )
        for column_id, heading, width in (
            ("status", "Status", 120),
            ("pack", "Pack / Summary", 360),
            ("job_id", "Job ID", 220),
        ):
            tree.heading(column_id, text=heading)
            tree.column(column_id, width=width, anchor="w")
        tree.grid(row=0, column=0, sticky="nsew")
        scrollbar = ttk.Scrollbar(frame, orient="vertical", command=tree.yview)
        scrollbar.grid(row=0, column=1, sticky="ns")
        tree.configure(yscrollcommand=scrollbar.set)

        for entry in history_items[:50]:
            item_id = str(getattr(entry, "job_id", "") or "")
            tree.insert(
                "",
                "end",
                iid=item_id,
                values=(
                    str(getattr(getattr(entry, "status", None), "value", "") or ""),
                    self._history_entry_summary(entry),
                    item_id,
                ),
            )

        action_bar = ttk.Frame(frame, style="Panel.TFrame")
        action_bar.grid(row=1, column=0, columnspan=2, sticky="ew", pady=(8, 0))
        ttk.Button(
            action_bar,
            text="Import Selected Job",
            style="Dark.TButton",
            command=lambda: self._import_selected_history_job(tree),
        ).pack(side="left")
        ttk.Button(
            action_bar,
            text="Close",
            style="Dark.TButton",
            command=window.destroy,
        ).pack(side="right")

    def _import_selected_history_job(self, tree: ttk.Treeview) -> None:
        selection = tree.selection()
        if not selection:
            messagebox.showwarning("No selection", "Select a history job to import.")
            return
        job_id = selection[0]
        entry = self._find_history_entry(job_id)
        if entry is None:
            messagebox.showerror("Import failed", "Unable to resolve the selected history job.")
            return
        learning_controller = self._resolve_learning_controller()
        if learning_controller is None:
            messagebox.showerror("Learning unavailable", "Learning controller is not connected.")
            return
        importer = getattr(learning_controller, "import_history_entry_to_staged_curation", None)
        if not callable(importer):
            messagebox.showerror("Unsupported", "Connected learning controller does not support history import.")
            return
        group_id = importer(entry)
        if not group_id:
            messagebox.showerror("Import failed", "No image outputs were found for the selected history job.")
            return
        if self._history_import_window and self._history_import_window.winfo_exists():
            self._history_import_window.destroy()
        messagebox.showinfo("Imported", f"Imported history job into Staged Curation.\nGroup: {group_id}")

    def _find_history_entry(self, job_id: str) -> JobHistoryEntry | None:
        history_items = list(getattr(self.app_state, "history_items", []) or [])
        for entry in history_items:
            if str(getattr(entry, "job_id", "") or "") == str(job_id or ""):
                return entry
        return None

    def _history_entry_summary(self, entry: JobHistoryEntry) -> str:
        prompt_pack_id = str(getattr(entry, "prompt_pack_id", "") or "").strip()
        if prompt_pack_id:
            return prompt_pack_id
        payload_summary = str(getattr(entry, "payload_summary", "") or "").strip()
        return payload_summary[:80] if payload_summary else "History job"

    def _get_selected_review_paths(self) -> list[Path]:
        idxs = list(self.images_list.curselection())
        if not idxs and self._selected_image_path is not None:
            return [self._selected_image_path]
        paths: list[Path] = []
        for idx in idxs:
            if 0 <= int(idx) < len(self._image_index_by_row):
                paths.append(self._image_index_by_row[int(idx)])
        return paths

    def _build_import_display_name(self, paths: list[Path]) -> str:
        if len(paths) == 1:
            return f"Review Import - {paths[0].stem}"
        return f"Review Import - {len(paths)} images"

    def _visibility_resolver(self) -> ContentVisibilityResolver:
        return ContentVisibilityResolver(self._content_visibility_mode)

    def _current_visibility_subject(self) -> dict[str, str]:
        return {
            "positive_prompt": self._selected_base_prompt,
            "negative_prompt": self._selected_base_negative_prompt,
            "name": self._selected_image_path.name if self._selected_image_path is not None else "",
        }

    def _apply_content_visibility_mode(self) -> None:
        resolver = self._visibility_resolver()
        prompt_value = resolver.redact_text(self._selected_base_prompt, item=self._current_visibility_subject())
        negative_value = resolver.redact_text(
            self._selected_base_negative_prompt,
            item=self._current_visibility_subject(),
        )
        self._set_readonly_text(self.current_prompt_text, prompt_value)
        self._set_readonly_text(self.current_negative_text, negative_value)
        self.visibility_banner.config(text="")

    def on_content_visibility_mode_changed(self, mode: str | None = None) -> None:
        self._content_visibility_mode = str(
            mode or getattr(getattr(self, "app_state", None), "content_visibility_mode", "nsfw") or "nsfw"
        )
        self._apply_content_visibility_mode()
        self._refresh_prompt_diff()

    def _on_content_visibility_mode_changed(self) -> None:
        self.on_content_visibility_mode_changed()

    def _set_readonly_text(self, widget: tk.Text, value: str) -> None:
        widget.configure(state="normal")
        widget.delete("1.0", tk.END)
        widget.insert("1.0", (value or "").strip())
        widget.configure(state="disabled")

    def _clip_text(self, text: str, max_len: int = 220) -> str:
        return self._workflow_adapter.clip_text(text, max_len=max_len)

    def _refresh_prompt_diff(self) -> None:
        prompt_delta = self.prompt_text.get("1.0", tk.END).strip()
        negative_delta = self.negative_text.get("1.0", tk.END).strip()
        diff = self._workflow_adapter.build_prompt_diff(
            base_prompt=self._selected_base_prompt,
            base_negative_prompt=self._selected_base_negative_prompt,
            prompt_delta=prompt_delta,
            negative_prompt_delta=negative_delta,
            prompt_mode=self.prompt_mode_var.get(),
            negative_prompt_mode=self.negative_mode_var.get(),
        )
        resolver = self._visibility_resolver()
        self.diff_before_label.config(
            text=resolver.redact_text(diff.before_text, item=self._current_visibility_subject())
        )
        self.diff_after_label.config(
            text=resolver.redact_text(diff.after_text, item=self._current_visibility_subject())
        )
        self._refresh_effective_settings()

    def _refresh_effective_settings(self) -> None:
        image_path = self._selected_image_path
        if image_path is None:
            self._effective_settings_var.set("Effective settings: select an image")
            return

        controller = self.app_controller
        builder = getattr(controller, "get_review_reprocess_effective_settings_preview", None)
        if not callable(builder):
            self._effective_settings_var.set("Effective settings: controller preview unavailable")
            return

        try:
            preview = builder(
                image_path=str(image_path),
                stages=self._selected_stages(),
                prompt_delta=self.prompt_text.get("1.0", tk.END).strip(),
                negative_prompt_delta=self.negative_text.get("1.0", tk.END).strip(),
                prompt_mode=self.prompt_mode_var.get(),
                negative_prompt_mode=self.negative_mode_var.get(),
            )
        except Exception as exc:
            self._effective_settings_var.set(f"Effective settings: unavailable ({exc})")
            return

        direct_queue_preview = None
        if self._active_handoff is not None:
            direct_queue_preview = self._active_handoff.direct_queue_preview
        self._effective_settings_var.set(
            self._workflow_adapter.format_effective_settings_summary(
                preview,
                direct_queue_preview=direct_queue_preview,
            )
        )

    def _show_batch_logic_help(self) -> None:
        messagebox.showinfo(
            "Batch Logic",
            "How batching works:\n\n"
            "- Single image run: always 1 job.\n"
            "- Batch run: images are grouped by compatible effective settings.\n"
            "- Compatible means same final + prompt, - prompt, model, and merged config.\n"
            "- If one image needs different model/config/prompt, it is put in a different job.\n"
            "- Batch size limits max images per compatible job.",
        )

    @staticmethod
    def _apply_prompt_delta(base: str, delta: str, mode: str) -> str:
        return ReviewWorkflowAdapter.apply_prompt_delta(base, delta, mode)

    def _get_text(self, widget: tk.Text) -> str:
        return widget.get("1.0", tk.END).strip()

    def _set_text(self, widget: tk.Text, value: str) -> None:
        widget.delete("1.0", tk.END)
        widget.insert("1.0", value or "")

    def _reset_mode_edits_for_current_image(self) -> None:
        self._prompt_mode_edits = {"append": "", "replace": "", "modify": self._selected_base_prompt}
        self._negative_mode_edits = {
            "append": "",
            "replace": "",
            "modify": self._selected_base_negative_prompt,
        }
        self._prompt_prev_mode = self.prompt_mode_var.get() or "append"
        self._negative_prev_mode = self.negative_mode_var.get() or "append"
        self._sync_edit_box_to_mode("prompt")
        self._sync_edit_box_to_mode("negative")

    def _sync_edit_box_to_mode(self, which: str) -> None:
        if which == "prompt":
            mode = self.prompt_mode_var.get() or "append"
            text = self._prompt_mode_edits.get(mode, "")
            if mode == "modify" and not text:
                text = self._selected_base_prompt
                self._prompt_mode_edits["modify"] = text
            self._set_text(self.prompt_text, text)
        else:
            mode = self.negative_mode_var.get() or "append"
            text = self._negative_mode_edits.get(mode, "")
            if mode == "modify" and not text:
                text = self._selected_base_negative_prompt
                self._negative_mode_edits["modify"] = text
            self._set_text(self.negative_text, text)
        self._refresh_prompt_diff()

    def _on_prompt_mode_changed(self) -> None:
        self._prompt_mode_edits[self._prompt_prev_mode] = self._get_text(self.prompt_text)
        self._prompt_prev_mode = self.prompt_mode_var.get() or "append"
        self._sync_edit_box_to_mode("prompt")

    def _on_negative_mode_changed(self) -> None:
        self._negative_mode_edits[self._negative_prev_mode] = self._get_text(self.negative_text)
        self._negative_prev_mode = self.negative_mode_var.get() or "append"
        self._sync_edit_box_to_mode("negative")

    def _reprocess(self, *, batch_all: bool) -> None:
        stages = self._selected_stages()
        if not stages:
            messagebox.showwarning("No stages", "Select at least one stage.")
            return

        if batch_all:
            targets = list(self.selected_images)
        else:
            idxs = self.images_list.curselection()
            if not idxs:
                messagebox.showwarning("No selection", "Select an image from the list.")
                return
            targets = [self._image_index_by_row[int(idxs[0])]]

        if not targets:
            messagebox.showwarning("No images", "Select at least one image.")
            return

        controller = self.app_controller
        if controller is None:
            messagebox.showerror("Controller missing", "App controller is not connected.")
            return

        prompt_delta = self.prompt_text.get("1.0", tk.END).strip()
        negative_delta = self.negative_text.get("1.0", tk.END).strip()
        batch_size = max(1, int(self.batch_size_var.get() or 1))

        try:
            handler = getattr(controller, "on_reprocess_images_with_prompt_delta", None)
            if callable(handler):
                source_metadata_by_image = None
                if self._active_handoff is not None:
                    source_map = dict(getattr(self._active_handoff, "source_metadata_by_path", {}) or {})
                    if source_map:
                        source_metadata_by_image = {}
                        for target in targets:
                            source_metadata = source_map.get(str(target)) or source_map.get(str(target.resolve()))
                            if isinstance(source_metadata, dict):
                                source_metadata_by_image[str(target)] = source_metadata
                submitted = handler(
                    image_paths=[str(p) for p in targets],
                    stages=stages,
                    prompt_delta=prompt_delta,
                    negative_prompt_delta=negative_delta,
                    prompt_mode=self.prompt_mode_var.get(),
                    negative_prompt_mode=self.negative_mode_var.get(),
                    batch_size=batch_size,
                    source_metadata_by_image=source_metadata_by_image,
                )
            else:
                fallback = getattr(controller, "on_reprocess_images", None)
                if not callable(fallback):
                    raise RuntimeError("No reprocess handler is available on controller")
                submitted = fallback(
                    image_paths=[str(p) for p in targets],
                    stages=stages,
                    batch_size=batch_size,
                )
            messagebox.showinfo("Submitted", f"Submitted {submitted} reprocess job(s).")
        except Exception as exc:
            messagebox.showerror("Reprocess failed", str(exc))

    def _resolve_learning_controller(self) -> Any | None:
        app_ctrl = self.app_controller
        if app_ctrl is None:
            return None
        main_window = getattr(app_ctrl, "main_window", None)
        if main_window is None:
            return None
        learning_tab = getattr(main_window, "learning_tab", None)
        if learning_tab is None:
            return None
        return getattr(learning_tab, "learning_controller", None) or getattr(
            learning_tab, "controller", None
        )

    def _save_feedback(self) -> None:
        if self._selected_image_path is None:
            messagebox.showwarning("No image", "Select an image first.")
            return
        learning_controller = self._resolve_learning_controller()
        if learning_controller is None:
            messagebox.showerror(
                "Learning unavailable",
                "Learning controller is not connected.",
            )
            return
        save = getattr(learning_controller, "save_review_feedback", None)
        if not callable(save):
            messagebox.showerror(
                "Unsupported",
                "Connected learning controller does not support review feedback.",
            )
            return
        payload = self._build_feedback_payload(self._selected_image_path)
        if payload is None:
            messagebox.showerror("Save failed", "Unable to build feedback payload for selected image.")
            return
        try:
            record = save(payload)
            run_id = str(getattr(record, "run_id", "") or "")
            self._feedback_undo_stack.append(
                [{"run_id": run_id, "image_path": str(self._selected_image_path)}]
            )
            self._refresh_prior_review_summary(self._selected_image_path)
            messagebox.showinfo("Saved", "Review feedback saved to Learning records.")
        except Exception as exc:
            messagebox.showerror("Save failed", str(exc))

    def _save_feedback_batch(self) -> None:
        learning_controller = self._resolve_learning_controller()
        if learning_controller is None:
            messagebox.showerror("Learning unavailable", "Learning controller is not connected.")
            return
        save = getattr(learning_controller, "save_review_feedback", None)
        if not callable(save):
            messagebox.showerror(
                "Unsupported",
                "Connected learning controller does not support review feedback.",
            )
            return
        idxs = list(self.images_list.curselection())
        if not idxs:
            messagebox.showwarning("No selection", "Select one or more images in the list.")
            return
        targets: list[Path] = []
        for idx in idxs:
            if 0 <= int(idx) < len(self._image_index_by_row):
                targets.append(self._image_index_by_row[int(idx)])
        if not targets:
            messagebox.showwarning("No images", "No valid selected images.")
            return

        tokens: list[dict[str, str]] = []
        failed: list[str] = []
        for target in targets:
            payload = self._build_feedback_payload(target)
            if payload is None:
                failed.append(target.name)
                continue
            try:
                record = save(payload)
                tokens.append(
                    {
                        "run_id": str(getattr(record, "run_id", "") or ""),
                        "image_path": str(target),
                    }
                )
            except Exception:
                failed.append(target.name)
        if tokens:
            self._feedback_undo_stack.append(tokens)
        if failed:
            messagebox.showwarning(
                "Partial Save",
                f"Saved {len(tokens)} feedback record(s); failed {len(failed)}.",
            )
            return
        messagebox.showinfo("Saved", f"Saved feedback for {len(tokens)} image(s).")

    def _undo_last_feedback_save(self) -> None:
        learning_controller = self._resolve_learning_controller()
        if learning_controller is None:
            messagebox.showerror("Learning unavailable", "Learning controller is not connected.")
            return
        undo = getattr(learning_controller, "undo_review_feedback", None)
        if not callable(undo):
            messagebox.showerror("Unsupported", "Connected learning controller does not support undo.")
            return
        if not self._feedback_undo_stack:
            messagebox.showinfo("Nothing to undo", "No saved feedback actions to undo.")
            return
        action = self._feedback_undo_stack.pop()
        undone = 0
        for token in reversed(action):
            if undo(run_id=token.get("run_id"), image_path=token.get("image_path")):
                undone += 1
        if undone <= 0:
            messagebox.showwarning("Undo", "No matching feedback records were removed.")
            return
        messagebox.showinfo("Undo complete", f"Removed {undone} feedback record(s).")

    def _build_feedback_payload(self, image_path: Path) -> dict[str, Any] | None:
        metadata = extract_embedded_metadata(image_path)
        if metadata.status != "ok" or not isinstance(metadata.payload, dict):
            return None
        return self._workflow_adapter.build_feedback_payload(
            image_path=image_path,
            metadata_payload=metadata.payload,
            rating=int(self.rating_var.get()),
            quality_label=self.quality_var.get(),
            notes=self.feedback_notes.get("1.0", tk.END).strip(),
            prompt_delta=self.prompt_text.get("1.0", tk.END).strip(),
            negative_prompt_delta=self.negative_text.get("1.0", tk.END).strip(),
            prompt_mode=self.prompt_mode_var.get(),
            negative_prompt_mode=self.negative_mode_var.get(),
            stages=self._selected_stages(),
            anatomy_rating=int(self.anatomy_rating_var.get()),
            composition_rating=int(self.composition_rating_var.get()),
            prompt_adherence_rating=int(self.prompt_adherence_rating_var.get()),
        )
