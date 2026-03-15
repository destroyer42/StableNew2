from __future__ import annotations

import logging
import tkinter as tk
from datetime import datetime
from pathlib import Path
from tkinter import filedialog, messagebox, ttk
from typing import Any

from src.gui.widgets.thumbnail_widget_v2 import ThumbnailWidget
from src.state.output_routing import OUTPUT_ROUTE_SVD, OUTPUT_ROUTE_TESTING
from src.video.svd_models import get_default_svd_model_id, get_supported_svd_models

logger = logging.getLogger(__name__)

_IMAGE_FILETYPES = [
    ("PNG files", "*.png"),
    ("Image files", "*.png *.jpg *.jpeg *.webp *.bmp *.tiff *.tif"),
    ("All files", "*.*"),
]
_TARGET_PRESETS: dict[str, tuple[int, int]] = {
    "Landscape 1024x576": (1024, 576),
    "Portrait 576x1024": (576, 1024),
}
_RESIZE_MODES = ("letterbox", "center_crop", "contain_then_crop")
_OUTPUT_FORMATS = ("mp4", "gif", "frames")
_FACE_RESTORE_METHODS = ("CodeFormer", "GFPGAN")
_DEFAULT_TARGET_PRESET = "Landscape 1024x576"
_DEFAULT_SVD_PRESET = "Quality 25f MP4"
_SVD_OUTPUT_ROUTES = (OUTPUT_ROUTE_SVD, OUTPUT_ROUTE_TESTING)
_SVD_PRESETS: dict[str, dict[str, Any]] = {
    "Quality 25f MP4": {
        "frames": 25,
        "fps": 7,
        "output_format": "mp4",
        "save_frames": False,
        "num_inference_steps": 30,
        "decode_chunk_size": 8,
        "motion_bucket": 72,
        "noise_aug": 0.02,
    },
    "Subtle Motion / Realism": {
        "frames": 25,
        "fps": 7,
        "output_format": "mp4",
        "save_frames": False,
        "num_inference_steps": 35,
        "decode_chunk_size": 8,
        "motion_bucket": 48,
        "noise_aug": 0.01,
        "resize_mode": "center_crop",
    },
    "Short 14f MP4": {
        "frames": 14,
        "fps": 7,
        "output_format": "mp4",
        "save_frames": False,
        "num_inference_steps": 28,
        "decode_chunk_size": 8,
        "motion_bucket": 64,
        "noise_aug": 0.02,
    },
    "GIF Preview": {
        "frames": 14,
        "fps": 8,
        "output_format": "gif",
        "save_frames": False,
        "num_inference_steps": 25,
        "decode_chunk_size": 4,
        "motion_bucket": 110,
        "noise_aug": 0.05,
    },
    "More Motion / Stylized": {
        "frames": 25,
        "fps": 7,
        "output_format": "mp4",
        "save_frames": False,
        "num_inference_steps": 25,
        "decode_chunk_size": 4,
        "motion_bucket": 140,
        "noise_aug": 0.06,
    },
    "Frames Only": {
        "frames": 25,
        "fps": 7,
        "output_format": "frames",
        "save_frames": True,
        "num_inference_steps": 30,
        "decode_chunk_size": 8,
        "motion_bucket": 72,
        "noise_aug": 0.02,
    },
}


