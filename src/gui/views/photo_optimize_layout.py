"""Photo Optimize presentation builders, extracted from the tab without new execution authority."""
from __future__ import annotations

import tkinter as tk
from collections.abc import Sequence
from tkinter import font as tkfont
from tkinter import ttk
from typing import cast

from src.gui.tooltip import attach_tooltip
from src.gui.ui_tokens import TOKENS
from src.gui.view_contracts.photo_optimize_layout_contract import (
    BODY_SPLIT,
    BODY_STACKED,
    BODY_WIDE,
    HEADER_GAP,
    HEADER_ROW_GAP,
    PREVIEW_MAX_EDGE,
    PREVIEW_MIN_EDGE,
    REGION_GUTTER,
    body_column_minsizes,
    body_column_weights,
    body_placements,
    choose_body_mode,
    flow_rows,
    region_minimums,
    selection_summary,
)
from src.gui.view_contracts.workspace_density_contract import disclosure_title, wrap_width
from src.gui.widgets.scrollable_frame_v2 import ScrollableFrame
from src.gui.widgets.thumbnail_widget_v2 import ThumbnailWidget

from .photo_optimize_editors import PhotoBatchEditor

_ACTIVE_NAME_MAX = 32
ROW_GAP = HEADER_ROW_GAP


class PhotoOptimizeLayoutMixin:
    """Builds and re-grids the tab. Layout changes only call ``grid`` on existing widgets, so typed text,
    selections and baselines are never recreated or reparented by a resize."""

    assets_frame: ttk.LabelFrame
    preview_frame: ttk.LabelFrame
    controls_frame: ttk.Frame
    body_mode: str | None = None

    # -- header ----------------------------------------------------------------------------------------------------

    def _build_header(self) -> None:
        host = cast(tk.Misc, self)  # the mixin is only ever composed into a ttk.Frame
        header = ttk.Frame(host, style="Panel.TFrame", padding=8)
        header.grid(row=0, column=0, sticky="ew", padx=6, pady=(6, 4))
        header.columnconfigure(0, weight=1)
        self.header_frame = header
        self._flow_signatures: dict[str, object] = {}
        self.header_more_var = tk.BooleanVar(master=host, value=False)

        primary = ttk.Frame(header, style="Panel.TFrame")
        primary.grid(row=0, column=0, sticky="ew")
        self.header_primary = primary
        self.import_photos_btn = ttk.Button(
            primary, text="Import Photos", style="Dark.TButton", command=self._on_import_photos
        )
        self.optimize_selected_header_btn = ttk.Button(
            primary,
            text="Review Selected…",
            style="Primary.TButton",
            command=lambda: self._optimize(batch_all=False),
        )
        self.optimize_all_header_btn = ttk.Button(
            primary,
            text="Review All Visible (unarchived)…",
            style="Dark.TButton",
            command=lambda: self._optimize(batch_all=True),
        )
        self.header_more_btn = ttk.Button(
            primary, text=self._more_title(), style="Dark.TButton", command=self._toggle_header_more
        )
        attach_tooltip(
            self.header_more_btn,
            "Refresh, Review Pipeline Copy, Interrogate, batch size and legacy-migration actions.",
        )
        self.selection_label = ttk.Label(primary, text="No assets loaded", style="Dark.TLabel")
        self._primary_flow = [
            self.import_photos_btn,
            self.optimize_selected_header_btn,
            self.optimize_all_header_btn,
            self.header_more_btn,
            self.selection_label,
        ]

        self.visibility_banner = ttk.Label(header, text="", style="Dark.TLabel")
        migration_var = self.__dict__["migration_status_var"]
        self._migration_status_var = migration_var
        self.submission_summary_label = ttk.Label(
            header,
            textvariable=self.__dict__["submission_summary_var"],
            style="Dark.TLabel",
            justify="left",
        )
        self.submission_summary_label.grid(row=1, column=0, sticky="ew", pady=(6, 0))
        self.migration_status_label = ttk.Label(
            header, textvariable=migration_var, style="Dark.TLabel", justify="left"
        )
        self.migration_status_label.grid(row=2, column=0, sticky="ew", pady=(4, 0))
        self.header_status_labels = (self.submission_summary_label, self.migration_status_label)

        secondary = ttk.LabelFrame(header, text="More actions", style="Dark.TLabelframe", padding=6)
        self.header_secondary = secondary  # gridded into row 3 only while expanded
        secondary.columnconfigure(0, weight=1)
        flow = ttk.Frame(secondary, style="Panel.TFrame")
        flow.grid(row=0, column=0, sticky="ew")
        self.header_secondary_flow = flow
        self.refresh_btn = ttk.Button(
            flow, text="Refresh", style="Dark.TButton", command=self._refresh_assets
        )
        self.pipeline_copy_btn = ttk.Button(
            flow,
            text="Review Pipeline Copy (editing scope)…",
            style="Dark.TButton",
            command=self._use_current_pipeline_settings,
        )
        self.interrogate_btn = ttk.Button(
            flow,
            text="Interrogate",
            style="Dark.TButton",
            command=self._interrogate_current_asset,
        )
        attach_tooltip(
            self.interrogate_btn,
            "Analyze the current working image and write the returned caption into the baseline prompt.",
        )
        batch_box = ttk.Frame(flow, style="Panel.TFrame")
        ttk.Label(batch_box, text="Max photos / compatible job", style="Dark.TLabel").pack(
            side="left", padx=(0, 4)
        )
        self.batch_size_spin = ttk.Spinbox(
            batch_box,
            from_=1,
            to=64,
            increment=1,
            textvariable=self.batch_size_var,
            width=5,
            style="Dark.TSpinbox",
        )
        self.batch_size_spin.pack(side="left")
        self.migration_details_btn = ttk.Button(
            flow,
            text="Migration Details",
            style="Dark.TButton",
            command=self._show_migration_details,
        )
        self.retry_migration_btn = ttk.Button(
            flow,
            text="Retry Legacy Migration",
            style="Dark.TButton",
            command=self._retry_legacy_migration,
        )
        self._secondary_flow = [
            self.refresh_btn,
            self.pipeline_copy_btn,
            self.interrogate_btn,
            batch_box,
            self.migration_details_btn,
            self.retry_migration_btn,
        ]

        primary.bind("<Configure>", lambda _e: self._reflow_header(), add="+")
        flow.bind("<Configure>", lambda _e: self._reflow_header(), add="+")
        header.bind("<Configure>", lambda _e: self._update_header_wraps(), add="+")
        migration_var.trace_add("write", lambda *_: self._on_migration_status_changed())
        self._reflow_header()

    def _more_title(self) -> str:
        expanded = bool(self.header_more_var.get())
        return disclosure_title("More actions", expanded=expanded)

    def _toggle_header_more(self) -> None:
        self._set_header_more(not self.header_more_var.get())

    def _set_header_more(self, expanded: bool) -> None:
        self.header_more_var.set(bool(expanded))
        self.header_more_btn.configure(text=self._more_title())
        if expanded:
            self.header_secondary.grid(row=3, column=0, sticky="ew", pady=(6, 0))
        else:
            self.header_secondary.grid_remove()
        self._reflow_header()

    def _on_migration_status_changed(self) -> None:
        # A failed legacy migration must keep Retry/Details one glance away, not behind a collapsed section.
        report = getattr(self.__dict__.get("store"), "migration_report", None)
        if getattr(report, "failures", None) and not self.header_more_var.get():
            self._set_header_more(True)

    def _reflow_header(self) -> None:
        self._flow("primary", self.header_primary, self._primary_flow)
        self._flow("secondary", self.header_secondary_flow, self._secondary_flow)

    def _flow(self, key: str, container: ttk.Frame, children: Sequence[tk.Widget]) -> None:
        """Wrap ``children`` into rows that fit ``container``.

        Children are ``place``d (grid would tie one row's column widths to another row's items) and the container
        is given the resulting height. Re-placed only when the rows or any item width changed.
        """

        widths = [child.winfo_reqwidth() for child in children]
        rows = flow_rows(widths, container.winfo_width(), gap=HEADER_GAP)
        signature = (tuple(tuple(row) for row in rows), tuple(widths))
        if self._flow_signatures.get(key) == signature:
            return
        self._flow_signatures[key] = signature
        y = 0
        for items in rows:
            x = 0
            row_height = max(children[index].winfo_reqheight() for index in items)
            for index in items:
                children[index].place(x=x, y=y)
                x += widths[index] + HEADER_GAP
            y += row_height + ROW_GAP
        container.configure(height=max(1, y - ROW_GAP))

    def _update_header_wraps(self) -> None:
        width = wrap_width(self.header_frame.winfo_width(), margin=32)
        for label in self.header_status_labels:
            if int(label.cget("wraplength") or 0) != width:
                label.configure(wraplength=width)
        self._reflow_header()

    def _bind_wrap(self, label: ttk.Label, container: tk.Misc, *, margin: int = 32) -> None:
        """Keep ``label``'s wraplength tied to the width its container was actually given."""

        def update(_event: tk.Event | None = None) -> None:
            width = wrap_width(container.winfo_width(), margin=margin)
            if int(label.cget("wraplength") or 0) != width:
                label.configure(wraplength=width)

        container.bind("<Configure>", update, add="+")
        update()

    def _update_selection_summary(self) -> None:
        """Header text saying which photo Single Photo edits and how many photos form the batch."""

        try:
            current = self.__dict__.get("_current_asset")
            name = getattr(current, "source_filename", None)
            if name and len(name) > _ACTIVE_NAME_MAX:
                name = name[: _ACTIVE_NAME_MAX - 1] + "…"
            listbox = self.__dict__["assets_list"]
            rows = len(self.__dict__["_asset_index_by_row"])
            archived = sum(1 for label in listbox.get(0, tk.END) if str(label).startswith("[Archived]"))
            text = selection_summary(
                visible=rows - archived,
                selected=len(listbox.curselection()),
                active_name=name,
                archived=archived,
            )
            self.selection_label.config(text=text)
            self._reflow_header()
        except (AttributeError, KeyError, tk.TclError):
            return

    # -- body ------------------------------------------------------------------------------------------------------

    def _layout_char_width(self) -> int:
        """Width of "0" in the font the labels really use (follows Tk scaling), the unit of every region floor."""

        cached = self.__dict__.get("_char_width_cache")
        if isinstance(cached, int) and cached:
            return cached
        try:
            host = cast(tk.Misc, self)
            spec = ttk.Style(host).lookup("Dark.TLabel", "font")
            width = int(tkfont.Font(root=host, font=spec or "TkDefaultFont").measure("0"))
        except (tk.TclError, RuntimeError):
            return 7  # not measurable yet: do not cache the fallback
        width = max(1, width)
        if spec:  # the theme font is known; a pre-theme default measurement must not stick
            self._char_width_cache = width
        return width

    def _on_body_configure(self, _event: tk.Event | None = None) -> None:
        width = self.body_scroll.viewport_width()
        if width <= 1:
            return
        mode = choose_body_mode(width, region_minimums(self._layout_char_width()))
        if mode != self.body_mode:
            self._apply_body_layout(mode)

    def _apply_body_layout(self, mode: str) -> None:
        """Re-grid the three existing regions for ``mode``; nothing is created, destroyed or reparented."""

        body = self.body_scroll.inner
        minimums = region_minimums(self._layout_char_width())
        for index in range(3):
            body.columnconfigure(index, weight=0, minsize=0)
            body.rowconfigure(index, weight=0, minsize=0)
        weights = body_column_weights(mode)
        minsizes = body_column_minsizes(mode, minimums)
        for index, (weight, minsize) in enumerate(zip(weights, minsizes, strict=True)):
            body.columnconfigure(index, weight=weight, minsize=minsize)
        if mode == BODY_SPLIT:
            body.rowconfigure(2, weight=1)
        placements = body_placements(mode)
        regions = {"assets": self.assets_frame, "preview": self.preview_frame, "editor": self.controls_frame}
        last_column = len(weights) - 1
        for name, region in regions.items():
            placement = placements[name]
            right = 0 if placement.column + placement.columnspan - 1 >= last_column else REGION_GUTTER
            stacked_above = (mode == BODY_STACKED and name != "editor") or (mode == BODY_SPLIT and name == "assets")
            region.grid(
                row=placement.row,
                column=placement.column,
                rowspan=placement.rowspan,
                columnspan=placement.columnspan,
                sticky="new",
                padx=(0, right),
                pady=(0, 6 if stacked_above else 0),
            )
        self.body_mode = mode

    def _build_body(self) -> None:
        self.body_scroll = ScrollableFrame(cast(tk.Misc, self), style="Panel.TFrame")
        self.body_scroll.grid(row=1, column=0, sticky="nsew", padx=6, pady=(0, 6))
        body = self.body_scroll.inner
        self.body_mode = None

        assets_frame = ttk.LabelFrame(body, text="Assets — batch selection", style="Dark.TLabelframe", padding=8)
        self.assets_frame = assets_frame
        assets_frame.columnconfigure(0, weight=1)
        assets_frame.rowconfigure(0, weight=1)

        self.assets_list = tk.Listbox(
            assets_frame,
            height=12,
            width=24,
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
        self.assets_actions_frame = list_controls
        list_controls.grid(row=1, column=0, columnspan=2, sticky="ew", pady=(6, 0))
        ttk.Label(list_controls, text="Active Single Photo", style="Dark.TLabel").pack(anchor="w")
        self.active_photo_combo = ttk.Combobox(list_controls, state="readonly", style="Dark.TCombobox")
        self.active_photo_combo.pack(fill="x")
        self.active_photo_combo.bind("<<ComboboxSelected>>", self._on_active_photo_choice)
        active_note = ttk.Label(list_controls, text="Changes editor only; batch highlights stay.",
                                style="Dark.TLabel", wraplength=240)
        active_note.pack(anchor="w", pady=(0, 6))
        self._bind_wrap(active_note, assets_frame, margin=40)
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
        preview_frame.columnconfigure(0, weight=1)

        self.image_previews_frame = ttk.Frame(preview_frame, style="Panel.TFrame")
        self.image_previews_frame.grid(row=0, column=0, sticky="new")
        self.image_previews_frame.columnconfigure(0, weight=1, uniform="photo_thumbs")
        self.image_previews_frame.columnconfigure(1, weight=1, uniform="photo_thumbs")

        ttk.Label(self.image_previews_frame, text="Original", style="Dark.TLabel").grid(
            row=0, column=0, sticky="w", pady=(0, 4)
        )
        ttk.Label(self.image_previews_frame, text="Selected candidate (preview only)", style="Dark.TLabel").grid(
            row=0, column=1, sticky="w", pady=(0, 4)
        )
        self.original_preview = ThumbnailWidget(
            self.image_previews_frame,
            width=PREVIEW_MAX_EDGE,
            height=PREVIEW_MAX_EDGE,
            placeholder_text="Import a photo",
            responsive=True,
            min_edge=PREVIEW_MIN_EDGE,
        )
        self.original_preview.grid(row=1, column=0, sticky="new", padx=(0, 6))
        self.latest_preview = ThumbnailWidget(
            self.image_previews_frame,
            width=PREVIEW_MAX_EDGE,
            height=PREVIEW_MAX_EDGE,
            placeholder_text="No optimize output yet",
            responsive=True,
            min_edge=PREVIEW_MIN_EDGE,
        )
        self.latest_preview.grid(row=1, column=1, sticky="new")

        self.meta_label = ttk.Label(
            preview_frame,
            text="Metadata: n/a",
            style="Dark.TLabel",
            justify="left",
            wraplength=460,
        )
        self.meta_label.grid(row=1, column=0, sticky="ew", pady=(8, 0))
        self._bind_wrap(self.meta_label, preview_frame)

        controls = ttk.Frame(body, style="Panel.TFrame")
        self.controls_frame = controls
        controls.columnconfigure(0, weight=1)

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
            width=24,
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
            width=24,
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
        settings_error = ttk.Label(baseline_box, textvariable=self.settings_error_var, style="Dark.TLabel",
                                   wraplength=420)
        settings_error.grid(row=12, column=0, sticky="ew")
        self._bind_wrap(settings_error, baseline_box, margin=24)
        save_status = ttk.Label(baseline_box, textvariable=self.baseline_save_status_var,
                                style="Dark.TLabel", wraplength=420)
        save_status.grid(row=13, column=0, sticky="ew")
        self._bind_wrap(save_status, baseline_box, margin=24)

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
            width=24,
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
        optimize_box.grid(row=1, column=0, sticky="new", pady=(0, 6))
        optimize_box.columnconfigure(1, weight=1)

        ttk.Label(optimize_box, text="Saved positive prompt for active photo", style="Dark.TLabel").grid(
            row=0, column=0, columnspan=2, sticky="w", pady=(0, 4)
        )
        self.current_prompt_text = tk.Text(
            optimize_box,
            width=24,
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
            width=24,
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
            width=24,
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
            width=24,
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
        self._bind_wrap(self.diff_before_label, diff_box, margin=24)
        self.diff_before_label.grid_remove()  # saved prompts are shown directly above; avoid a third copy
        self.diff_after_label = ttk.Label(
            diff_box,
            text="After: (no changes)",
            style="Dark.TLabel",
            justify="left",
            wraplength=460,
        )
        self.diff_after_label.grid(row=1, column=0, sticky="ew")
        self._bind_wrap(self.diff_after_label, diff_box, margin=24)

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
            text="Original, Working Baseline and Recorded Results",
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
            text="Use Selected Result as Working Baseline…",
            style="Dark.TButton",
            command=self._promote_selected_result,
        ).pack(side="left", fill="x", expand=True, padx=(0, 4))
        ttk.Button(
            actions,
            text="Restore Previous Baseline",
            style="Dark.TButton",
            command=self._revert_baseline,
        ).pack(side="left", fill="x", expand=True)
        ttk.Radiobutton(history_box, text="Image + recorded prompt/settings", variable=self.promotion_mode_var,
                        value="recorded").grid(row=2, column=0, sticky="w")
        ttk.Radiobutton(history_box, text="Image only + retain current prompt/settings", variable=self.promotion_mode_var,
                        value="image_only").grid(row=3, column=0, sticky="w")
        result_status = ttk.Label(history_box, textvariable=self.result_status_var, wraplength=460,
                                  style="Dark.TLabel")
        result_status.grid(row=4, column=0, columnspan=2, sticky="ew")
        self._bind_wrap(result_status, history_box, margin=24)

        body.bind("<Configure>", self._on_body_configure, add="+")
        self._apply_body_layout(BODY_WIDE)


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
