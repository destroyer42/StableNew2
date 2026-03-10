from __future__ import annotations

import tkinter as tk
from copy import deepcopy
from pathlib import Path
from tkinter import filedialog, messagebox, ttk
from typing import Any

from src.gui.controllers.review_workflow_adapter import ReviewWorkflowAdapter
from src.gui.tooltip import attach_tooltip
from src.gui.ui_tokens import TOKENS
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
        self.app_state = app_state
        self.store = store or get_photo_optimize_store()
        self._workflow_adapter = ReviewWorkflowAdapter()
        self._asset_index_by_row: list[str] = []
        self._current_asset_id: str | None = None
        self._current_asset: PhotoOptimizeAsset | None = None
        self._restored_asset_id: str | None = None
        self._history_index_by_row: list[int] = []
        self._suspend_asset_persist = False

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

        self.columnconfigure(0, weight=1)
        self.rowconfigure(1, weight=1)

        self._build_header()
        self._build_body()

        self.prompt_mode_var.trace_add("write", lambda *_: self._on_prompt_mode_changed())
        self.negative_mode_var.trace_add("write", lambda *_: self._on_negative_mode_changed())
        for variable in (
            self.model_var,
            self.vae_var,
            self.tags_var,
            self.stage_img2img_var,
            self.stage_adetailer_var,
            self.stage_upscale_var,
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

        self._set_readonly_text(self.current_prompt_text, "")
        self._set_readonly_text(self.current_negative_text, "")
        self._refresh_assets()

    def _build_header(self) -> None:
        header = ttk.Frame(self, style="Panel.TFrame", padding=8)
        header.grid(row=0, column=0, sticky="ew", padx=6, pady=(6, 4))
        header.columnconfigure(4, weight=1)

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
            command=self._show_interrogate_unavailable,
        )
        interrogate_btn.grid(row=0, column=3, sticky="w")
        attach_tooltip(
            interrogate_btn,
            "Prompt interrogation is not wired in this MVP. Import, set a baseline, then optimize.",
        )

        self.selection_label = ttk.Label(
            header,
            text="No assets loaded",
            style="Dark.TLabel",
        )
        self.selection_label.grid(row=0, column=4, sticky="e")

    def _build_body(self) -> None:
        body = ttk.Frame(self, style="Panel.TFrame")
        body.grid(row=1, column=0, sticky="nsew", padx=6, pady=(0, 6))
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
            width=280,
            height=280,
            placeholder_text="Import a photo",
        )
        self.original_preview.grid(row=1, column=0, sticky="nsew", padx=(0, 6))
        self.latest_preview = ThumbnailWidget(
            preview_frame,
            width=280,
            height=280,
            placeholder_text="No optimize output yet",
        )
        self.latest_preview.grid(row=1, column=1, sticky="nsew")

        self.meta_label = ttk.Label(
            preview_frame,
            text="Metadata: n/a",
            style="Dark.TLabel",
            justify="left",
            wraplength=560,
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
        ttk.Entry(model_row, textvariable=self.model_var, style="Dark.TEntry").grid(
            row=0, column=1, sticky="ew", padx=(0, 8)
        )
        ttk.Label(model_row, text="VAE", style="Dark.TLabel").grid(row=0, column=2, sticky="w", padx=(0, 6))
        ttk.Entry(model_row, textvariable=self.vae_var, style="Dark.TEntry").grid(row=0, column=3, sticky="ew")

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

        ttk.Label(baseline_box, text="Tags (comma-separated)", style="Dark.TLabel").grid(
            row=6, column=0, sticky="w", pady=(0, 4)
        )
        ttk.Entry(baseline_box, textvariable=self.tags_var, style="Dark.TEntry").grid(
            row=7, column=0, sticky="ew", pady=(0, 8)
        )

        ttk.Label(baseline_box, text="Notes", style="Dark.TLabel").grid(
            row=8, column=0, sticky="w", pady=(0, 4)
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
        self.notes_text.grid(row=9, column=0, sticky="ew")

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
        self._set_readonly_text(self.current_prompt_text, "")
        self._set_readonly_text(self.current_negative_text, "")
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
            self._set_text(self.baseline_prompt_text, asset.baseline.prompt)
            self._set_text(self.baseline_negative_text, asset.baseline.negative_prompt)
            self._set_text(self.notes_text, asset.notes)
            self.model_var.set(asset.baseline.model)
            self.vae_var.set(asset.baseline.vae)
            self.tags_var.set(", ".join(asset.tags))
            self.stage_img2img_var.set(bool(asset.baseline.stage_defaults.get("img2img", True)))
            self.stage_adetailer_var.set(bool(asset.baseline.stage_defaults.get("adetailer", False)))
            self.stage_upscale_var.set(bool(asset.baseline.stage_defaults.get("upscale", False)))
            self._set_readonly_text(self.current_prompt_text, asset.baseline.prompt)
            self._set_readonly_text(self.current_negative_text, asset.baseline.negative_prompt)
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
        baseline.model = self.model_var.get().strip()
        baseline.vae = self.vae_var.get().strip()
        baseline.stage_defaults = {
            "img2img": bool(self.stage_img2img_var.get()),
            "adetailer": bool(self.stage_adetailer_var.get()),
            "upscale": bool(self.stage_upscale_var.get()),
        }
        if not baseline.working_image_path:
            baseline.working_image_path = asset.managed_original_path
        updated = self.store.update_asset_fields(
            asset.asset_id,
            notes=self._get_text(self.notes_text),
            tags=[item.strip() for item in self.tags_var.get().split(",") if item.strip()],
            baseline=baseline,
        )
        self._current_asset = updated
        self._set_readonly_text(self.current_prompt_text, updated.baseline.prompt)
        self._set_readonly_text(self.current_negative_text, updated.baseline.negative_prompt)
        self._refresh_prompt_diff()
        self._refresh_preview(updated)

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
        self.diff_before_label.config(text=diff.before_text)
        self.diff_after_label.config(text=diff.after_text)

    def _set_readonly_text(self, widget: tk.Text, value: str) -> None:
        widget.configure(state="normal")
        widget.delete("1.0", tk.END)
        widget.insert("1.0", value or "")
        widget.configure(state="disabled")

    def _set_text(self, widget: tk.Text, value: str) -> None:
        widget.delete("1.0", tk.END)
        widget.insert("1.0", value or "")

    def _get_text(self, widget: tk.Text) -> str:
        return widget.get("1.0", tk.END).strip()

    def get_photo_optimize_state(self) -> dict[str, Any]:
        return {
            "selected_asset_id": self._current_asset_id,
        }

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
        self._refresh_assets(select_asset_id=target)


PhotoOptimizeTabFrame = PhotoOptimizeTabFrameV2
