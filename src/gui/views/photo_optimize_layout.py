"""Photo Optimize presentation builders, extracted from the tab without new execution authority."""
from __future__ import annotations

import tkinter as tk
from tkinter import ttk

from src.gui.tooltip import attach_tooltip
from src.gui.ui_tokens import TOKENS
from src.gui.widgets.scrollable_frame_v2 import ScrollableFrame
from src.gui.widgets.thumbnail_widget_v2 import ThumbnailWidget

from .photo_optimize_editors import PhotoBatchEditor


class PhotoOptimizeLayoutMixin:
    def _build_header(self) -> None:
        header = ttk.Frame(self, style="Panel.TFrame", padding=8)
        header.grid(row=0, column=0, sticky="ew", padx=6, pady=(6, 4))
        header.columnconfigure(8, weight=1)

        ttk.Button(
            header,
            text="Import Photos",
            style="Dark.TButton",
            command=self._on_import_photos,
        ).grid(row=0, column=0, sticky="w", padx=(0, 6))
        ttk.Button(
            header,
            text="Refresh",
            style="Dark.TButton",
            command=self._refresh_assets,
        ).grid(row=0, column=1, sticky="w", padx=(0, 6))
        ttk.Button(
            header,
            text="Review Pipeline Copy (editing scope)…",
            style="Dark.TButton",
            command=self._use_current_pipeline_settings,
        ).grid(row=0, column=2, sticky="w", padx=(0, 6))
        interrogate_btn = ttk.Button(
            header,
            text="Interrogate",
            style="Dark.TButton",
            command=self._interrogate_current_asset,
        )
        interrogate_btn.grid(row=0, column=3, sticky="w")
        attach_tooltip(
            interrogate_btn,
            "Analyze the current working image and write the returned caption into the baseline prompt.",
        )
        self.visibility_banner = ttk.Label(header, text="", style="Dark.TLabel")
        ttk.Label(header, text="Max photos / compatible job", style="Dark.TLabel").grid(
            row=0, column=4, sticky="w", padx=(10, 4)
        )
        ttk.Spinbox(
            header,
            from_=1,
            to=64,
            increment=1,
            textvariable=self.batch_size_var,
            width=5,
            style="Dark.TSpinbox",
        ).grid(row=0, column=5, sticky="w", padx=(0, 8))
        self.optimize_selected_header_btn = ttk.Button(
            header,
            text="Review Selected…",
            style="Primary.TButton",
            command=lambda: self._optimize(batch_all=False),
        )
        self.optimize_selected_header_btn.grid(row=0, column=6, sticky="w", padx=(0, 6))
        self.optimize_all_header_btn = ttk.Button(
            header,
            text="Review All Visible (unarchived)…",
            style="Dark.TButton",
            command=lambda: self._optimize(batch_all=True),
        )
        self.optimize_all_header_btn.grid(row=0, column=7, sticky="w")

        self.selection_label = ttk.Label(
            header,
            text="No assets loaded",
            style="Dark.TLabel",
        )
        self.selection_label.grid(row=0, column=8, sticky="e")
        ttk.Label(header, textvariable=self.submission_summary_var, style="Dark.TLabel",
                  wraplength=1000).grid(row=1, column=0, columnspan=9, sticky="ew", pady=(6, 0))
        ttk.Label(header, textvariable=self.migration_status_var, style="Dark.TLabel",
                  wraplength=750).grid(row=2, column=0, columnspan=7, sticky="ew", pady=(4, 0))
        ttk.Button(header, text="Migration Details", style="Dark.TButton",
                   command=self._show_migration_details).grid(row=2, column=7, padx=(4, 0))
        ttk.Button(header, text="Retry Legacy Migration", style="Dark.TButton",
                   command=self._retry_legacy_migration).grid(row=2, column=8, padx=(4, 0))


    def _build_body(self) -> None:
        self.body_scroll = ScrollableFrame(self, style="Panel.TFrame")
        self.body_scroll.grid(row=1, column=0, sticky="nsew", padx=6, pady=(0, 6))
        body = self.body_scroll.inner
        body.columnconfigure(0, weight=1, uniform="photo_optimize")
        body.columnconfigure(1, weight=2, uniform="photo_optimize")
        body.columnconfigure(2, weight=2, uniform="photo_optimize")
        body.rowconfigure(0, weight=1)

        assets_frame = ttk.LabelFrame(body, text="Assets — batch selection", style="Dark.TLabelframe", padding=8)
        assets_frame.grid(row=0, column=0, sticky="nsew", padx=(0, 6))
        assets_frame.columnconfigure(0, weight=1)
        assets_frame.rowconfigure(0, weight=1)

        self.assets_list = tk.Listbox(
            assets_frame,
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
        self.assets_list.grid(row=0, column=0, sticky="nsew")
        self.assets_list.bind("<<ListboxSelect>>", self._on_asset_select)
        assets_scroll = ttk.Scrollbar(
            assets_frame, orient="vertical", command=self.assets_list.yview
        )
        assets_scroll.grid(row=0, column=1, sticky="ns")
        self.assets_list.configure(yscrollcommand=assets_scroll.set)
        list_controls = ttk.Frame(assets_frame, style="Panel.TFrame")
        list_controls.grid(row=1, column=0, columnspan=2, sticky="ew", pady=(6, 0))
        ttk.Label(list_controls, text="Active Single Photo", style="Dark.TLabel").pack(anchor="w")
        self.active_photo_combo = ttk.Combobox(list_controls, state="readonly", style="Dark.TCombobox")
        self.active_photo_combo.pack(fill="x")
        self.active_photo_combo.bind("<<ComboboxSelected>>", self._on_active_photo_choice)
        ttk.Label(list_controls, text="Changes editor only; batch highlights stay.",
                  style="Dark.TLabel", wraplength=240).pack(anchor="w", pady=(0, 6))
        for text, action in (
            ("Remove Selected", lambda: self._archive_assets(clear_all=False)),
            ("Clear List", lambda: self._archive_assets(clear_all=True)),
            ("Restore Selected", self._restore_assets),
        ):
            ttk.Button(list_controls, text=text, command=action, style="Dark.TButton").pack(anchor="w")
        ttk.Checkbutton(list_controls, text="Show Archived", variable=self.show_archived_var,
                        command=self._refresh_assets, style="Dark.TCheckbutton").pack(anchor="w")

        preview_frame = ttk.LabelFrame(
            body,
            text="Preview & Asset Metadata",
            style="Dark.TLabelframe",
            padding=8,
        )
        self.preview_frame = preview_frame
        preview_frame.grid(row=0, column=1, sticky="nsew", padx=(0, 6))
        preview_frame.columnconfigure(0, weight=1)
        preview_frame.columnconfigure(1, weight=1)
        preview_frame.rowconfigure(0, weight=1)

        self.image_previews_frame = ttk.Frame(preview_frame, style="Panel.TFrame")
        self.image_previews_frame.grid(row=0, column=0, columnspan=2, sticky="nsew")
        self.image_previews_frame.columnconfigure(0, weight=1)
        self.image_previews_frame.columnconfigure(1, weight=1)
        self.image_previews_frame.rowconfigure(1, weight=1)

        ttk.Label(self.image_previews_frame, text="Original", style="Dark.TLabel").grid(
            row=0, column=0, sticky="w", pady=(0, 4)
        )
        ttk.Label(self.image_previews_frame, text="History Output", style="Dark.TLabel").grid(
            row=0, column=1, sticky="w", pady=(0, 4)
        )
        self.original_preview = ThumbnailWidget(
            self.image_previews_frame,
            width=220,
            height=220,
            placeholder_text="Import a photo",
        )
        self.original_preview.grid(row=1, column=0, sticky="nsew", padx=(0, 6))
        self.latest_preview = ThumbnailWidget(
            self.image_previews_frame,
            width=220,
            height=220,
            placeholder_text="No optimize output yet",
        )
        self.latest_preview.grid(row=1, column=1, sticky="nsew")

        self.meta_label = ttk.Label(
            preview_frame,
            text="Metadata: n/a",
            style="Dark.TLabel",
            justify="left",
            wraplength=460,
        )
        self.meta_label.grid(row=1, column=0, columnspan=2, sticky="ew", pady=(8, 0))

        controls = ttk.Frame(body, style="Panel.TFrame")
        controls.grid(row=0, column=2, sticky="nsew")
        controls.columnconfigure(0, weight=1)
        controls.rowconfigure(0, weight=1)
        controls.rowconfigure(1, weight=1)
        controls.rowconfigure(2, weight=1)

        self.edit_workspaces = ttk.Notebook(controls)
        self.edit_workspaces.grid(row=0, column=0, sticky="nsew")
        self.single_workspace = ttk.Frame(self.edit_workspaces)
        self.batch_workspace = ttk.Frame(self.edit_workspaces)
        self.single_workspace.columnconfigure(0, weight=1)
        self.batch_workspace.columnconfigure(0, weight=1)
        self.edit_workspaces.add(self.single_workspace, text="Single Photo")
        self.edit_workspaces.add(self.batch_workspace, text="Batch Edit")
        self.edit_workspaces.bind("<<NotebookTabChanged>>", self._on_workspace_changed)
        self.batch_editor = PhotoBatchEditor(self.batch_workspace, review=self._review_batch_edit)
        self.batch_editor.grid(row=0, column=0, sticky="nsew")
        ttk.Checkbutton(list_controls, text="Show Image Previews", variable=self.show_image_previews_var,
                        command=self._toggle_image_previews).pack(anchor="w")

        baseline_box = ttk.LabelFrame(
            self.single_workspace,
            text="Single Photo — prompts/settings autosave to this photo only",
            style="Dark.TLabelframe",
            padding=8,
        )
        baseline_box.grid(row=0, column=0, sticky="nsew", pady=(0, 6))
        baseline_box.columnconfigure(0, weight=1)

        ttk.Label(baseline_box, text="Saved positive prompt (this photo only)", style="Dark.TLabel").grid(
            row=0, column=0, sticky="w", pady=(0, 4)
        )
        self.baseline_prompt_text = tk.Text(
            baseline_box,
            height=4,
            bg=TOKENS.colors.surface_secondary,
            fg=TOKENS.colors.text_primary,
            insertbackground=TOKENS.colors.text_primary,
            wrap="word",
            borderwidth=1,
            relief="solid",
        )
        self.baseline_prompt_text.grid(row=1, column=0, sticky="ew", pady=(0, 8))

        ttk.Label(baseline_box, text="Saved negative prompt (this photo only)", style="Dark.TLabel").grid(
            row=2, column=0, sticky="w", pady=(0, 4)
        )
        self.baseline_negative_text = tk.Text(
            baseline_box,
            height=3,
            bg=TOKENS.colors.surface_secondary,
            fg=TOKENS.colors.text_primary,
            insertbackground=TOKENS.colors.text_primary,
            wrap="word",
            borderwidth=1,
            relief="solid",
        )
        self.baseline_negative_text.grid(row=3, column=0, sticky="ew", pady=(0, 8))

        model_row = ttk.Frame(baseline_box, style="Panel.TFrame")
        model_row.grid(row=4, column=0, sticky="ew", pady=(0, 6))
        model_row.columnconfigure(1, weight=1)
        model_row.columnconfigure(3, weight=1)
        ttk.Label(model_row, text="Model", style="Dark.TLabel").grid(
            row=0, column=0, sticky="w", padx=(0, 6)
        )
        self.model_combo = ttk.Combobox(
            model_row,
            textvariable=self.model_var,
            style="Dark.TCombobox",
            state="readonly",
        )
        self.model_combo.grid(row=0, column=1, sticky="ew", padx=(0, 8))
        ttk.Label(model_row, text="VAE", style="Dark.TLabel").grid(
            row=0, column=2, sticky="w", padx=(0, 6)
        )
        self.vae_combo = ttk.Combobox(
            model_row,
            textvariable=self.vae_var,
            style="Dark.TCombobox",
            state="readonly",
        )
        self.vae_combo.grid(row=0, column=3, sticky="ew")

        stage_row = ttk.Frame(baseline_box, style="Panel.TFrame")
        stage_row.grid(row=5, column=0, sticky="ew", pady=(0, 6))
        ttk.Checkbutton(
            stage_row,
            text="img2img",
            variable=self.stage_img2img_var,
            style="Dark.TCheckbutton",
        ).pack(side="left", padx=(0, 8))
        ttk.Checkbutton(
            stage_row,
            text="adetailer",
            variable=self.stage_adetailer_var,
            style="Dark.TCheckbutton",
        ).pack(side="left", padx=(0, 8))
        ttk.Checkbutton(
            stage_row,
            text="upscale",
            variable=self.stage_upscale_var,
            style="Dark.TCheckbutton",
        ).pack(side="left")

        self._build_stage_config_editor(baseline_box, row=6)
        geometry_row = ttk.Frame(baseline_box, style="Panel.TFrame")
        geometry_row.grid(row=11, column=0, sticky="ew", pady=(6, 0))
        ttk.Label(geometry_row, text="Geometry", style="Dark.TLabel").pack(side="left")
        ttk.Combobox(geometry_row, textvariable=self.geometry_mode_var, values=["auto", "custom"],
                     state="readonly", width=8, style="Dark.TCombobox").pack(side="left", padx=6)
        ttk.Label(geometry_row, text="Auto = working image; Custom = width/height above",
                  style="Dark.TLabel").pack(side="left")
        ttk.Label(baseline_box, textvariable=self.settings_error_var, style="Dark.TLabel",
                  wraplength=420).grid(row=12, column=0, sticky="ew")

        ttk.Label(baseline_box, text="Tags (comma-separated)", style="Dark.TLabel").grid(
            row=7, column=0, sticky="w", pady=(0, 4)
        )
        ttk.Entry(baseline_box, textvariable=self.tags_var, style="Dark.TEntry").grid(
            row=8, column=0, sticky="ew", pady=(0, 8)
        )

        ttk.Label(baseline_box, text="Notes", style="Dark.TLabel").grid(
            row=9, column=0, sticky="w", pady=(0, 4)
        )
        self.notes_text = tk.Text(
            baseline_box,
            height=4,
            bg=TOKENS.colors.surface_secondary,
            fg=TOKENS.colors.text_primary,
            insertbackground=TOKENS.colors.text_primary,
            wrap="word",
            borderwidth=1,
            relief="solid",
        )
        self.notes_text.grid(row=10, column=0, sticky="ew")

        optimize_box = ttk.LabelFrame(
            controls,
            text="Run-only overrides — selected or all visible unarchived photos",
            style="Dark.TLabelframe",
            padding=8,
        )
        optimize_box.grid(row=1, column=0, sticky="nsew", pady=(0, 6))
        optimize_box.columnconfigure(1, weight=1)

        ttk.Label(optimize_box, text="Saved positive prompt for active photo", style="Dark.TLabel").grid(
            row=0, column=0, columnspan=2, sticky="w", pady=(0, 4)
        )
        self.current_prompt_text = tk.Text(
            optimize_box,
            height=3,
            bg=TOKENS.colors.surface_tertiary,
            fg=TOKENS.colors.text_muted,
            insertbackground=TOKENS.colors.text_muted,
            wrap="word",
            borderwidth=1,
            relief="solid",
        )
        self.current_prompt_text.grid(row=1, column=0, columnspan=2, sticky="ew", pady=(0, 8))

        ttk.Label(optimize_box, text="Positive mode", style="Dark.TLabel").grid(
            row=2, column=0, sticky="w", padx=(0, 6), pady=(0, 4)
        )
        ttk.Combobox(
            optimize_box,
            textvariable=self.prompt_mode_var,
            values=["append", "replace", "modify"],
            state="readonly",
            style="Dark.TCombobox",
            width=10,
        ).grid(row=2, column=1, sticky="w", pady=(0, 4))

        self.prompt_delta_text = tk.Text(
            optimize_box,
            height=4,
            bg=TOKENS.colors.surface_secondary,
            fg=TOKENS.colors.text_primary,
            insertbackground=TOKENS.colors.text_primary,
            wrap="word",
            borderwidth=1,
            relief="solid",
        )
        self.prompt_delta_text.grid(row=3, column=0, columnspan=2, sticky="ew", pady=(0, 8))

        ttk.Label(optimize_box, text="Saved negative prompt for active photo", style="Dark.TLabel").grid(
            row=4, column=0, columnspan=2, sticky="w", pady=(0, 4)
        )
        self.current_negative_text = tk.Text(
            optimize_box,
            height=3,
            bg=TOKENS.colors.surface_tertiary,
            fg=TOKENS.colors.text_muted,
            insertbackground=TOKENS.colors.text_muted,
            wrap="word",
            borderwidth=1,
            relief="solid",
        )
        self.current_negative_text.grid(row=5, column=0, columnspan=2, sticky="ew", pady=(0, 8))

        ttk.Label(optimize_box, text="Negative mode", style="Dark.TLabel").grid(
            row=6, column=0, sticky="w", padx=(0, 6), pady=(0, 4)
        )
        ttk.Combobox(
            optimize_box,
            textvariable=self.negative_mode_var,
            values=["append", "replace", "modify"],
            state="readonly",
            style="Dark.TCombobox",
            width=10,
        ).grid(row=6, column=1, sticky="w", pady=(0, 4))

        self.negative_delta_text = tk.Text(
            optimize_box,
            height=4,
            bg=TOKENS.colors.surface_secondary,
            fg=TOKENS.colors.text_primary,
            insertbackground=TOKENS.colors.text_primary,
            wrap="word",
            borderwidth=1,
            relief="solid",
        )
        self.negative_delta_text.grid(row=7, column=0, columnspan=2, sticky="ew", pady=(0, 8))

        diff_box = ttk.LabelFrame(
            optimize_box,
            text="Effective prompts — saved baseline + run-only transformation (not autosaved)",
            style="Dark.TLabelframe",
            padding=8,
        )
        diff_box.grid(row=8, column=0, columnspan=2, sticky="ew", pady=(0, 8))
        diff_box.columnconfigure(0, weight=1)

        self.diff_before_label = ttk.Label(
            diff_box,
            text="Before: (select an asset)",
            style="Dark.TLabel",
            justify="left",
            wraplength=460,
        )
        self.diff_before_label.grid(row=0, column=0, sticky="ew", pady=(0, 4))
        self.diff_before_label.grid_remove()  # saved prompts are shown directly above; avoid a third copy
        self.diff_after_label = ttk.Label(
            diff_box,
            text="After: (no changes)",
            style="Dark.TLabel",
            justify="left",
            wraplength=460,
        )
        self.diff_after_label.grid(row=1, column=0, sticky="ew")

        run_row = ttk.Frame(optimize_box, style="Panel.TFrame")
        run_row.grid(row=9, column=0, columnspan=2, sticky="ew", pady=(0, 8))
        ttk.Label(run_row, text="Max photos per compatible job", style="Dark.TLabel").pack(side="left", padx=(0, 8))
        ttk.Spinbox(
            run_row,
            from_=1,
            to=64,
            increment=1,
            textvariable=self.batch_size_var,
            width=6,
            style="Dark.TSpinbox",
        ).pack(side="left")
        help_btn = ttk.Button(
            run_row,
            text="?",
            width=3,
            style="Dark.TButton",
            command=self._show_batch_logic_help,
        )
        help_btn.pack(side="left", padx=(8, 0))
        attach_tooltip(
            help_btn,
            "Only assets with identical effective prompt/model/config are grouped into the same queue job.",
        )

        ttk.Button(
            optimize_box,
            text="Review Selected…",
            style="Primary.TButton",
            command=lambda: self._optimize(batch_all=False),
        ).grid(row=10, column=0, sticky="ew", padx=(0, 4))
        ttk.Button(
            optimize_box,
            text="Review All Visible (unarchived)…",
            style="Dark.TButton",
            command=lambda: self._optimize(batch_all=True),
        ).grid(row=10, column=1, sticky="ew")

        history_box = ttk.LabelFrame(
            self.single_workspace,
            text="Asset History",
            style="Dark.TLabelframe",
            padding=8,
        )
        history_box.grid(row=1, column=0, sticky="nsew")
        history_box.columnconfigure(0, weight=1)
        history_box.rowconfigure(0, weight=1)

        self.history_list = tk.Listbox(
            history_box,
            bg=TOKENS.colors.surface_secondary,
            fg=TOKENS.colors.text_primary,
            selectbackground=TOKENS.colors.accent_primary,
            selectforeground=TOKENS.colors.text_primary,
            borderwidth=0,
            highlightthickness=1,
            highlightbackground=TOKENS.colors.border_subtle,
            exportselection=False,
        )
        self.history_list.grid(row=0, column=0, sticky="nsew")
        self.history_list.bind("<<ListboxSelect>>", self._on_history_select)
        history_scroll = ttk.Scrollbar(
            history_box, orient="vertical", command=self.history_list.yview
        )
        history_scroll.grid(row=0, column=1, sticky="ns")
        self.history_list.configure(yscrollcommand=history_scroll.set)

        actions = ttk.Frame(history_box, style="Panel.TFrame")
        actions.grid(row=1, column=0, columnspan=2, sticky="ew", pady=(8, 0))
        ttk.Button(
            actions,
            text="Promote Latest Result",
            style="Dark.TButton",
            command=self._promote_latest_result,
        ).pack(side="left", fill="x", expand=True, padx=(0, 4))
        ttk.Button(
            actions,
            text="Revert Baseline",
            style="Dark.TButton",
            command=self._revert_baseline,
        ).pack(side="left", fill="x", expand=True)


    def _build_stage_config_editor(self, parent: ttk.LabelFrame, *, row: int) -> None:
        frame = ttk.LabelFrame(
            parent,
            text="Stage Config",
            style="Dark.TLabelframe",
            padding=8,
        )
        frame.grid(row=row, column=0, sticky="ew", pady=(0, 8))
        frame.columnconfigure(0, weight=1)

        img2img_box = ttk.LabelFrame(
            frame,
            text="img2img",
            style="Dark.TLabelframe",
            padding=8,
        )
        img2img_box.grid(row=0, column=0, sticky="ew", pady=(0, 6))
        img2img_box.columnconfigure(1, weight=1)
        img2img_box.columnconfigure(3, weight=1)
        ttk.Label(img2img_box, text="Sampler", style="Dark.TLabel").grid(
            row=0, column=0, sticky="w", padx=(0, 6)
        )
        self.img2img_sampler_combo = ttk.Combobox(
            img2img_box,
            textvariable=self.img2img_sampler_var,
            style="Dark.TCombobox",
        )
        self.img2img_sampler_combo.grid(row=0, column=1, sticky="ew", padx=(0, 8))
        ttk.Label(img2img_box, text="Steps", style="Dark.TLabel").grid(
            row=0, column=2, sticky="w", padx=(0, 6)
        )
        ttk.Spinbox(
            img2img_box,
            from_=1,
            to=200,
            increment=1,
            textvariable=self.img2img_steps_var,
            width=8,
            style="Dark.TSpinbox",
        ).grid(row=0, column=3, sticky="ew")
        ttk.Label(img2img_box, text="CFG", style="Dark.TLabel").grid(
            row=1, column=0, sticky="w", padx=(0, 6), pady=(6, 0)
        )
        ttk.Spinbox(
            img2img_box,
            from_=1.0,
            to=30.0,
            increment=0.1,
            textvariable=self.img2img_cfg_var,
            width=8,
            style="Dark.TSpinbox",
        ).grid(row=1, column=1, sticky="ew", padx=(0, 8), pady=(6, 0))
        ttk.Label(img2img_box, text="Denoise", style="Dark.TLabel").grid(
            row=1, column=2, sticky="w", padx=(0, 6), pady=(6, 0)
        )
        ttk.Spinbox(
            img2img_box,
            from_=0.0,
            to=1.0,
            increment=0.01,
            textvariable=self.img2img_denoise_var,
            width=8,
            style="Dark.TSpinbox",
        ).grid(row=1, column=3, sticky="ew", pady=(6, 0))
        ttk.Label(img2img_box, text="Width", style="Dark.TLabel").grid(
            row=2, column=0, sticky="w", padx=(0, 6), pady=(6, 0)
        )
        self.geometry_width_entry = ttk.Spinbox(
            img2img_box,
            from_=0,
            to=4096,
            increment=64,
            textvariable=self.img2img_width_var,
            width=8,
            style="Dark.TSpinbox",
        )
        self.geometry_width_entry.grid(row=2, column=1, sticky="ew", padx=(0, 8), pady=(6, 0))
        ttk.Label(img2img_box, text="Height", style="Dark.TLabel").grid(
            row=2, column=2, sticky="w", padx=(0, 6), pady=(6, 0)
        )
        self.geometry_height_entry = ttk.Spinbox(
            img2img_box,
            from_=0,
            to=4096,
            increment=64,
            textvariable=self.img2img_height_var,
            width=8,
            style="Dark.TSpinbox",
        )
        self.geometry_height_entry.grid(row=2, column=3, sticky="ew", pady=(6, 0))
        ttk.Label(img2img_box, text="Scheduler", style="Dark.TLabel").grid(row=3, column=0, sticky="w")
        self.img2img_scheduler_combo = ttk.Combobox(img2img_box, textvariable=self.img2img_scheduler_var,
                                                   style="Dark.TCombobox")
        self.img2img_scheduler_combo.grid(row=3, column=1, columnspan=3, sticky="ew")

        adetailer_box = ttk.LabelFrame(
            frame,
            text="ADetailer",
            style="Dark.TLabelframe",
            padding=8,
        )
        adetailer_box.grid(row=1, column=0, sticky="ew", pady=(0, 6))
        adetailer_box.columnconfigure(1, weight=1)
        adetailer_box.columnconfigure(3, weight=1)
        ttk.Label(adetailer_box, text="Model", style="Dark.TLabel").grid(
            row=0, column=0, sticky="w", padx=(0, 6)
        )
        self.adetailer_model_combo = ttk.Combobox(
            adetailer_box,
            textvariable=self.adetailer_model_var,
            style="Dark.TCombobox",
        )
        self.adetailer_model_combo.grid(row=0, column=1, sticky="ew", padx=(0, 8))
        ttk.Label(adetailer_box, text="Confidence", style="Dark.TLabel").grid(
            row=0, column=2, sticky="w", padx=(0, 6)
        )
        ttk.Spinbox(
            adetailer_box,
            from_=0.0,
            to=1.0,
            increment=0.01,
            textvariable=self.adetailer_confidence_var,
            width=8,
            style="Dark.TSpinbox",
        ).grid(row=0, column=3, sticky="ew")
        ttk.Label(adetailer_box, text="Steps", style="Dark.TLabel").grid(
            row=1, column=0, sticky="w", padx=(0, 6), pady=(6, 0)
        )
        ttk.Spinbox(
            adetailer_box,
            from_=1,
            to=200,
            increment=1,
            textvariable=self.adetailer_steps_var,
            width=8,
            style="Dark.TSpinbox",
        ).grid(row=1, column=1, sticky="ew", padx=(0, 8), pady=(6, 0))
        ttk.Label(adetailer_box, text="CFG", style="Dark.TLabel").grid(
            row=1, column=2, sticky="w", padx=(0, 6), pady=(6, 0)
        )
        ttk.Spinbox(
            adetailer_box,
            from_=1.0,
            to=30.0,
            increment=0.1,
            textvariable=self.adetailer_cfg_var,
            width=8,
            style="Dark.TSpinbox",
        ).grid(row=1, column=3, sticky="ew", pady=(6, 0))
        ttk.Label(adetailer_box, text="Denoise", style="Dark.TLabel").grid(
            row=2, column=0, sticky="w", padx=(0, 6), pady=(6, 0)
        )
        ttk.Spinbox(
            adetailer_box,
            from_=0.0,
            to=1.0,
            increment=0.01,
            textvariable=self.adetailer_denoise_var,
            width=8,
            style="Dark.TSpinbox",
        ).grid(row=2, column=1, sticky="ew", padx=(0, 8), pady=(6, 0))
        ttk.Label(adetailer_box, text="Sampler", style="Dark.TLabel").grid(
            row=2, column=2, sticky="w", padx=(0, 6), pady=(6, 0)
        )
        self.adetailer_sampler_combo = ttk.Combobox(
            adetailer_box,
            textvariable=self.adetailer_sampler_var,
            style="Dark.TCombobox",
        )
        self.adetailer_sampler_combo.grid(row=2, column=3, sticky="ew", pady=(6, 0))
        ttk.Label(adetailer_box, text="Scheduler", style="Dark.TLabel").grid(
            row=3, column=0, sticky="w", padx=(0, 6), pady=(6, 0)
        )
        self.adetailer_scheduler_combo = ttk.Combobox(
            adetailer_box,
            textvariable=self.adetailer_scheduler_var,
            style="Dark.TCombobox",
        )
        self.adetailer_scheduler_combo.grid(row=3, column=1, sticky="ew", pady=(6, 0))

        upscale_box = ttk.LabelFrame(
            frame,
            text="Upscale",
            style="Dark.TLabelframe",
            padding=8,
        )
        upscale_box.grid(row=2, column=0, sticky="ew")
        upscale_box.columnconfigure(1, weight=1)
        upscale_box.columnconfigure(3, weight=1)
        ttk.Label(upscale_box, text="Upscaler", style="Dark.TLabel").grid(
            row=0, column=0, sticky="w", padx=(0, 6)
        )
        self.upscale_upscaler_combo = ttk.Combobox(
            upscale_box,
            textvariable=self.upscale_upscaler_var,
            style="Dark.TCombobox",
        )
        self.upscale_upscaler_combo.grid(row=0, column=1, sticky="ew", padx=(0, 8))
        ttk.Label(upscale_box, text="Factor", style="Dark.TLabel").grid(
            row=0, column=2, sticky="w", padx=(0, 6)
        )
        ttk.Spinbox(
            upscale_box,
            from_=1.0,
            to=8.0,
            increment=0.1,
            textvariable=self.upscale_factor_var,
            width=8,
            style="Dark.TSpinbox",
        ).grid(row=0, column=3, sticky="ew")
        ttk.Label(upscale_box, text="Steps", style="Dark.TLabel").grid(
            row=1, column=0, sticky="w", padx=(0, 6), pady=(6, 0)
        )
        ttk.Spinbox(
            upscale_box,
            from_=1,
            to=200,
            increment=1,
            textvariable=self.upscale_steps_var,
            width=8,
            style="Dark.TSpinbox",
        ).grid(row=1, column=1, sticky="ew", padx=(0, 8), pady=(6, 0))
        ttk.Label(upscale_box, text="Denoise", style="Dark.TLabel").grid(
            row=1, column=2, sticky="w", padx=(0, 6), pady=(6, 0)
        )
        ttk.Spinbox(
            upscale_box,
            from_=0.0,
            to=1.0,
            increment=0.01,
            textvariable=self.upscale_denoise_var,
            width=8,
            style="Dark.TSpinbox",
        ).grid(row=1, column=3, sticky="ew", pady=(6, 0))
        ttk.Label(upscale_box, text="Sampler", style="Dark.TLabel").grid(
            row=2, column=0, sticky="w", padx=(0, 6), pady=(6, 0)
        )
        self.upscale_sampler_combo = ttk.Combobox(
            upscale_box,
            textvariable=self.upscale_sampler_var,
            style="Dark.TCombobox",
        )
        self.upscale_sampler_combo.grid(row=2, column=1, sticky="ew", padx=(0, 8), pady=(6, 0))
        ttk.Label(upscale_box, text="Scheduler", style="Dark.TLabel").grid(
            row=2, column=2, sticky="w", padx=(0, 6), pady=(6, 0)
        )
        self.upscale_scheduler_combo = ttk.Combobox(
            upscale_box,
            textvariable=self.upscale_scheduler_var,
            style="Dark.TCombobox",
        )
        self.upscale_scheduler_combo.grid(row=2, column=3, sticky="ew", pady=(6, 0))
        ttk.Label(upscale_box, text="Tile Size", style="Dark.TLabel").grid(
            row=3, column=0, sticky="w", padx=(0, 6), pady=(6, 0)
        )
        ttk.Spinbox(
            upscale_box,
            from_=0,
            to=4096,
            increment=64,
            textvariable=self.upscale_tile_size_var,
            width=8,
            style="Dark.TSpinbox",
        ).grid(row=3, column=1, sticky="ew", padx=(0, 8), pady=(6, 0))
        ttk.Checkbutton(
            upscale_box,
            text="Face restore",
            variable=self.upscale_face_restore_var,
            style="Dark.TCheckbutton",
        ).grid(row=3, column=2, sticky="w", padx=(0, 6), pady=(6, 0))
        ttk.Combobox(
            upscale_box,
            textvariable=self.upscale_face_restore_method_var,
            values=["CodeFormer", "GFPGAN"],
            style="Dark.TCombobox",
        ).grid(row=3, column=3, sticky="ew", pady=(6, 0))

        self._refresh_resource_options()
