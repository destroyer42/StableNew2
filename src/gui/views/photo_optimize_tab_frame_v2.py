from __future__ import annotations

import tkinter as tk
from copy import deepcopy
from pathlib import Path
from tkinter import filedialog, messagebox, ttk
from typing import Any

from src.controller.content_visibility_resolver import REDACTED_TEXT, ContentVisibilityResolver
from src.gui.controllers.review_workflow_adapter import ReviewWorkflowAdapter
from src.gui.tooltip import attach_tooltip
from src.gui.ui_tokens import TOKENS
from src.gui.widgets.scrollable_frame_v2 import ScrollableFrame
from src.gui.widgets.thumbnail_widget_v2 import ThumbnailWidget
from src.photo_optimize import PhotoOptimizeAsset, PhotoOptimizeBaseline, get_photo_optimize_store


class PhotoOptimizeTabFrameV2(ttk.Frame):
    def __init__(
        self,
        master: tk.Misc,
        *,
        app_controller: Any = None,
        app_state: Any = None,
        store: Any = None,
        **kwargs: Any,
    ) -> None:
        super().__init__(master, **kwargs)
        self.app_controller = app_controller
        self.app_state = None
        self.store = store or get_photo_optimize_store()
        self._workflow_adapter = ReviewWorkflowAdapter()
        self._asset_index_by_row: list[str] = []
        self._current_asset_id: str | None = None
        self._current_asset: PhotoOptimizeAsset | None = None
        self._restored_asset_id: str | None = None
        self._history_index_by_row: list[int] = []
        self._suspend_asset_persist = False
        self._app_state_resource_listener: Any = None
        self._app_state_visibility_listener: Any = None
        self._model_name_map: dict[str, str] = {}
        self._vae_name_map: dict[str, str] = {"Automatic": ""}
        self._content_visibility_mode = "nsfw"
        self._pending_asset_refresh_target: str | None = None
        self._pending_resources_payload: dict[str, list[Any]] | None = None
        self._pending_visibility_refresh = False

        self.prompt_mode_var = tk.StringVar(value="append")
        self.negative_mode_var = tk.StringVar(value="append")
        self._prompt_prev_mode = "append"
        self._negative_prev_mode = "append"
        self._prompt_mode_edits: dict[str, str] = {"append": "", "replace": "", "modify": ""}
        self._negative_mode_edits: dict[str, str] = {"append": "", "replace": "", "modify": ""}

        self.model_var = tk.StringVar()
        self.vae_var = tk.StringVar()
        self.tags_var = tk.StringVar()
        self.stage_img2img_var = tk.BooleanVar(value=True)
        self.stage_adetailer_var = tk.BooleanVar(value=False)
        self.stage_upscale_var = tk.BooleanVar(value=False)
        self.batch_size_var = tk.IntVar(value=1)
        self.img2img_sampler_var = tk.StringVar()
        self.img2img_steps_var = tk.IntVar(value=20)
        self.img2img_cfg_var = tk.DoubleVar(value=7.0)
        self.img2img_denoise_var = tk.DoubleVar(value=0.3)
        self.img2img_width_var = tk.IntVar(value=0)
        self.img2img_height_var = tk.IntVar(value=0)
        self.adetailer_model_var = tk.StringVar()
        self.adetailer_confidence_var = tk.DoubleVar(value=0.35)
        self.adetailer_steps_var = tk.IntVar(value=28)
        self.adetailer_cfg_var = tk.DoubleVar(value=7.0)
        self.adetailer_denoise_var = tk.DoubleVar(value=0.4)
        self.adetailer_sampler_var = tk.StringVar()
        self.adetailer_scheduler_var = tk.StringVar(value="Use sampler default")
        self.upscale_upscaler_var = tk.StringVar()
        self.upscale_factor_var = tk.DoubleVar(value=2.0)
        self.upscale_steps_var = tk.IntVar(value=20)
        self.upscale_denoise_var = tk.DoubleVar(value=0.35)
        self.upscale_sampler_var = tk.StringVar(value="Euler a")
        self.upscale_scheduler_var = tk.StringVar(value="normal")
        self.upscale_tile_size_var = tk.IntVar(value=0)
        self.upscale_face_restore_var = tk.BooleanVar(value=False)
        self.upscale_face_restore_method_var = tk.StringVar(value="CodeFormer")

        self.columnconfigure(0, weight=1)
        self.rowconfigure(1, weight=1)

        self._build_header()
        self._build_body()
        self.bind("<Map>", self._on_map, add="+")

        self.prompt_mode_var.trace_add("write", lambda *_: self._on_prompt_mode_changed())
        self.negative_mode_var.trace_add("write", lambda *_: self._on_negative_mode_changed())
        for variable in (
            self.model_var,
            self.vae_var,
            self.tags_var,
            self.stage_img2img_var,
            self.stage_adetailer_var,
            self.stage_upscale_var,
            self.img2img_sampler_var,
            self.img2img_steps_var,
            self.img2img_cfg_var,
            self.img2img_denoise_var,
            self.img2img_width_var,
            self.img2img_height_var,
            self.adetailer_model_var,
            self.adetailer_confidence_var,
            self.adetailer_steps_var,
            self.adetailer_cfg_var,
            self.adetailer_denoise_var,
            self.adetailer_sampler_var,
            self.adetailer_scheduler_var,
            self.upscale_upscaler_var,
            self.upscale_factor_var,
            self.upscale_steps_var,
            self.upscale_denoise_var,
            self.upscale_sampler_var,
            self.upscale_scheduler_var,
            self.upscale_tile_size_var,
            self.upscale_face_restore_var,
            self.upscale_face_restore_method_var,
        ):
            variable.trace_add("write", lambda *_: self._persist_current_asset_baseline())

        self.baseline_prompt_text.bind("<KeyRelease>", lambda _e: self._persist_current_asset_baseline())
        self.baseline_prompt_text.bind("<FocusOut>", lambda _e: self._persist_current_asset_baseline())
        self.baseline_negative_text.bind("<KeyRelease>", lambda _e: self._persist_current_asset_baseline())
        self.baseline_negative_text.bind("<FocusOut>", lambda _e: self._persist_current_asset_baseline())
        self.notes_text.bind("<KeyRelease>", lambda _e: self._persist_current_asset_baseline())
        self.notes_text.bind("<FocusOut>", lambda _e: self._persist_current_asset_baseline())
        self.prompt_delta_text.bind("<KeyRelease>", lambda _e: self._refresh_prompt_diff())
        self.negative_delta_text.bind("<KeyRelease>", lambda _e: self._refresh_prompt_diff())

        self.bind_app_state(app_state)
        self._apply_content_visibility_mode()
        self._refresh_assets()

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
            text="Use Current Pipeline Settings",
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
        ttk.Label(header, text="Batch", style="Dark.TLabel").grid(
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
            text="Optimize Selected",
            style="Primary.TButton",
            command=lambda: self._optimize(batch_all=False),
        )
        self.optimize_selected_header_btn.grid(row=0, column=6, sticky="w", padx=(0, 6))
        self.optimize_all_header_btn = ttk.Button(
            header,
            text="Optimize All",
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

    def _build_body(self) -> None:
        self.body_scroll = ScrollableFrame(self, style="Panel.TFrame")
        self.body_scroll.grid(row=1, column=0, sticky="nsew", padx=6, pady=(0, 6))
        body = self.body_scroll.inner
        body.columnconfigure(0, weight=1, uniform="photo_optimize")
        body.columnconfigure(1, weight=2, uniform="photo_optimize")
        body.columnconfigure(2, weight=2, uniform="photo_optimize")
        body.rowconfigure(0, weight=1)

        assets_frame = ttk.LabelFrame(body, text="Assets", style="Dark.TLabelframe", padding=8)
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
        assets_scroll = ttk.Scrollbar(assets_frame, orient="vertical", command=self.assets_list.yview)
        assets_scroll.grid(row=0, column=1, sticky="ns")
        self.assets_list.configure(yscrollcommand=assets_scroll.set)

        preview_frame = ttk.LabelFrame(
            body,
            text="Preview & Asset Metadata",
            style="Dark.TLabelframe",
            padding=8,
        )
        preview_frame.grid(row=0, column=1, sticky="nsew", padx=(0, 6))
        preview_frame.columnconfigure(0, weight=1)
        preview_frame.columnconfigure(1, weight=1)
        preview_frame.rowconfigure(1, weight=1)

        ttk.Label(preview_frame, text="Original", style="Dark.TLabel").grid(
            row=0, column=0, sticky="w", pady=(0, 4)
        )
        ttk.Label(preview_frame, text="Latest Output", style="Dark.TLabel").grid(
            row=0, column=1, sticky="w", pady=(0, 4)
        )
        self.original_preview = ThumbnailWidget(
            preview_frame,
            width=220,
            height=220,
            placeholder_text="Import a photo",
        )
        self.original_preview.grid(row=1, column=0, sticky="nsew", padx=(0, 6))
        self.latest_preview = ThumbnailWidget(
            preview_frame,
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
        self.meta_label.grid(row=2, column=0, columnspan=2, sticky="ew", pady=(8, 0))

        controls = ttk.Frame(body, style="Panel.TFrame")
        controls.grid(row=0, column=2, sticky="nsew")
        controls.columnconfigure(0, weight=1)
        controls.rowconfigure(0, weight=1)
        controls.rowconfigure(1, weight=1)
        controls.rowconfigure(2, weight=1)

        baseline_box = ttk.LabelFrame(
            controls,
            text="Baseline Editor",
            style="Dark.TLabelframe",
            padding=8,
        )
        baseline_box.grid(row=0, column=0, sticky="nsew", pady=(0, 6))
        baseline_box.columnconfigure(0, weight=1)

        ttk.Label(baseline_box, text="Baseline + prompt", style="Dark.TLabel").grid(
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

        ttk.Label(baseline_box, text="Baseline - prompt", style="Dark.TLabel").grid(
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
        ttk.Label(model_row, text="Model", style="Dark.TLabel").grid(row=0, column=0, sticky="w", padx=(0, 6))
        self.model_combo = ttk.Combobox(
            model_row,
            textvariable=self.model_var,
            style="Dark.TCombobox",
            state="readonly",
        )
        self.model_combo.grid(
            row=0, column=1, sticky="ew", padx=(0, 8)
        )
        ttk.Label(model_row, text="VAE", style="Dark.TLabel").grid(row=0, column=2, sticky="w", padx=(0, 6))
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
            text="Prompt Deltas & Optimize",
            style="Dark.TLabelframe",
            padding=8,
        )
        optimize_box.grid(row=1, column=0, sticky="nsew", pady=(0, 6))
        optimize_box.columnconfigure(1, weight=1)

        ttk.Label(optimize_box, text="Current + prompt", style="Dark.TLabel").grid(
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

        ttk.Label(optimize_box, text="Current - prompt", style="Dark.TLabel").grid(
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
            text="Before / After Diff",
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
        ttk.Label(run_row, text="Batch size", style="Dark.TLabel").pack(side="left", padx=(0, 8))
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
            text="Optimize Selected",
            style="Primary.TButton",
            command=lambda: self._optimize(batch_all=False),
        ).grid(row=10, column=0, sticky="ew", padx=(0, 4))
        ttk.Button(
            optimize_box,
            text="Optimize All Assets",
            style="Dark.TButton",
            command=lambda: self._optimize(batch_all=True),
        ).grid(row=10, column=1, sticky="ew")

        history_box = ttk.LabelFrame(
            controls,
            text="Asset History",
            style="Dark.TLabelframe",
            padding=8,
        )
        history_box.grid(row=2, column=0, sticky="nsew")
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
        history_scroll = ttk.Scrollbar(history_box, orient="vertical", command=self.history_list.yview)
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

    def _on_import_photos(self) -> None:
        files = filedialog.askopenfilenames(
            title="Import photos for Photo Optomize",
            filetypes=[
                ("Image files", "*.png *.jpg *.jpeg *.webp"),
                ("All files", "*.*"),
            ],
        )
        if not files:
            return
        defaults = self._build_import_defaults()
        imported_ids: list[str] = []
        for file_path in files:
            asset = self.store.import_photo(file_path, baseline_defaults=defaults)
            imported_ids.append(asset.asset_id)
        self._refresh_assets(select_asset_id=imported_ids[0] if imported_ids else None)

    def _build_import_defaults(self) -> dict[str, Any]:
        controller = self.app_controller
        builder = getattr(controller, "build_photo_optimize_defaults", None)
        if callable(builder):
            try:
                defaults = builder()
                if isinstance(defaults, dict):
                    return defaults
            except Exception:
                pass
        return {
            "prompt": "",
            "negative_prompt": "",
            "model": "",
            "vae": "",
            "stage_defaults": {"img2img": True, "adetailer": False, "upscale": False},
            "config": {},
            "source": "manual",
        }

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
        ttk.Label(img2img_box, text="Sampler", style="Dark.TLabel").grid(row=0, column=0, sticky="w", padx=(0, 6))
        self.img2img_sampler_combo = ttk.Combobox(
            img2img_box,
            textvariable=self.img2img_sampler_var,
            style="Dark.TCombobox",
        )
        self.img2img_sampler_combo.grid(row=0, column=1, sticky="ew", padx=(0, 8))
        ttk.Label(img2img_box, text="Steps", style="Dark.TLabel").grid(row=0, column=2, sticky="w", padx=(0, 6))
        ttk.Spinbox(
            img2img_box,
            from_=1,
            to=200,
            increment=1,
            textvariable=self.img2img_steps_var,
            width=8,
            style="Dark.TSpinbox",
        ).grid(row=0, column=3, sticky="ew")
        ttk.Label(img2img_box, text="CFG", style="Dark.TLabel").grid(row=1, column=0, sticky="w", padx=(0, 6), pady=(6, 0))
        ttk.Spinbox(
            img2img_box,
            from_=1.0,
            to=30.0,
            increment=0.1,
            textvariable=self.img2img_cfg_var,
            width=8,
            style="Dark.TSpinbox",
        ).grid(row=1, column=1, sticky="ew", padx=(0, 8), pady=(6, 0))
        ttk.Label(img2img_box, text="Denoise", style="Dark.TLabel").grid(row=1, column=2, sticky="w", padx=(0, 6), pady=(6, 0))
        ttk.Spinbox(
            img2img_box,
            from_=0.0,
            to=1.0,
            increment=0.01,
            textvariable=self.img2img_denoise_var,
            width=8,
            style="Dark.TSpinbox",
        ).grid(row=1, column=3, sticky="ew", pady=(6, 0))
        ttk.Label(img2img_box, text="Width", style="Dark.TLabel").grid(row=2, column=0, sticky="w", padx=(0, 6), pady=(6, 0))
        ttk.Spinbox(
            img2img_box,
            from_=0,
            to=4096,
            increment=64,
            textvariable=self.img2img_width_var,
            width=8,
            style="Dark.TSpinbox",
        ).grid(row=2, column=1, sticky="ew", padx=(0, 8), pady=(6, 0))
        ttk.Label(img2img_box, text="Height", style="Dark.TLabel").grid(row=2, column=2, sticky="w", padx=(0, 6), pady=(6, 0))
        ttk.Spinbox(
            img2img_box,
            from_=0,
            to=4096,
            increment=64,
            textvariable=self.img2img_height_var,
            width=8,
            style="Dark.TSpinbox",
        ).grid(row=2, column=3, sticky="ew", pady=(6, 0))

        adetailer_box = ttk.LabelFrame(
            frame,
            text="ADetailer",
            style="Dark.TLabelframe",
            padding=8,
        )
        adetailer_box.grid(row=1, column=0, sticky="ew", pady=(0, 6))
        adetailer_box.columnconfigure(1, weight=1)
        adetailer_box.columnconfigure(3, weight=1)
        ttk.Label(adetailer_box, text="Model", style="Dark.TLabel").grid(row=0, column=0, sticky="w", padx=(0, 6))
        self.adetailer_model_combo = ttk.Combobox(
            adetailer_box,
            textvariable=self.adetailer_model_var,
            style="Dark.TCombobox",
        )
        self.adetailer_model_combo.grid(row=0, column=1, sticky="ew", padx=(0, 8))
        ttk.Label(adetailer_box, text="Confidence", style="Dark.TLabel").grid(row=0, column=2, sticky="w", padx=(0, 6))
        ttk.Spinbox(
            adetailer_box,
            from_=0.0,
            to=1.0,
            increment=0.01,
            textvariable=self.adetailer_confidence_var,
            width=8,
            style="Dark.TSpinbox",
        ).grid(row=0, column=3, sticky="ew")
        ttk.Label(adetailer_box, text="Steps", style="Dark.TLabel").grid(row=1, column=0, sticky="w", padx=(0, 6), pady=(6, 0))
        ttk.Spinbox(
            adetailer_box,
            from_=1,
            to=200,
            increment=1,
            textvariable=self.adetailer_steps_var,
            width=8,
            style="Dark.TSpinbox",
        ).grid(row=1, column=1, sticky="ew", padx=(0, 8), pady=(6, 0))
        ttk.Label(adetailer_box, text="CFG", style="Dark.TLabel").grid(row=1, column=2, sticky="w", padx=(0, 6), pady=(6, 0))
        ttk.Spinbox(
            adetailer_box,
            from_=1.0,
            to=30.0,
            increment=0.1,
            textvariable=self.adetailer_cfg_var,
            width=8,
            style="Dark.TSpinbox",
        ).grid(row=1, column=3, sticky="ew", pady=(6, 0))
        ttk.Label(adetailer_box, text="Denoise", style="Dark.TLabel").grid(row=2, column=0, sticky="w", padx=(0, 6), pady=(6, 0))
        ttk.Spinbox(
            adetailer_box,
            from_=0.0,
            to=1.0,
            increment=0.01,
            textvariable=self.adetailer_denoise_var,
            width=8,
            style="Dark.TSpinbox",
        ).grid(row=2, column=1, sticky="ew", padx=(0, 8), pady=(6, 0))
        ttk.Label(adetailer_box, text="Sampler", style="Dark.TLabel").grid(row=2, column=2, sticky="w", padx=(0, 6), pady=(6, 0))
        self.adetailer_sampler_combo = ttk.Combobox(
            adetailer_box,
            textvariable=self.adetailer_sampler_var,
            style="Dark.TCombobox",
        )
        self.adetailer_sampler_combo.grid(row=2, column=3, sticky="ew", pady=(6, 0))
        ttk.Label(adetailer_box, text="Scheduler", style="Dark.TLabel").grid(row=3, column=0, sticky="w", padx=(0, 6), pady=(6, 0))
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
        ttk.Label(upscale_box, text="Upscaler", style="Dark.TLabel").grid(row=0, column=0, sticky="w", padx=(0, 6))
        self.upscale_upscaler_combo = ttk.Combobox(
            upscale_box,
            textvariable=self.upscale_upscaler_var,
            style="Dark.TCombobox",
        )
        self.upscale_upscaler_combo.grid(row=0, column=1, sticky="ew", padx=(0, 8))
        ttk.Label(upscale_box, text="Factor", style="Dark.TLabel").grid(row=0, column=2, sticky="w", padx=(0, 6))
        ttk.Spinbox(
            upscale_box,
            from_=1.0,
            to=8.0,
            increment=0.1,
            textvariable=self.upscale_factor_var,
            width=8,
            style="Dark.TSpinbox",
        ).grid(row=0, column=3, sticky="ew")
        ttk.Label(upscale_box, text="Steps", style="Dark.TLabel").grid(row=1, column=0, sticky="w", padx=(0, 6), pady=(6, 0))
        ttk.Spinbox(
            upscale_box,
            from_=1,
            to=200,
            increment=1,
            textvariable=self.upscale_steps_var,
            width=8,
            style="Dark.TSpinbox",
        ).grid(row=1, column=1, sticky="ew", padx=(0, 8), pady=(6, 0))
        ttk.Label(upscale_box, text="Denoise", style="Dark.TLabel").grid(row=1, column=2, sticky="w", padx=(0, 6), pady=(6, 0))
        ttk.Spinbox(
            upscale_box,
            from_=0.0,
            to=1.0,
            increment=0.01,
            textvariable=self.upscale_denoise_var,
            width=8,
            style="Dark.TSpinbox",
        ).grid(row=1, column=3, sticky="ew", pady=(6, 0))
        ttk.Label(upscale_box, text="Sampler", style="Dark.TLabel").grid(row=2, column=0, sticky="w", padx=(0, 6), pady=(6, 0))
        self.upscale_sampler_combo = ttk.Combobox(
            upscale_box,
            textvariable=self.upscale_sampler_var,
            style="Dark.TCombobox",
        )
        self.upscale_sampler_combo.grid(row=2, column=1, sticky="ew", padx=(0, 8), pady=(6, 0))
        ttk.Label(upscale_box, text="Scheduler", style="Dark.TLabel").grid(row=2, column=2, sticky="w", padx=(0, 6), pady=(6, 0))
        self.upscale_scheduler_combo = ttk.Combobox(
            upscale_box,
            textvariable=self.upscale_scheduler_var,
            style="Dark.TCombobox",
        )
        self.upscale_scheduler_combo.grid(row=2, column=3, sticky="ew", pady=(6, 0))
        ttk.Label(upscale_box, text="Tile Size", style="Dark.TLabel").grid(row=3, column=0, sticky="w", padx=(0, 6), pady=(6, 0))
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

    def _refresh_assets(self, select_asset_id: str | None = None) -> None:
        assets = self.store.list_assets()
        self.assets_list.delete(0, tk.END)
        self._asset_index_by_row = []
        for asset in assets:
            label = asset.source_filename
            if asset.history:
                label = f"{label} ({len(asset.history)})"
            self.assets_list.insert(tk.END, label)
            self._asset_index_by_row.append(asset.asset_id)
        self.selection_label.config(text=f"{len(assets)} asset(s)")

        target_asset_id = select_asset_id or self._restored_asset_id or self._current_asset_id
        if target_asset_id and target_asset_id in self._asset_index_by_row:
            index = self._asset_index_by_row.index(target_asset_id)
            self.assets_list.selection_clear(0, tk.END)
            self.assets_list.selection_set(index)
            self.assets_list.activate(index)
            self._show_asset(target_asset_id)
            self._restored_asset_id = None
            return
        if self._asset_index_by_row:
            self.assets_list.selection_clear(0, tk.END)
            self.assets_list.selection_set(0)
            self._show_asset(self._asset_index_by_row[0])
        else:
            self._clear_selection()

    def _clear_selection(self) -> None:
        self._current_asset_id = None
        self._current_asset = None
        self.original_preview.clear()
        self.latest_preview.clear()
        self.meta_label.config(text="Metadata: n/a")
        self.history_list.delete(0, tk.END)
        self._history_index_by_row = []
        self._set_text(self.baseline_prompt_text, "")
        self._set_text(self.baseline_negative_text, "")
        self._set_text(self.notes_text, "")
        self.model_var.set("")
        self.vae_var.set("")
        self.tags_var.set("")
        self._load_baseline_config_form({})
        self._apply_content_visibility_mode()
        self._set_text(self.prompt_delta_text, "")
        self._set_text(self.negative_delta_text, "")
        self._refresh_prompt_diff()

    def _on_asset_select(self, _event: tk.Event) -> None:
        idxs = list(self.assets_list.curselection())
        if not idxs:
            return
        idx = int(idxs[0])
        if idx < 0 or idx >= len(self._asset_index_by_row):
            return
        self._show_asset(self._asset_index_by_row[idx])

    def _show_asset(self, asset_id: str) -> None:
        asset = self.store.get_asset(asset_id)
        if asset is None:
            return
        self._current_asset_id = asset.asset_id
        self._current_asset = asset
        self._suspend_asset_persist = True
        try:
            self._refresh_resource_options()
            self._set_text(self.baseline_prompt_text, asset.baseline.prompt)
            self._set_text(self.baseline_negative_text, asset.baseline.negative_prompt)
            self._set_text(self.notes_text, asset.notes)
            self.model_var.set(
                self._display_for_internal(asset.baseline.model, self._model_name_map) or asset.baseline.model
            )
            self.vae_var.set(
                self._display_for_internal(asset.baseline.vae, self._vae_name_map)
                or ("Automatic" if not asset.baseline.vae else asset.baseline.vae)
            )
            self.tags_var.set(", ".join(asset.tags))
            self.stage_img2img_var.set(bool(asset.baseline.stage_defaults.get("img2img", True)))
            self.stage_adetailer_var.set(bool(asset.baseline.stage_defaults.get("adetailer", False)))
            self.stage_upscale_var.set(bool(asset.baseline.stage_defaults.get("upscale", False)))
            self._load_baseline_config_form(asset.baseline.config)
            self._apply_content_visibility_mode()
            self._reset_prompt_mode_state(asset)
            self._populate_history(asset)
            self._refresh_preview(asset)
            self._refresh_prompt_diff()
        finally:
            self._suspend_asset_persist = False

    def _refresh_preview(self, asset: PhotoOptimizeAsset, history_index: int | None = None) -> None:
        self.original_preview.set_image_from_path(Path(asset.managed_original_path))
        history_entry = None
        if history_index is not None and 0 <= history_index < len(asset.history):
            history_entry = asset.history[history_index]
        elif asset.history:
            history_entry = asset.history[-1]
        if history_entry and history_entry.output_paths:
            self.latest_preview.set_image_from_path(Path(history_entry.output_paths[-1]))
        else:
            self.latest_preview.clear()
        last_run = asset.history[-1].run_id if asset.history else "none"
        working_name = Path(asset.current_input_path).name if asset.current_input_path else asset.source_filename
        self.meta_label.config(
            text=(
                f"Asset: {asset.source_filename}\n"
                f"Working image: {working_name}\n"
                f"Model: {asset.baseline.model or '(pipeline fallback)'} | "
                f"VAE: {asset.baseline.vae or '(pipeline fallback)'}\n"
                f"History entries: {len(asset.history)} | Last run: {last_run}"
            )
        )

    def _populate_history(self, asset: PhotoOptimizeAsset) -> None:
        self.history_list.delete(0, tk.END)
        self._history_index_by_row = []
        for idx, entry in enumerate(reversed(asset.history)):
            display_index = len(asset.history) - idx - 1
            label = f"{entry.created_at} | {entry.run_id} | {', '.join(entry.stages or [])}"
            self.history_list.insert(tk.END, label)
            self._history_index_by_row.append(display_index)

    def _on_history_select(self, _event: tk.Event) -> None:
        if self._current_asset is None:
            return
        idxs = list(self.history_list.curselection())
        if not idxs:
            return
        row = int(idxs[0])
        if row < 0 or row >= len(self._history_index_by_row):
            return
        history_index = self._history_index_by_row[row]
        self._refresh_preview(self._current_asset, history_index=history_index)

    def _selected_asset_ids(self, *, batch_all: bool) -> list[str]:
        if batch_all:
            return list(self._asset_index_by_row)
        idxs = list(self.assets_list.curselection())
        asset_ids: list[str] = []
        for idx in idxs:
            if 0 <= int(idx) < len(self._asset_index_by_row):
                asset_ids.append(self._asset_index_by_row[int(idx)])
        if not asset_ids and self._current_asset_id:
            asset_ids = [self._current_asset_id]
        return asset_ids

    def _selected_stages(self) -> list[str]:
        stages: list[str] = []
        if self.stage_img2img_var.get():
            stages.append("img2img")
        if self.stage_adetailer_var.get():
            stages.append("adetailer")
        if self.stage_upscale_var.get():
            stages.append("upscale")
        return stages

    def _optimize(self, *, batch_all: bool) -> None:
        self._persist_current_asset_baseline()
        asset_ids = self._selected_asset_ids(batch_all=batch_all)
        if not asset_ids:
            messagebox.showwarning("No assets", "Select one or more assets first.")
            return
        stages = self._selected_stages()
        if not stages:
            messagebox.showwarning("No stages", "Select at least one stage.")
            return
        controller = self.app_controller
        handler = getattr(controller, "on_optimize_photo_assets", None)
        if not callable(handler):
            messagebox.showerror("Controller missing", "Photo optimize controller is not connected.")
            return

        assets_payload: list[dict[str, Any]] = []
        for asset_id in asset_ids:
            asset = self.store.get_asset(asset_id)
            if asset is None:
                continue
            assets_payload.append(
                {
                    "asset_id": asset.asset_id,
                    "managed_original_path": asset.managed_original_path,
                    "input_image_path": str(asset.current_input_path),
                    "baseline": asset.baseline.to_dict(),
                }
            )
        if not assets_payload:
            messagebox.showwarning("No assets", "No valid assets were available for optimization.")
            return

        try:
            submitted = handler(
                assets=assets_payload,
                stages=stages,
                prompt_delta=self._get_text(self.prompt_delta_text),
                negative_prompt_delta=self._get_text(self.negative_delta_text),
                prompt_mode=self.prompt_mode_var.get(),
                negative_prompt_mode=self.negative_mode_var.get(),
                batch_size=max(1, int(self.batch_size_var.get() or 1)),
            )
            messagebox.showinfo("Submitted", f"Submitted {submitted} photo optimize job(s).")
        except Exception as exc:
            messagebox.showerror("Optimize failed", str(exc))

    def _use_current_pipeline_settings(self) -> None:
        if self._current_asset is None:
            messagebox.showwarning("No asset", "Select an asset first.")
            return
        defaults = self._build_import_defaults()
        baseline = PhotoOptimizeBaseline.from_dict(self._current_asset.baseline.to_dict())
        baseline.model = str(defaults.get("model") or "")
        baseline.vae = str(defaults.get("vae") or "")
        baseline.config = deepcopy(defaults.get("config") or {})
        baseline.stage_defaults = dict(defaults.get("stage_defaults") or baseline.stage_defaults)
        self.store.update_asset_fields(
            self._current_asset.asset_id,
            notes=self._current_asset.notes,
            tags=list(self._current_asset.tags),
            baseline=baseline,
        )
        self._show_asset(self._current_asset.asset_id)

    def _show_interrogate_unavailable(self) -> None:
        messagebox.showinfo(
            "Interrogate unavailable",
            "Prompt interrogation is not wired in this MVP. Set the baseline prompt manually.",
        )

    def _promote_latest_result(self) -> None:
        if self._current_asset is None:
            messagebox.showwarning("No asset", "Select an asset first.")
            return
        try:
            self.store.promote_latest_output_as_baseline(self._current_asset.asset_id)
            self._show_asset(self._current_asset.asset_id)
            messagebox.showinfo("Promoted", "Latest result promoted as the working baseline.")
        except Exception as exc:
            messagebox.showerror("Promote failed", str(exc))

    def _revert_baseline(self) -> None:
        if self._current_asset is None:
            messagebox.showwarning("No asset", "Select an asset first.")
            return
        try:
            self.store.revert_baseline(self._current_asset.asset_id)
            self._show_asset(self._current_asset.asset_id)
            messagebox.showinfo("Reverted", "Baseline reverted to the previous snapshot.")
        except Exception as exc:
            messagebox.showerror("Revert failed", str(exc))

    def _show_batch_logic_help(self) -> None:
        messagebox.showinfo(
            "Batch Logic",
            "How Photo Optomize batching works:\n\n"
            "- Selected assets are grouped only when their final prompt, model, and merged config match.\n"
            "- Compatible assets can share one queue job.\n"
            "- Incompatible assets are split into separate queue jobs automatically.\n"
            "- After completion, each asset still gets its own copied output and history entry.",
        )

    def _persist_current_asset_baseline(self) -> None:
        if self._suspend_asset_persist or self._current_asset is None:
            return
        asset = self.store.get_asset(self._current_asset.asset_id)
        if asset is None:
            return
        baseline = PhotoOptimizeBaseline.from_dict(asset.baseline.to_dict())
        baseline.prompt = self._get_text(self.baseline_prompt_text)
        baseline.negative_prompt = self._get_text(self.baseline_negative_text)
        baseline.model = self._internal_for_display(self.model_var.get(), self._model_name_map)
        baseline.vae = self._internal_for_display(self.vae_var.get(), self._vae_name_map)
        baseline.stage_defaults = {
            "img2img": bool(self.stage_img2img_var.get()),
            "adetailer": bool(self.stage_adetailer_var.get()),
            "upscale": bool(self.stage_upscale_var.get()),
        }
        baseline.config = self._merge_nested_dicts(
            baseline.config if isinstance(baseline.config, dict) else {},
            self._collect_baseline_config_from_form(),
        )
        if not baseline.working_image_path:
            baseline.working_image_path = asset.managed_original_path
        updated = self.store.update_asset_fields(
            asset.asset_id,
            notes=self._get_text(self.notes_text),
            tags=[item.strip() for item in self.tags_var.get().split(",") if item.strip()],
            baseline=baseline,
        )
        self._current_asset = updated
        self._apply_content_visibility_mode()
        self._refresh_prompt_diff()
        self._refresh_preview(updated)

    def _interrogate_current_asset(self) -> None:
        if self._current_asset is None:
            messagebox.showwarning("No asset", "Select an asset first.")
            return
        controller = self.app_controller
        interrogate = getattr(controller, "interrogate_photo_path", None)
        if not callable(interrogate):
            messagebox.showerror("Controller missing", "Photo interrogation is not connected.")
            return
        try:
            caption = str(interrogate(str(self._current_asset.current_input_path)) or "").strip()
            if not caption:
                raise RuntimeError("Interrogate returned an empty caption")
            asset = self.store.get_asset(self._current_asset.asset_id)
            if asset is None:
                raise RuntimeError("Selected asset could not be reloaded")
            baseline = PhotoOptimizeBaseline.from_dict(asset.baseline.to_dict())
            baseline.prompt = caption
            baseline.source = "interrogated"
            self.store.update_asset_fields(
                asset.asset_id,
                notes=asset.notes,
                tags=list(asset.tags),
                baseline=baseline,
            )
            self._show_asset(asset.asset_id)
        except Exception as exc:
            messagebox.showerror("Interrogate failed", str(exc))

    def _reset_prompt_mode_state(self, asset: PhotoOptimizeAsset) -> None:
        self._prompt_mode_edits = {
            "append": "",
            "replace": "",
            "modify": asset.baseline.prompt,
        }
        self._negative_mode_edits = {
            "append": "",
            "replace": "",
            "modify": asset.baseline.negative_prompt,
        }
        self._prompt_prev_mode = self.prompt_mode_var.get() or "append"
        self._negative_prev_mode = self.negative_mode_var.get() or "append"
        self._sync_edit_box_to_mode("prompt")
        self._sync_edit_box_to_mode("negative")

    def _sync_edit_box_to_mode(self, which: str) -> None:
        if self._current_asset is None:
            return
        if which == "prompt":
            mode = self.prompt_mode_var.get() or "append"
            text = self._prompt_mode_edits.get(mode, "")
            if mode == "modify" and not text:
                text = self._current_asset.baseline.prompt
                self._prompt_mode_edits["modify"] = text
            self._set_text(self.prompt_delta_text, text)
        else:
            mode = self.negative_mode_var.get() or "append"
            text = self._negative_mode_edits.get(mode, "")
            if mode == "modify" and not text:
                text = self._current_asset.baseline.negative_prompt
                self._negative_mode_edits["modify"] = text
            self._set_text(self.negative_delta_text, text)
        self._refresh_prompt_diff()

    def _on_prompt_mode_changed(self) -> None:
        self._prompt_mode_edits[self._prompt_prev_mode] = self._get_text(self.prompt_delta_text)
        self._prompt_prev_mode = self.prompt_mode_var.get() or "append"
        self._sync_edit_box_to_mode("prompt")

    def _on_negative_mode_changed(self) -> None:
        self._negative_mode_edits[self._negative_prev_mode] = self._get_text(self.negative_delta_text)
        self._negative_prev_mode = self.negative_mode_var.get() or "append"
        self._sync_edit_box_to_mode("negative")

    def _refresh_prompt_diff(self) -> None:
        asset = self._current_asset
        base_prompt = asset.baseline.prompt if asset is not None else ""
        base_negative = asset.baseline.negative_prompt if asset is not None else ""
        diff = self._workflow_adapter.build_prompt_diff(
            base_prompt=base_prompt,
            base_negative_prompt=base_negative,
            prompt_delta=self._get_text(self.prompt_delta_text),
            negative_prompt_delta=self._get_text(self.negative_delta_text),
            prompt_mode=self.prompt_mode_var.get(),
            negative_prompt_mode=self.negative_mode_var.get(),
        )
        resolver = self._visibility_resolver()
        subject = self._current_visibility_subject()
        self.diff_before_label.config(text=resolver.redact_text(diff.before_text, item=subject))
        self.diff_after_label.config(text=resolver.redact_text(diff.after_text, item=subject))

    def _set_readonly_text(self, widget: tk.Text, value: str) -> None:
        widget.configure(state="normal")
        widget.delete("1.0", tk.END)
        widget.insert("1.0", value or "")
        widget.configure(state="disabled")

    def _visibility_resolver(self) -> ContentVisibilityResolver:
        return ContentVisibilityResolver(self._content_visibility_mode)

    def _current_visibility_subject(self) -> dict[str, str]:
        asset = self._current_asset
        if asset is None:
            return {"positive_prompt": "", "negative_prompt": "", "name": ""}
        return {
            "positive_prompt": asset.baseline.prompt,
            "negative_prompt": asset.baseline.negative_prompt,
            "name": asset.source_filename,
        }

    def _apply_content_visibility_mode(self) -> None:
        resolver = self._visibility_resolver()
        subject = self._current_visibility_subject()
        prompt_value = resolver.redact_text(subject.get("positive_prompt", ""), item=subject)
        negative_value = resolver.redact_text(subject.get("negative_prompt", ""), item=subject)
        self._set_readonly_text(self.current_prompt_text, prompt_value)
        self._set_readonly_text(self.current_negative_text, negative_value)
        self.visibility_banner.config(text="")

    def on_content_visibility_mode_changed(self, mode: str | None = None) -> None:
        self._content_visibility_mode = str(
            mode or getattr(getattr(self, "app_state", None), "content_visibility_mode", "nsfw") or "nsfw"
        )
        self._pending_visibility_refresh = False
        self._apply_content_visibility_mode()
        self._refresh_prompt_diff()

    def _on_content_visibility_mode_changed(self) -> None:
        mode = str(
            getattr(getattr(self, "app_state", None), "content_visibility_mode", "nsfw") or "nsfw"
        )
        self._content_visibility_mode = mode
        if not bool(self.winfo_ismapped()):
            self._pending_visibility_refresh = True
            return
        self.on_content_visibility_mode_changed(mode)

    def _set_text(self, widget: tk.Text, value: str) -> None:
        widget.delete("1.0", tk.END)
        widget.insert("1.0", value or "")

    def _get_text(self, widget: tk.Text) -> str:
        return widget.get("1.0", tk.END).strip()

    def _load_baseline_config_form(self, config: dict[str, Any] | None) -> None:
        data = config if isinstance(config, dict) else {}
        img2img = data.get("img2img") if isinstance(data.get("img2img"), dict) else {}
        adetailer = data.get("adetailer") if isinstance(data.get("adetailer"), dict) else {}
        upscale = data.get("upscale") if isinstance(data.get("upscale"), dict) else {}

        self.img2img_sampler_var.set(
            str(img2img.get("sampler_name") or data.get("img2img_sampler_name") or data.get("sampler_name") or "")
        )
        self.img2img_steps_var.set(
            self._safe_int(img2img.get("steps") or data.get("img2img_steps") or data.get("steps"), 20)
        )
        self.img2img_cfg_var.set(
            self._safe_float(img2img.get("cfg_scale") or data.get("img2img_cfg_scale") or data.get("cfg_scale"), 7.0)
        )
        self.img2img_denoise_var.set(
            self._safe_float(
                img2img.get("denoising_strength") or data.get("img2img_denoising_strength"),
                0.3,
            )
        )
        self.img2img_width_var.set(self._safe_int(img2img.get("width"), 0))
        self.img2img_height_var.set(self._safe_int(img2img.get("height"), 0))

        self.adetailer_model_var.set(
            str(adetailer.get("adetailer_model") or adetailer.get("ad_model") or "")
        )
        self.adetailer_confidence_var.set(
            self._safe_float(
                adetailer.get("adetailer_confidence") or adetailer.get("ad_confidence"),
                0.35,
            )
        )
        self.adetailer_steps_var.set(
            self._safe_int(
                adetailer.get("adetailer_steps") or adetailer.get("ad_steps") or data.get("adetailer_steps"),
                28,
            )
        )
        self.adetailer_cfg_var.set(
            self._safe_float(
                adetailer.get("adetailer_cfg")
                or adetailer.get("ad_cfg_scale")
                or data.get("adetailer_cfg_scale"),
                7.0,
            )
        )
        self.adetailer_denoise_var.set(
            self._safe_float(
                adetailer.get("adetailer_denoise")
                or adetailer.get("ad_denoising_strength")
                or data.get("adetailer_denoising_strength"),
                0.4,
            )
        )
        self.adetailer_sampler_var.set(
            str(
                adetailer.get("adetailer_sampler")
                or adetailer.get("ad_sampler")
                or data.get("adetailer_sampler_name")
                or ""
            )
        )
        self.adetailer_scheduler_var.set(
            str(adetailer.get("scheduler") or adetailer.get("ad_scheduler") or "Use sampler default")
        )

        self.upscale_upscaler_var.set(str(upscale.get("upscaler") or data.get("upscaler") or ""))
        self.upscale_factor_var.set(
            self._safe_float(
                upscale.get("upscaling_resize")
                or upscale.get("upscale_factor")
                or upscale.get("upscale_by")
                or data.get("upscale_factor"),
                2.0,
            )
        )
        self.upscale_steps_var.set(
            self._safe_int(upscale.get("steps") or data.get("upscale_steps"), 20)
        )
        self.upscale_denoise_var.set(
            self._safe_float(
                upscale.get("denoising_strength") or data.get("upscale_denoising_strength"),
                0.35,
            )
        )
        self.upscale_sampler_var.set(
            str(upscale.get("sampler_name") or data.get("upscale_sampler_name") or "Euler a")
        )
        self.upscale_scheduler_var.set(
            str(upscale.get("scheduler") or data.get("upscale_scheduler") or "normal")
        )
        self.upscale_tile_size_var.set(self._safe_int(upscale.get("tile_size"), 0))
        self.upscale_face_restore_var.set(bool(upscale.get("face_restore", False)))
        self.upscale_face_restore_method_var.set(
            str(upscale.get("face_restore_method") or "CodeFormer")
        )

    def _collect_baseline_config_from_form(self) -> dict[str, Any]:
        img2img_cfg: dict[str, Any] = {
            "sampler_name": self.img2img_sampler_var.get().strip(),
            "steps": self._safe_int(self.img2img_steps_var.get(), 20),
            "cfg_scale": self._safe_float(self.img2img_cfg_var.get(), 7.0),
            "denoising_strength": self._safe_float(self.img2img_denoise_var.get(), 0.3),
        }
        width = self._safe_int(self.img2img_width_var.get(), 0)
        height = self._safe_int(self.img2img_height_var.get(), 0)
        if width > 0:
            img2img_cfg["width"] = width
        if height > 0:
            img2img_cfg["height"] = height

        adetailer_cfg: dict[str, Any] = {
            "adetailer_model": self.adetailer_model_var.get().strip(),
            "ad_model": self.adetailer_model_var.get().strip(),
            "adetailer_confidence": self._safe_float(self.adetailer_confidence_var.get(), 0.35),
            "ad_confidence": self._safe_float(self.adetailer_confidence_var.get(), 0.35),
            "adetailer_steps": self._safe_int(self.adetailer_steps_var.get(), 28),
            "ad_steps": self._safe_int(self.adetailer_steps_var.get(), 28),
            "adetailer_cfg": self._safe_float(self.adetailer_cfg_var.get(), 7.0),
            "ad_cfg_scale": self._safe_float(self.adetailer_cfg_var.get(), 7.0),
            "adetailer_denoise": self._safe_float(self.adetailer_denoise_var.get(), 0.4),
            "ad_denoising_strength": self._safe_float(self.adetailer_denoise_var.get(), 0.4),
            "adetailer_sampler": self.adetailer_sampler_var.get().strip(),
            "ad_sampler": self.adetailer_sampler_var.get().strip(),
            "scheduler": self.adetailer_scheduler_var.get().strip() or "Use sampler default",
            "ad_scheduler": self.adetailer_scheduler_var.get().strip() or "Use sampler default",
        }

        upscale_cfg: dict[str, Any] = {
            "upscaler": self.upscale_upscaler_var.get().strip(),
            "upscaling_resize": self._safe_float(self.upscale_factor_var.get(), 2.0),
            "upscale_factor": self._safe_float(self.upscale_factor_var.get(), 2.0),
            "steps": self._safe_int(self.upscale_steps_var.get(), 20),
            "denoising_strength": self._safe_float(self.upscale_denoise_var.get(), 0.35),
            "sampler_name": self.upscale_sampler_var.get().strip(),
            "scheduler": self.upscale_scheduler_var.get().strip() or "normal",
            "tile_size": self._safe_int(self.upscale_tile_size_var.get(), 0),
            "face_restore": bool(self.upscale_face_restore_var.get()),
            "face_restore_method": self.upscale_face_restore_method_var.get().strip() or "CodeFormer",
        }

        config: dict[str, Any] = {
            "img2img": img2img_cfg,
            "img2img_sampler_name": img2img_cfg["sampler_name"],
            "img2img_steps": img2img_cfg["steps"],
            "img2img_cfg_scale": img2img_cfg["cfg_scale"],
            "img2img_denoising_strength": img2img_cfg["denoising_strength"],
            "adetailer": adetailer_cfg,
            "adetailer_steps": adetailer_cfg["adetailer_steps"],
            "adetailer_cfg_scale": adetailer_cfg["adetailer_cfg"],
            "adetailer_sampler_name": adetailer_cfg["adetailer_sampler"],
            "adetailer_denoising_strength": adetailer_cfg["adetailer_denoise"],
            "upscale": upscale_cfg,
            "upscale_steps": upscale_cfg["steps"],
            "upscale_sampler_name": upscale_cfg["sampler_name"],
            "upscale_denoising_strength": upscale_cfg["denoising_strength"],
            "upscale_factor": upscale_cfg["upscale_factor"],
            "upscaler": upscale_cfg["upscaler"],
            "steps": img2img_cfg["steps"],
            "cfg_scale": img2img_cfg["cfg_scale"],
            "sampler_name": img2img_cfg["sampler_name"],
        }
        return config

    def _refresh_resource_options(self, resources: dict[str, list[Any]] | None = None) -> None:
        resource_map = resources
        if resource_map is None:
            resource_map = getattr(self.app_state, "resources", {}) if self.app_state is not None else {}
        model_values, model_map = self._normalize_dropdown_entries(
            self._resource_entries(resource_map, "models")
        )
        vae_values, vae_map = self._normalize_dropdown_entries(
            self._resource_entries(resource_map, "vaes"),
            include_automatic=True,
        )
        self._model_name_map = model_map
        self._vae_name_map = vae_map
        self._set_combobox_values(self.model_combo, self.model_var, model_values)
        self._set_combobox_values(self.vae_combo, self.vae_var, vae_values)

        samplers = self._resource_values("samplers")
        schedulers = self._resource_values("schedulers")
        upscalers = self._resource_values("upscalers", fallback=["Latent", "R-ESRGAN 4x+"])
        adetailer_models = self._resource_values(
            "adetailer_models",
            fallback=["face_yolov8n.pt", "hand_yolov8n.pt", "mediapipe_face_full"],
        )
        self._set_combobox_values(self.img2img_sampler_combo, self.img2img_sampler_var, samplers)
        self._set_combobox_values(self.adetailer_sampler_combo, self.adetailer_sampler_var, samplers)
        self._set_combobox_values(self.upscale_sampler_combo, self.upscale_sampler_var, samplers)
        self._set_combobox_values(
            self.adetailer_scheduler_combo,
            self.adetailer_scheduler_var,
            ["Use sampler default"] + schedulers,
        )
        self._set_combobox_values(self.upscale_scheduler_combo, self.upscale_scheduler_var, schedulers)
        self._set_combobox_values(self.upscale_upscaler_combo, self.upscale_upscaler_var, upscalers)
        self._set_combobox_values(self.adetailer_model_combo, self.adetailer_model_var, adetailer_models)

    @staticmethod
    def _resource_entries(
        resources: dict[str, list[Any]] | None,
        key: str,
    ) -> list[Any]:
        if not isinstance(resources, dict):
            return []
        return list(resources.get(key) or [])

    def _resource_values(self, key: str, *, fallback: list[str] | None = None) -> list[str]:
        resources = getattr(self.app_state, "resources", {}) if self.app_state is not None else {}
        entries = resources.get(key) if isinstance(resources, dict) else []
        values: list[str] = []
        for entry in entries or []:
            value = self._resource_entry_name(entry)
            if value:
                values.append(value)
        for item in fallback or []:
            if item and item not in values:
                values.append(item)
        return values

    @staticmethod
    def _resource_entry_name(entry: Any) -> str:
        if isinstance(entry, str):
            return entry.strip()
        if isinstance(entry, dict):
            for key in ("title", "model_name", "name", "label"):
                value = entry.get(key)
                if isinstance(value, str) and value.strip():
                    return value.strip()
            return ""
        for attr in ("display_name", "name", "title", "model_name"):
            value = getattr(entry, attr, None)
            if isinstance(value, str) and value.strip():
                return value.strip()
        return ""

    @classmethod
    def _normalize_dropdown_entries(
        cls,
        entries: list[Any],
        *,
        include_automatic: bool = False,
    ) -> tuple[list[str], dict[str, str]]:
        seen: set[str] = set()
        values: list[str] = []
        mapping: dict[str, str] = {}
        if include_automatic:
            values.append("Automatic")
            mapping["Automatic"] = ""
            seen.add("Automatic")
        for entry in entries:
            display = cls._resource_entry_name(entry)
            if not display or display in seen:
                continue
            internal = cls._resource_internal_name(entry) or display
            seen.add(display)
            values.append(display)
            mapping[display] = internal
        return values, mapping

    @staticmethod
    def _resource_internal_name(entry: Any) -> str:
        if isinstance(entry, str):
            return entry.strip()
        if isinstance(entry, dict):
            for key in ("name", "model_name", "title", "label"):
                value = entry.get(key)
                if isinstance(value, str) and value.strip():
                    return value.strip()
            return ""
        for attr in ("name", "model_name", "title", "display_name"):
            value = getattr(entry, attr, None)
            if isinstance(value, str) and value.strip():
                return value.strip()
        return ""

    @staticmethod
    def _display_for_internal(internal: str | None, mapping: dict[str, str]) -> str:
        target = str(internal or "").strip()
        if not target:
            return "Automatic" if mapping.get("Automatic", None) == "" else ""
        for display, name in mapping.items():
            if name == target:
                return display
        return target

    @staticmethod
    def _internal_for_display(display: str | None, mapping: dict[str, str]) -> str:
        text = str(display or "").strip()
        if not text:
            return ""
        return str(mapping.get(text, text)).strip()

    @staticmethod
    def _set_combobox_values(combo: ttk.Combobox, var: tk.StringVar, values: list[str]) -> None:
        current = (var.get() or "").strip()
        unique_values: list[str] = []
        for value in values:
            item = str(value or "").strip()
            if item and item not in unique_values:
                unique_values.append(item)
        if current and current not in unique_values:
            unique_values.append(current)
        combo["values"] = unique_values

    @staticmethod
    def _merge_nested_dicts(base: dict[str, Any], update: dict[str, Any]) -> dict[str, Any]:
        merged = deepcopy(base or {})
        for key, value in (update or {}).items():
            if isinstance(value, dict) and isinstance(merged.get(key), dict):
                merged[key] = PhotoOptimizeTabFrameV2._merge_nested_dicts(merged.get(key, {}), value)
            else:
                merged[key] = deepcopy(value)
        return merged

    @staticmethod
    def _safe_int(value: Any, default: int) -> int:
        try:
            return int(value)
        except (TypeError, ValueError):
            return default

    @staticmethod
    def _safe_float(value: Any, default: float) -> float:
        try:
            return float(value)
        except (TypeError, ValueError):
            return default

    def get_photo_optimize_state(self) -> dict[str, Any]:
        return {
            "selected_asset_id": self._current_asset_id,
        }

    def _on_app_state_resources_changed(self, resources: dict[str, list[Any]] | None = None) -> None:
        resource_map = resources if isinstance(resources, dict) else None
        if not bool(self.winfo_ismapped()):
            self._pending_resources_payload = resource_map
            return
        self._pending_resources_payload = None
        self._refresh_resource_options(resource_map)

    def bind_app_state(self, app_state: Any) -> None:
        if self.app_state is app_state:
            return
        old_state = self.app_state
        old_listener = self._app_state_resource_listener
        old_visibility_listener = self._app_state_visibility_listener
        if old_state is not None and old_listener is not None and hasattr(old_state, "unsubscribe"):
            try:
                old_state.unsubscribe("resources", old_listener)
            except Exception:
                pass
        if old_state is not None and old_visibility_listener is not None and hasattr(old_state, "unsubscribe"):
            try:
                old_state.unsubscribe("content_visibility_mode", old_visibility_listener)
            except Exception:
                pass
        self.app_state = app_state
        self._app_state_resource_listener = None
        self._app_state_visibility_listener = None
        if self.app_state is not None and hasattr(self.app_state, "subscribe"):
            self._app_state_resource_listener = lambda: self._on_app_state_resources_changed(
                getattr(self.app_state, "resources", None)
            )
            try:
                self.app_state.subscribe("resources", self._app_state_resource_listener)
            except Exception:
                self._app_state_resource_listener = None
            self._app_state_visibility_listener = self._on_content_visibility_mode_changed
            try:
                self.app_state.subscribe(
                    "content_visibility_mode",
                    self._app_state_visibility_listener,
                )
            except Exception:
                self._app_state_visibility_listener = None
        self._on_app_state_resources_changed(
            getattr(self.app_state, "resources", None) if self.app_state is not None else None
        )
        self.on_content_visibility_mode_changed()

    def restore_photo_optimize_state(self, payload: dict[str, Any] | None) -> bool:
        if not isinstance(payload, dict):
            return False
        selected_asset_id = payload.get("selected_asset_id")
        if selected_asset_id:
            self._restored_asset_id = str(selected_asset_id)
            self._refresh_assets(select_asset_id=self._restored_asset_id)
            return True
        return False

    def on_assets_updated(self, asset_ids: list[str] | None = None) -> None:
        target = self._current_asset_id
        if asset_ids and target not in set(asset_ids):
            target = asset_ids[0]
        if not bool(self.winfo_ismapped()):
            self._pending_asset_refresh_target = target
            return
        self._pending_asset_refresh_target = None
        self._refresh_assets(select_asset_id=target)

    def _on_map(self, _event: Any = None) -> None:
        if self._pending_resources_payload is not None:
            resources = self._pending_resources_payload
            self._pending_resources_payload = None
            self.after_idle(lambda resources=resources: self._refresh_resource_options(resources))
        if self._pending_asset_refresh_target is not None:
            target = self._pending_asset_refresh_target
            self._pending_asset_refresh_target = None
            self.after_idle(lambda target=target: self._refresh_assets(select_asset_id=target))
        if self._pending_visibility_refresh:
            self.after_idle(lambda: self.on_content_visibility_mode_changed(self._content_visibility_mode))

    def destroy(self) -> None:
        if self.app_state is not None and self._app_state_resource_listener is not None and hasattr(
            self.app_state, "unsubscribe"
        ):
            try:
                self.app_state.unsubscribe("resources", self._app_state_resource_listener)
            except Exception:
                pass
        if self.app_state is not None and self._app_state_visibility_listener is not None and hasattr(
            self.app_state, "unsubscribe"
        ):
            try:
                self.app_state.unsubscribe("content_visibility_mode", self._app_state_visibility_listener)
            except Exception:
                pass
        self._app_state_resource_listener = None
        self._app_state_visibility_listener = None
        super().destroy()


PhotoOptimizeTabFrame = PhotoOptimizeTabFrameV2
