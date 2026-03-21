from __future__ import annotations

import tkinter as tk
from pathlib import Path
from tkinter import filedialog, messagebox, ttk
from typing import Any

from src.gui.controllers.review_workflow_adapter import ReviewWorkflowAdapter
from src.gui.tooltip import attach_tooltip
from src.gui.ui_tokens import TOKENS
from src.gui.widgets.thumbnail_widget_v2 import ThumbnailWidget
from src.utils.image_metadata import (
    extract_embedded_metadata,
    resolve_model_vae_fields,
    resolve_prompt_fields,
)


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
        self._feedback_undo_stack: list[list[dict[str, str]]] = []
        self._selected_base_prompt = ""
        self._selected_base_negative_prompt = ""
        self._selected_image_path: Path | None = None

        self.columnconfigure(0, weight=1)
        self.rowconfigure(1, weight=1)

        self._build_header()
        self._build_body()
        self._build_controls()

        self.prompt_mode_var.trace_add("write", lambda *_: self._on_prompt_mode_changed())
        self.negative_mode_var.trace_add("write", lambda *_: self._on_negative_mode_changed())
        self.prompt_text.bind("<KeyRelease>", lambda _e: self._refresh_prompt_diff())
        self.negative_text.bind("<KeyRelease>", lambda _e: self._refresh_prompt_diff())
        self._set_readonly_text(self.current_prompt_text, "")
        self._set_readonly_text(self.current_negative_text, "")
        self._sync_edit_box_to_mode("prompt")
        self._sync_edit_box_to_mode("negative")
        self._refresh_prompt_diff()

    def _build_header(self) -> None:
        header = ttk.Frame(self, style="Panel.TFrame", padding=8)
        header.grid(row=0, column=0, sticky="ew", padx=6, pady=(6, 4))
        header.columnconfigure(3, weight=1)

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

        self.selection_label = ttk.Label(
            header,
            text="No images selected",
            style="Dark.TLabel",
        )
        self.selection_label.grid(row=0, column=3, sticky="e")

        self.workflow_hint_label = ttk.Label(
            header,
            text="Review is the canonical advanced reprocess workspace.",
            style="Dark.TLabel",
        )
        self.workflow_hint_label.grid(row=1, column=0, columnspan=4, sticky="w", pady=(6, 0))

    def _build_body(self) -> None:
        body = ttk.Frame(self, style="Panel.TFrame")
        body.grid(row=1, column=0, sticky="nsew", padx=6, pady=4)
        body.columnconfigure(0, weight=1, uniform="review")
        body.columnconfigure(1, weight=1, uniform="review")
        body.rowconfigure(0, weight=1)

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
        self.images_list.grid(row=0, column=0, sticky="nsew")
        self.images_list.bind("<<ListboxSelect>>", self._on_image_select)

        list_scroll = ttk.Scrollbar(left, orient="vertical", command=self.images_list.yview)
        list_scroll.grid(row=0, column=1, sticky="ns")
        self.images_list.configure(yscrollcommand=list_scroll.set)

        right = ttk.LabelFrame(body, text="Preview & Metadata", style="Dark.TLabelframe", padding=8)
        right.grid(row=0, column=1, sticky="nsew")
        right.columnconfigure(0, weight=1)

        self.preview = ThumbnailWidget(right, width=420, height=420, placeholder_text="Select an image")
        self.preview.grid(row=0, column=0, sticky="n", pady=(0, 8))

        self.meta_label = ttk.Label(
            right,
            text="Metadata: n/a",
            style="Dark.TLabel",
            justify="left",
            wraplength=420,
        )
        self.meta_label.grid(row=1, column=0, sticky="ew")

    def _build_controls(self) -> None:
        controls = ttk.Frame(self, style="Panel.TFrame")
        controls.grid(row=2, column=0, sticky="ew", padx=6, pady=(4, 6))
        controls.columnconfigure(0, weight=1)
        controls.columnconfigure(1, weight=1)

        prompt_box = ttk.LabelFrame(
            controls,
            text="Current Prompts + Edits",
            style="Dark.TLabelframe",
            padding=8,
        )
        prompt_box.grid(row=0, column=0, sticky="nsew", padx=(0, 6))
        prompt_box.columnconfigure(1, weight=1)
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

        batch_row = ttk.Frame(run_box, style="Panel.TFrame")
        batch_row.grid(row=3, column=0, sticky="ew", pady=(0, 8))
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

        ttk.Button(
            run_box,
            text="Reprocess Selected",
            style="Primary.TButton",
            command=lambda: self._reprocess(batch_all=False),
        ).grid(row=4, column=0, sticky="ew", pady=(0, 6))

        ttk.Button(
            run_box,
            text="Reprocess All",
            style="Dark.TButton",
            command=lambda: self._reprocess(batch_all=True),
        ).grid(row=5, column=0, sticky="ew")

        feedback_box = ttk.LabelFrame(
            run_box,
            text="Review Feedback",
            style="Dark.TLabelframe",
            padding=8,
        )
        feedback_box.grid(row=6, column=0, sticky="ew", pady=(8, 0))
        feedback_box.columnconfigure(1, weight=1)
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
        self._set_readonly_text(self.current_prompt_text, "")
        self._set_readonly_text(self.current_negative_text, "")
        self._refresh_prompt_diff()
        self.preview.clear()

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
        result = extract_embedded_metadata(path)
        if result.status != "ok" or not isinstance(result.payload, dict):
            self.meta_label.config(text=f"Metadata: {result.status}")
            self._selected_base_prompt = ""
            self._selected_base_negative_prompt = ""
            self._reset_mode_edits_for_current_image()
            self._set_readonly_text(self.current_prompt_text, "")
            self._set_readonly_text(self.current_negative_text, "")
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
        self._set_readonly_text(self.current_prompt_text, self._selected_base_prompt)
        self._set_readonly_text(self.current_negative_text, self._selected_base_negative_prompt)
        self._refresh_prompt_diff()
        self.meta_label.config(
            text=(
                f"Metadata: ok | model={model or 'n/a'} | vae={vae or 'n/a'}\n"
                f"Prompt: {preview_prompt or '(empty)'}"
            )
        )

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
        self.diff_before_label.config(text=diff.before_text)
        self.diff_after_label.config(text=diff.after_text)

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
                submitted = handler(
                    image_paths=[str(p) for p in targets],
                    stages=stages,
                    prompt_delta=prompt_delta,
                    negative_prompt_delta=negative_delta,
                    prompt_mode=self.prompt_mode_var.get(),
                    negative_prompt_mode=self.negative_mode_var.get(),
                    batch_size=batch_size,
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