class SVDTabFrameV2(ttk.Frame):
    """Standalone native SVD submission tab."""

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
        self._last_folder = ""
        self._status_text = ""
        self._capability_text = ""
        self._recent_runs_by_item: dict[str, dict[str, Any]] = {}
        self._recent_selected_item: str | None = None

        model_options = self._get_model_options()
        preferred_model = get_default_svd_model_id()
        if preferred_model in model_options:
            default_model = preferred_model
        else:
            default_model = model_options[0] if model_options else preferred_model

        self.source_image_var = tk.StringVar()
        self.preset_var = tk.StringVar(value=_DEFAULT_SVD_PRESET)
        self.model_var = tk.StringVar(value=default_model)
        self.frames_var = tk.IntVar(value=25)
        self.fps_var = tk.IntVar(value=7)
        self.motion_bucket_var = tk.IntVar(value=127)
        self.noise_aug_var = tk.DoubleVar(value=0.05)
        self.inference_steps_var = tk.IntVar(value=30)
        self.seed_var = tk.StringVar()
        self.target_preset_var = tk.StringVar(value=_DEFAULT_TARGET_PRESET)
        self.resize_mode_var = tk.StringVar(value="letterbox")
        self.output_format_var = tk.StringVar(value="mp4")
        self.output_route_var = tk.StringVar(value=OUTPUT_ROUTE_SVD)
        self.save_frames_var = tk.BooleanVar(value=False)
        self.cpu_offload_var = tk.BooleanVar(value=True)
        self.forward_chunking_var = tk.BooleanVar(value=True)
        self.local_files_only_var = tk.BooleanVar(value=False)
        self.decode_chunk_size_var = tk.IntVar(value=2)
        self.cache_dir_var = tk.StringVar()
        self.face_restore_enabled_var = tk.BooleanVar(value=False)
        self.face_restore_method_var = tk.StringVar(value="CodeFormer")
        self.face_restore_fidelity_var = tk.DoubleVar(value=0.7)
        self.interpolation_enabled_var = tk.BooleanVar(value=False)
        self.interpolation_multiplier_var = tk.IntVar(value=2)
        self.rife_executable_var = tk.StringVar()
        self.frame_upscale_enabled_var = tk.BooleanVar(value=False)
        self.frame_upscale_factor_var = tk.DoubleVar(value=2.0)

        self.columnconfigure(0, weight=1)
        self.rowconfigure(1, weight=1)

        self._build_header()
        self._build_body(model_options)
        self._apply_preset(_DEFAULT_SVD_PRESET, update_status=False)
        self._refresh_capabilities()
        self._refresh_summary()
        self._refresh_recent_runs()

        if app_state and hasattr(app_state, "subscribe"):
            try:
                app_state.subscribe("history_items", self._on_history_items_changed)
            except Exception:
                pass

    def _build_header(self) -> None:
        header = ttk.Frame(self, style="Panel.TFrame", padding=8)
        header.grid(row=0, column=0, sticky="ew", padx=6, pady=(6, 4))
        header.columnconfigure(1, weight=1)
        header.columnconfigure(5, weight=1)

        ttk.Label(header, text="Source Image", style="Dark.TLabel").grid(
            row=0, column=0, sticky="w", padx=(0, 6)
        )
        self.source_entry = ttk.Entry(
            header,
            textvariable=self.source_image_var,
            style="Dark.TEntry",
            width=52,
        )
        self.source_entry.grid(row=0, column=1, columnspan=3, sticky="ew", padx=(0, 6))
        ttk.Button(
            header,
            text="Browse...",
            style="Dark.TButton",
            command=self._on_browse_image,
        ).grid(row=0, column=4, sticky="w", padx=(0, 6))
        ttk.Button(
            header,
            text="Use Latest Output",
            style="Dark.TButton",
            command=self._on_use_latest_output,
        ).grid(row=0, column=5, sticky="w")

        self.status_label = ttk.Label(header, text="", style="Dark.TLabel")
        self.status_label.grid(row=1, column=0, columnspan=6, sticky="w", pady=(6, 0))

    def _build_body(self, model_options: list[str]) -> None:
        body = ttk.Frame(self, style="Panel.TFrame")
        body.grid(row=1, column=0, sticky="nsew", padx=6, pady=(0, 6))
        body.columnconfigure(0, weight=1)
        body.columnconfigure(1, weight=0)
        body.rowconfigure(0, weight=0)
        body.rowconfigure(1, weight=1)

        help_frame = ttk.LabelFrame(body, text="SVD Img2Vid", style="Dark.TLabelframe", padding=8)
        help_frame.grid(row=0, column=0, sticky="nsew", padx=(0, 6))
        help_frame.columnconfigure(0, weight=1)

        help_text = (
            "Stable Video Diffusion animates an existing still image into a short clip.\n"
            "This path is native Python and does not use A1111/WebUI generation APIs.\n"
            "Best quality usually comes from the XT model, lower motion/noise values, and a landscape hero crop."
        )
        ttk.Label(
            help_frame,
            text=help_text,
            style="Dark.TLabel",
            justify="left",
            wraplength=520,
        ).grid(row=0, column=0, sticky="nw")

        self.summary_label = ttk.Label(
            help_frame,
            text="Ready to submit a native SVD job.",
            style="Dark.TLabel",
            justify="left",
            wraplength=520,
        )
        self.summary_label.grid(row=1, column=0, sticky="nw", pady=(10, 0))
        self.capabilities_label = ttk.Label(
            help_frame,
            text="",
            style="Dark.TLabel",
            justify="left",
            wraplength=520,
        )
        self.capabilities_label.grid(row=2, column=0, sticky="nw", pady=(10, 0))

        settings = ttk.LabelFrame(body, text="Settings", style="Dark.TLabelframe", padding=8)
        settings.grid(row=0, column=1, sticky="ns")
        settings.columnconfigure(1, weight=1)

        row = 0
        self.preset_combo = self._add_combo(settings, row, "Preset", self.preset_var, list(_SVD_PRESETS.keys()))
        self.preset_combo.bind("<<ComboboxSelected>>", self._on_preset_selected)
        row += 1
        self.model_combo = self._add_combo(settings, row, "Model", self.model_var, model_options)
        row += 1
        self._add_spinbox(settings, row, "Frames", self.frames_var, from_=1, to=64)
        row += 1
        self._add_spinbox(settings, row, "FPS", self.fps_var, from_=1, to=30)
        row += 1
        self._add_spinbox(settings, row, "Motion bucket", self.motion_bucket_var, from_=0, to=255)
        row += 1
        self._add_spinbox(settings, row, "Noise aug", self.noise_aug_var, from_=0.0, to=1.0, increment=0.01)
        row += 1
        self._add_spinbox(settings, row, "Inference steps", self.inference_steps_var, from_=1, to=100)
        row += 1

        ttk.Label(settings, text="Seed", style="Dark.TLabel").grid(
            row=row, column=0, sticky="w", padx=(0, 8), pady=(0, 6)
        )
        ttk.Entry(settings, textvariable=self.seed_var, style="Dark.TEntry", width=14).grid(
            row=row, column=1, sticky="ew", pady=(0, 6)
        )
        row += 1

        self._add_combo(settings, row, "Target size", self.target_preset_var, list(_TARGET_PRESETS.keys()))
        row += 1
        self._add_combo(settings, row, "Resize mode", self.resize_mode_var, list(_RESIZE_MODES))
        row += 1
        self._add_combo(settings, row, "Output", self.output_format_var, list(_OUTPUT_FORMATS))
        row += 1
        self._add_combo(settings, row, "Route", self.output_route_var, list(_SVD_OUTPUT_ROUTES))
        row += 1
        self._add_spinbox(settings, row, "Decode chunk", self.decode_chunk_size_var, from_=1, to=16)
        row += 1

        ttk.Checkbutton(
            settings,
            text="Save frames",
            variable=self.save_frames_var,
            style="Dark.TCheckbutton",
        ).grid(row=row, column=0, columnspan=2, sticky="w", pady=(0, 4))
        row += 1
        ttk.Checkbutton(
            settings,
            text="CPU offload",
            variable=self.cpu_offload_var,
            style="Dark.TCheckbutton",
        ).grid(row=row, column=0, columnspan=2, sticky="w", pady=(0, 4))
        row += 1
        ttk.Checkbutton(
            settings,
            text="Forward chunking",
            variable=self.forward_chunking_var,
            style="Dark.TCheckbutton",
        ).grid(row=row, column=0, columnspan=2, sticky="w", pady=(0, 4))
        row += 1
        ttk.Checkbutton(
            settings,
            text="Local files only",
            variable=self.local_files_only_var,
            style="Dark.TCheckbutton",
        ).grid(row=row, column=0, columnspan=2, sticky="w", pady=(0, 8))
        row += 1

        ttk.Label(settings, text="Cache dir", style="Dark.TLabel").grid(
            row=row, column=0, sticky="w", padx=(0, 8), pady=(0, 6)
        )
        cache_frame = ttk.Frame(settings, style="Panel.TFrame")
        cache_frame.grid(row=row, column=1, sticky="ew", pady=(0, 6))
        cache_frame.columnconfigure(0, weight=1)
        self.cache_entry = ttk.Entry(cache_frame, textvariable=self.cache_dir_var, style="Dark.TEntry", width=22)
        self.cache_entry.grid(row=0, column=0, sticky="ew", padx=(0, 4))
        ttk.Button(
            cache_frame,
            text="...",
            width=3,
            style="Dark.TButton",
            command=self._on_browse_cache_dir,
        ).grid(row=0, column=1, sticky="e")
        row += 1

        ttk.Checkbutton(
            settings,
            text="Face cleanup",
            variable=self.face_restore_enabled_var,
            style="Dark.TCheckbutton",
        ).grid(row=row, column=0, columnspan=2, sticky="w", pady=(0, 4))
        row += 1
        self._add_combo(settings, row, "Face method", self.face_restore_method_var, list(_FACE_RESTORE_METHODS))
        row += 1
        self._add_spinbox(
            settings,
            row,
            "Face fidelity",
            self.face_restore_fidelity_var,
            from_=0.0,
            to=1.0,
            increment=0.05,
        )
        row += 1
        ttk.Checkbutton(
            settings,
            text="RIFE interpolate",
            variable=self.interpolation_enabled_var,
            style="Dark.TCheckbutton",
        ).grid(row=row, column=0, columnspan=2, sticky="w", pady=(0, 4))
        row += 1
        self._add_spinbox(
            settings,
            row,
            "RIFE multiplier",
            self.interpolation_multiplier_var,
            from_=2,
            to=4,
        )
        row += 1
        ttk.Label(settings, text="RIFE exe", style="Dark.TLabel").grid(
            row=row, column=0, sticky="w", padx=(0, 8), pady=(0, 6)
        )
        rife_frame = ttk.Frame(settings, style="Panel.TFrame")
        rife_frame.grid(row=row, column=1, sticky="ew", pady=(0, 6))
        rife_frame.columnconfigure(0, weight=1)
        ttk.Entry(rife_frame, textvariable=self.rife_executable_var, style="Dark.TEntry", width=22).grid(
            row=0, column=0, sticky="ew", padx=(0, 4)
        )
        ttk.Button(
            rife_frame,
            text="...",
            width=3,
            style="Dark.TButton",
            command=self._on_browse_rife_executable,
        ).grid(row=0, column=1, sticky="e")
        row += 1
        ttk.Checkbutton(
            settings,
            text="Upscale frames",
            variable=self.frame_upscale_enabled_var,
            style="Dark.TCheckbutton",
        ).grid(row=row, column=0, columnspan=2, sticky="w", pady=(0, 4))
        row += 1
        self._add_spinbox(
            settings,
            row,
            "Upscale factor",
            self.frame_upscale_factor_var,
            from_=1.0,
            to=4.0,
            increment=0.5,
        )
        row += 1

        ttk.Button(
            settings,
            text="Clear Loaded Cache",
            style="Dark.TButton",
            command=self._on_clear_model_cache,
        ).grid(row=row, column=0, columnspan=2, sticky="ew", pady=(0, 12))
        row += 1

        self.animate_btn = ttk.Button(
            settings,
            text="Animate Image",
            style="Primary.TButton",
            command=self._on_submit,
        )
        self.animate_btn.grid(row=row, column=0, columnspan=2, sticky="ew")

        recent = ttk.LabelFrame(body, text="Recent SVD Outputs", style="Dark.TLabelframe", padding=8)
        recent.grid(row=1, column=0, columnspan=2, sticky="nsew", pady=(8, 0))
        recent.columnconfigure(0, weight=1)
        recent.columnconfigure(1, weight=0)
        recent.rowconfigure(1, weight=1)

        recent_actions = ttk.Frame(recent, style="Panel.TFrame")
        recent_actions.grid(row=0, column=0, columnspan=2, sticky="ew", pady=(0, 6))
        ttk.Button(
            recent_actions,
            text="Refresh",
            style="Dark.TButton",
            command=self._refresh_recent_runs,
        ).pack(side=tk.LEFT)
        ttk.Label(
            recent_actions,
            text="Recent completed native SVD jobs from history.",
            style="Dark.TLabel",
        ).pack(side=tk.LEFT, padx=(8, 0))

        tree_frame = ttk.Frame(recent, style="Panel.TFrame")
        tree_frame.grid(row=1, column=0, sticky="nsew", padx=(0, 8))
        tree_frame.columnconfigure(0, weight=1)
        tree_frame.rowconfigure(0, weight=1)

        recent_columns = ("time", "model", "frames", "output")
        self.recent_tree = ttk.Treeview(
            tree_frame,
            columns=recent_columns,
            show="headings",
            height=8,
        )
        self.recent_tree.heading("time", text="Completed")
        self.recent_tree.heading("model", text="Model")
        self.recent_tree.heading("frames", text="Frames")
        self.recent_tree.heading("output", text="Output")
        self.recent_tree.column("time", width=150, stretch=False, anchor=tk.W)
        self.recent_tree.column("model", width=240, stretch=True, anchor=tk.W)
        self.recent_tree.column("frames", width=70, stretch=False, anchor=tk.W)
        self.recent_tree.column("output", width=260, stretch=True, anchor=tk.W)
        recent_scroll = ttk.Scrollbar(tree_frame, orient="vertical", command=self.recent_tree.yview)
        self.recent_tree.configure(yscrollcommand=recent_scroll.set)
        self.recent_tree.grid(row=0, column=0, sticky="nsew")
        recent_scroll.grid(row=0, column=1, sticky="ns")
        self.recent_tree.bind("<<TreeviewSelect>>", self._on_recent_select)
        self.recent_tree.bind("<Double-Button-1>", self._on_recent_use_source)

        details = ttk.Frame(recent, style="Panel.TFrame")
        details.grid(row=1, column=1, sticky="ns")
        details.columnconfigure(0, weight=1)
        self.recent_preview = ThumbnailWidget(
            details,
            width=240,
            height=180,
            placeholder_text="Select a recent SVD run",
        )
        self.recent_preview.grid(row=0, column=0, sticky="ew")
        self.recent_meta_label = ttk.Label(
            details,
            text="No recent SVD run selected.",
            style="Dark.TLabel",
            justify="left",
            wraplength=240,
        )
        self.recent_meta_label.grid(row=1, column=0, sticky="ew", pady=(8, 8))
        self.use_recent_btn = ttk.Button(
            details,
            text="Use Selected Source",
            style="Dark.TButton",
            command=self._on_recent_use_source,
            state=tk.DISABLED,
        )
        self.use_recent_btn.grid(row=2, column=0, sticky="ew", pady=(0, 4))
        self.open_recent_btn = ttk.Button(
            details,
            text="Open Output Folder",
            style="Dark.TButton",
            command=self._on_open_recent_output,
            state=tk.DISABLED,
        )
        self.open_recent_btn.grid(row=3, column=0, sticky="ew", pady=(0, 4))
        self.open_manifest_btn = ttk.Button(
            details,
            text="Open Manifest Folder",
            style="Dark.TButton",
            command=self._on_open_recent_manifest,
            state=tk.DISABLED,
        )
        self.open_manifest_btn.grid(row=4, column=0, sticky="ew")

    def _add_combo(
        self,
        parent: ttk.LabelFrame,
        row: int,
        label: str,
        variable: tk.Variable,
        values: list[str],
    ) -> ttk.Combobox:
        ttk.Label(parent, text=label, style="Dark.TLabel").grid(
            row=row, column=0, sticky="w", padx=(0, 8), pady=(0, 6)
        )
        combo = ttk.Combobox(
            parent,
            textvariable=variable,
            values=values,
            state="readonly",
            style="Dark.TCombobox",
            width=28,
        )
        combo.grid(row=row, column=1, sticky="ew", pady=(0, 6))
        return combo

    def _add_spinbox(
        self,
        parent: ttk.LabelFrame,
        row: int,
        label: str,
        variable: tk.Variable,
        *,
        from_: float,
        to: float,
        increment: float = 1,
    ) -> None:
        ttk.Label(parent, text=label, style="Dark.TLabel").grid(
            row=row, column=0, sticky="w", padx=(0, 8), pady=(0, 6)
        )
        ttk.Spinbox(
            parent,
            from_=from_,
            to=to,
            increment=increment,
            textvariable=variable,
            width=10,
            style="Dark.TSpinbox",
        ).grid(row=row, column=1, sticky="ew", pady=(0, 6))

    def _get_model_options(self) -> list[str]:
        controller = self.app_controller
        getter = getattr(controller, "get_supported_svd_models", None)
        if callable(getter):
            try:
                values = [str(value) for value in getter() if value]
                if values:
                    preferred = get_default_svd_model_id()
                    if preferred in values:
                        return [preferred, *[value for value in values if value != preferred]]
                    return values
            except Exception:
                logger.exception("Failed to load SVD model options from controller")
        supported = get_supported_svd_models()
        preferred = get_default_svd_model_id()
        values = list(supported.keys())
        if preferred in values:
            return [preferred, *[value for value in values if value != preferred]]
        return values

    def set_source_image_path(self, path: str | Path, *, status_message: str | None = None) -> None:
        string_path = str(path)
        self.source_image_var.set(string_path)
        try:
            self._last_folder = str(Path(string_path).parent)
        except Exception:
            pass
        self._refresh_summary(string_path)
        if status_message:
            self._set_status(status_message)

    def _on_browse_image(self) -> None:
        initial_dir = self._last_folder or None
        path = filedialog.askopenfilename(title="Select source image", initialdir=initial_dir, filetypes=_IMAGE_FILETYPES)
        if path:
            self.set_source_image_path(path, status_message=f"Selected {Path(path).name}")

    def _on_use_latest_output(self) -> None:
        controller = self.app_controller
        getter = getattr(controller, "get_latest_output_image_path", None)
        if not callable(getter):
            messagebox.showerror("Controller missing", "Latest output lookup is not connected.")
            return
        try:
            latest_path = getter()
        except Exception as exc:
            messagebox.showerror("Lookup failed", str(exc))
            return
        if not latest_path:
            messagebox.showinfo("No output found", "No recent image output is available.")
            return
        self.set_source_image_path(latest_path, status_message=f"Using latest output: {Path(latest_path).name}")

    def _on_submit(self) -> None:
        controller = self.app_controller
        handler = getattr(controller, "submit_svd_job", None)
        if not callable(handler):
            messagebox.showerror("Controller missing", "SVD controller is not connected.")
            return
        source = self.source_image_var.get().strip()
        if not source:
            messagebox.showwarning("No source image", "Select a PNG or image file first.")
            return
        try:
            job_id = handler(
                source_image_path=source,
                form_data=self._build_form_data(),
            )
            self._set_status(f"Queued SVD job {job_id} for {Path(source).name}")
            self._refresh_summary(source)
            messagebox.showinfo("Submitted", f"Queued SVD job {job_id}.")
        except Exception as exc:
            messagebox.showerror("SVD submit failed", str(exc))

    def _build_form_data(self) -> dict[str, Any]:
        target_width, target_height = _TARGET_PRESETS.get(
            self.target_preset_var.get(),
            _TARGET_PRESETS[_DEFAULT_TARGET_PRESET],
        )
        seed_text = self.seed_var.get().strip()
        seed_value = None if not seed_text else int(seed_text)
        cache_dir = self.cache_dir_var.get().strip()
        return {
            "preprocess": {
                "target_width": target_width,
                "target_height": target_height,
                "resize_mode": self.resize_mode_var.get(),
            },
            "inference": {
                "model_id": self.model_var.get(),
                "num_frames": int(self.frames_var.get()),
                "fps": int(self.fps_var.get()),
                "motion_bucket_id": int(self.motion_bucket_var.get()),
                "noise_aug_strength": float(self.noise_aug_var.get()),
                "num_inference_steps": int(self.inference_steps_var.get()),
                "decode_chunk_size": int(self.decode_chunk_size_var.get()),
                "seed": seed_value,
                "cpu_offload": bool(self.cpu_offload_var.get()),
                "forward_chunking": bool(self.forward_chunking_var.get()),
                "local_files_only": bool(self.local_files_only_var.get()),
                "cache_dir": cache_dir or None,
            },
            "pipeline": {
                "output_route": self.output_route_var.get(),
            },
            "output": {
                "output_format": self.output_format_var.get(),
                "save_frames": bool(self.save_frames_var.get()),
                "save_preview_image": True,
            },
            "postprocess": {
                "face_restore": {
                    "enabled": bool(self.face_restore_enabled_var.get()),
                    "method": self.face_restore_method_var.get(),
                    "fidelity_weight": float(self.face_restore_fidelity_var.get()),
                },
                "interpolation": {
                    "enabled": bool(self.interpolation_enabled_var.get()),
                    "multiplier": int(self.interpolation_multiplier_var.get()),
                    "executable_path": self.rife_executable_var.get().strip() or None,
                },
                "upscale": {
                    "enabled": bool(self.frame_upscale_enabled_var.get()),
                    "scale": float(self.frame_upscale_factor_var.get()),
                },
            },
        }

    def _refresh_capabilities(self) -> None:
        controller = self.app_controller
        getter = getattr(controller, "get_svd_postprocess_capabilities", None)
        if not callable(getter):
            self._capability_text = ""
            self.capabilities_label.configure(text="")
            return
        try:
            capabilities = getter(self._build_form_data())
        except Exception:
            logger.exception("Failed to load SVD postprocess capabilities from controller")
            self._capability_text = "Capabilities: unavailable"
            self.capabilities_label.configure(text=self._capability_text)
            return
        parts: list[str] = []
        for key in ("codeformer", "realesrgan", "rife", "gfpgan"):
            entry = capabilities.get(key)
            if not isinstance(entry, dict):
                continue
            name = str(entry.get("name") or key)
            status = str(entry.get("status") or "unknown")
            detail = str(entry.get("detail") or "").strip()
            parts.append(f"{name}: {status}" + (f" ({detail})" if detail else ""))
        self._capability_text = "Capabilities: " + " | ".join(parts) if parts else ""
        self.capabilities_label.configure(text=self._capability_text)

    def _refresh_summary(self, source: str | None = None) -> None:
        source_name = Path(source or self.source_image_var.get() or "").name or "No source image"
        cache_dir = self.cache_dir_var.get().strip() or "(default cache)"
        self.summary_label.configure(
            text=(
                f"Source: {source_name}\n"
                f"Preset: {self.preset_var.get()} | Frames: {int(self.frames_var.get())} at {int(self.fps_var.get())} fps | Steps: {int(self.inference_steps_var.get())}\n"
                f"Output: {self.output_format_var.get()} | Route: {self.output_route_var.get()} | Resize: {self.resize_mode_var.get()} | Cache: {cache_dir}\n"
                f"Postprocess: face={bool(self.face_restore_enabled_var.get())} | rife={bool(self.interpolation_enabled_var.get())} | upscale={bool(self.frame_upscale_enabled_var.get())}"
            )
        )

    def _set_status(self, message: str) -> None:
        self._status_text = message
        try:
            self.status_label.configure(text=message)
        except Exception:
            pass

    def _on_preset_selected(self, _event: tk.Event | None = None) -> None:
        self._apply_preset(self.preset_var.get())

    def _apply_preset(self, preset_name: str, *, update_status: bool = True) -> None:
        payload = _SVD_PRESETS.get(preset_name)
        if not payload:
            return
        self.frames_var.set(int(payload["frames"]))
        self.fps_var.set(int(payload["fps"]))
        self.output_format_var.set(str(payload["output_format"]))
        self.save_frames_var.set(bool(payload["save_frames"]))
        self.inference_steps_var.set(int(payload.get("num_inference_steps", self.inference_steps_var.get())))
        self.decode_chunk_size_var.set(int(payload["decode_chunk_size"]))
        self.motion_bucket_var.set(int(payload["motion_bucket"]))
        self.noise_aug_var.set(float(payload["noise_aug"]))
        resize_mode = payload.get("resize_mode")
        if resize_mode in _RESIZE_MODES:
            self.resize_mode_var.set(str(resize_mode))
        target_preset = payload.get("target_preset")
        if target_preset in _TARGET_PRESETS:
            self.target_preset_var.set(str(target_preset))
        self._refresh_summary()
        if update_status:
            self._set_status(f"Applied preset: {preset_name}")
        self._refresh_capabilities()

    def _on_browse_cache_dir(self) -> None:
        initial_dir = self.cache_dir_var.get().strip() or self._last_folder or None
        path = filedialog.askdirectory(title="Select SVD cache directory", initialdir=initial_dir)
        if path:
            self.cache_dir_var.set(path)
            self._refresh_summary()
            self._set_status(f"SVD cache directory set to {path}")
            self._refresh_capabilities()

    def _on_browse_rife_executable(self) -> None:
        initial_dir = self._last_folder or None
        path = filedialog.askopenfilename(
            title="Select rife-ncnn-vulkan executable",
            initialdir=initial_dir,
            filetypes=[("Executable", "*.exe"), ("All files", "*.*")],
        )
        if path:
            self.rife_executable_var.set(path)
            self._refresh_summary()
            self._set_status(f"RIFE executable set to {Path(path).name}")
            self._refresh_capabilities()

    def _on_clear_model_cache(self) -> None:
        controller = self.app_controller
        handler = getattr(controller, "clear_svd_model_cache", None)
        if not callable(handler):
            messagebox.showerror("Controller missing", "SVD cache controls are not connected.")
            return
        try:
            handler(model_id=self.model_var.get().strip() or None)
            self._set_status(f"Cleared loaded SVD cache for {self.model_var.get()}")
        except Exception as exc:
            messagebox.showerror("Clear cache failed", str(exc))

    def _on_history_items_changed(self) -> None:
        self._refresh_recent_runs()

    def _refresh_recent_runs(self) -> None:
        controller = self.app_controller
        getter = getattr(controller, "get_recent_svd_history", None)
        if callable(getter):
            try:
                records = list(getter())
            except Exception:
                logger.exception("Failed to load recent SVD history from controller")
                records = []
        else:
            records = []
        self._load_recent_runs(records)

    def _load_recent_runs(self, records: list[dict[str, Any]]) -> None:
        for item in self.recent_tree.get_children():
            self.recent_tree.delete(item)
        self._recent_runs_by_item.clear()
        self._recent_selected_item = None

        for record in records:
            output_name = Path(
                record.get("output_path")
                or record.get("video_path")
                or record.get("gif_path")
                or record.get("thumbnail_path")
                or ""
            ).name
            item_id = self.recent_tree.insert(
                "",
                "end",
                values=(
                    self._format_time(record.get("completed_at") or record.get("started_at") or record.get("created_at")),
                    self._shorten_model(record.get("model_id")),
                    record.get("frame_count") or record.get("count") or "-",
                    output_name or "-",
                ),
            )
            self._recent_runs_by_item[item_id] = record

        if self.recent_tree.get_children():
            first = self.recent_tree.get_children()[0]
            self.recent_tree.selection_set(first)
            self.recent_tree.focus(first)
            self._select_recent_item(first)
        else:
            self.recent_preview.clear()
            self.recent_meta_label.configure(text="No recent SVD runs found in history.")
            self.use_recent_btn.configure(state=tk.DISABLED)
            self.open_recent_btn.configure(state=tk.DISABLED)
            self.open_manifest_btn.configure(state=tk.DISABLED)

    def _on_recent_select(self, _event: tk.Event | None = None) -> None:
        selection = self.recent_tree.selection()
        if not selection:
            return
        self._select_recent_item(selection[0])

    def _select_recent_item(self, item_id: str) -> None:
        record = self._recent_runs_by_item.get(item_id)
        self._recent_selected_item = item_id if record else None
        if not record:
            return
        preview_path = record.get("thumbnail_path")
        if preview_path and Path(preview_path).exists():
            self.recent_preview.set_image_from_path(preview_path)
            open_target = (
                record.get("video_path")
                or record.get("gif_path")
                or record.get("output_path")
                or preview_path
            )
            self.recent_preview.set_open_target(open_target)
        else:
            self.recent_preview.clear()
        output_name = Path(record.get("output_path") or "").name or "-"
        source_name = Path(record.get("source_image_path") or "").name or "(unknown source)"
        self.recent_meta_label.configure(
            text=(
                f"Source: {source_name}\n"
                f"Output: {output_name}\n"
                f"Model: {record.get('model_id') or '-'}\n"
                f"Frames: {record.get('frame_count') or record.get('count') or '-'} | "
                f"FPS: {record.get('fps') or '-'}"
            )
        )
        self.use_recent_btn.configure(
            state=tk.NORMAL if record.get("source_image_path") else tk.DISABLED
        )
        self.open_recent_btn.configure(
            state=tk.NORMAL if record.get("output_dir") else tk.DISABLED
        )
        self.open_manifest_btn.configure(
            state=tk.NORMAL if record.get("manifest_path") else tk.DISABLED
        )

    def _current_recent_record(self) -> dict[str, Any] | None:
        if self._recent_selected_item is None:
            return None
        return self._recent_runs_by_item.get(self._recent_selected_item)

    def _on_recent_use_source(self, _event: tk.Event | None = None) -> None:
        record = self._current_recent_record()
        if not record or not record.get("source_image_path"):
            return
        self.set_source_image_path(
            record["source_image_path"],
            status_message=f"Loaded SVD source: {Path(record['source_image_path']).name}",
        )

    def _on_open_recent_output(self) -> None:
        record = self._current_recent_record()
        if not record or not record.get("output_dir"):
            return
        opener = getattr(self.app_controller, "open_path_in_file_browser", None)
        if callable(opener):
            try:
                opener(record["output_dir"])
            except Exception as exc:
                messagebox.showerror("Open output failed", str(exc))

    def _on_open_recent_manifest(self) -> None:
        record = self._current_recent_record()
        if not record or not record.get("manifest_path"):
            return
        opener = getattr(self.app_controller, "open_path_in_file_browser", None)
        if callable(opener):
            try:
                opener(record["manifest_path"])
            except Exception as exc:
                messagebox.showerror("Open manifest failed", str(exc))

    def get_svd_state(self) -> dict[str, Any]:
        return {
            "source_image_path": self.source_image_var.get(),
            "last_folder": self._last_folder,
            "preset_name": self.preset_var.get(),
            "model_id": self.model_var.get(),
            "num_frames": int(self.frames_var.get()),
            "fps": int(self.fps_var.get()),
            "motion_bucket_id": int(self.motion_bucket_var.get()),
            "noise_aug_strength": float(self.noise_aug_var.get()),
            "num_inference_steps": int(self.inference_steps_var.get()),
            "seed": self.seed_var.get(),
            "target_preset": self.target_preset_var.get(),
            "resize_mode": self.resize_mode_var.get(),
            "output_format": self.output_format_var.get(),
            "output_route": self.output_route_var.get(),
            "save_frames": bool(self.save_frames_var.get()),
            "cpu_offload": bool(self.cpu_offload_var.get()),
            "forward_chunking": bool(self.forward_chunking_var.get()),
            "local_files_only": bool(self.local_files_only_var.get()),
            "decode_chunk_size": int(self.decode_chunk_size_var.get()),
            "cache_dir": self.cache_dir_var.get(),
            "face_restore_enabled": bool(self.face_restore_enabled_var.get()),
            "face_restore_method": self.face_restore_method_var.get(),
            "face_restore_fidelity": float(self.face_restore_fidelity_var.get()),
            "interpolation_enabled": bool(self.interpolation_enabled_var.get()),
            "interpolation_multiplier": int(self.interpolation_multiplier_var.get()),
            "rife_executable_path": self.rife_executable_var.get(),
            "frame_upscale_enabled": bool(self.frame_upscale_enabled_var.get()),
            "frame_upscale_factor": float(self.frame_upscale_factor_var.get()),
        }

    def restore_svd_state(self, payload: dict[str, Any] | None) -> bool:
        if not isinstance(payload, dict):
            return False
        try:
            source_path = str(payload.get("source_image_path") or "")
            if source_path:
                self.source_image_var.set(source_path)
            self._last_folder = str(payload.get("last_folder") or self._last_folder)
            preset_name = str(payload.get("preset_name") or _DEFAULT_SVD_PRESET)
            if preset_name in _SVD_PRESETS:
                self.preset_var.set(preset_name)
            model_id = str(payload.get("model_id") or "")
            if model_id and model_id in list(self.model_combo.cget("values")):
                self.model_var.set(model_id)
            self.frames_var.set(int(payload.get("num_frames", self.frames_var.get())))
            self.fps_var.set(int(payload.get("fps", self.fps_var.get())))
            self.motion_bucket_var.set(int(payload.get("motion_bucket_id", self.motion_bucket_var.get())))
            self.noise_aug_var.set(float(payload.get("noise_aug_strength", self.noise_aug_var.get())))
            self.inference_steps_var.set(int(payload.get("num_inference_steps", self.inference_steps_var.get())))
            seed = payload.get("seed")
            self.seed_var.set("" if seed in (None, "") else str(seed))
            target_preset = str(payload.get("target_preset") or _DEFAULT_TARGET_PRESET)
            if target_preset in _TARGET_PRESETS:
                self.target_preset_var.set(target_preset)
            resize_mode = str(payload.get("resize_mode") or "letterbox")
            if resize_mode in _RESIZE_MODES:
                self.resize_mode_var.set(resize_mode)
            output_format = str(payload.get("output_format") or "mp4")
            if output_format in _OUTPUT_FORMATS:
                self.output_format_var.set(output_format)
            output_route = str(payload.get("output_route") or OUTPUT_ROUTE_SVD)
            if output_route in _SVD_OUTPUT_ROUTES:
                self.output_route_var.set(output_route)
            self.save_frames_var.set(bool(payload.get("save_frames", self.save_frames_var.get())))
            self.cpu_offload_var.set(bool(payload.get("cpu_offload", self.cpu_offload_var.get())))
            self.forward_chunking_var.set(bool(payload.get("forward_chunking", self.forward_chunking_var.get())))
            self.local_files_only_var.set(bool(payload.get("local_files_only", self.local_files_only_var.get())))
            self.decode_chunk_size_var.set(int(payload.get("decode_chunk_size", self.decode_chunk_size_var.get())))
            self.cache_dir_var.set(str(payload.get("cache_dir") or ""))
            self.face_restore_enabled_var.set(bool(payload.get("face_restore_enabled", self.face_restore_enabled_var.get())))
            face_restore_method = str(payload.get("face_restore_method") or self.face_restore_method_var.get())
            if face_restore_method in _FACE_RESTORE_METHODS:
                self.face_restore_method_var.set(face_restore_method)
            self.face_restore_fidelity_var.set(float(payload.get("face_restore_fidelity", self.face_restore_fidelity_var.get())))
            self.interpolation_enabled_var.set(bool(payload.get("interpolation_enabled", self.interpolation_enabled_var.get())))
            self.interpolation_multiplier_var.set(int(payload.get("interpolation_multiplier", self.interpolation_multiplier_var.get())))
            self.rife_executable_var.set(str(payload.get("rife_executable_path") or ""))
            self.frame_upscale_enabled_var.set(bool(payload.get("frame_upscale_enabled", self.frame_upscale_enabled_var.get())))
            self.frame_upscale_factor_var.set(float(payload.get("frame_upscale_factor", self.frame_upscale_factor_var.get())))
            self._refresh_capabilities()
            self._refresh_summary(source_path or None)
            return True
        except Exception as exc:
            logger.warning("Failed to restore SVD tab state: %s", exc)
            return False

    @staticmethod
    def _format_time(value: Any) -> str:
        if value in (None, ""):
            return "-"
        if isinstance(value, datetime):
            dt = value
        else:
            try:
                dt = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
            except Exception:
                return str(value)
        try:
            return dt.astimezone().strftime("%m-%d-%Y %H:%M:%S")
        except Exception:
            return dt.strftime("%m-%d-%Y %H:%M:%S")

    @staticmethod
    def _shorten_model(model_id: Any) -> str:
        text = str(model_id or "-")
        if len(text) <= 36:
            return text
        return f"{text[:33]}..."
