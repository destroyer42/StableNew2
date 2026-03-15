from __future__ import annotations

import logging
import tkinter as tk
from pathlib import Path
from tkinter import filedialog, messagebox, ttk
from typing import Any

from src.gui.ui_tokens import TOKENS
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
_DEFAULT_TARGET_PRESET = "Landscape 1024x576"


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

        model_options = self._get_model_options()
        default_model = model_options[0] if model_options else get_default_svd_model_id()

        self.source_image_var = tk.StringVar()
        self.model_var = tk.StringVar(value=default_model)
        self.frames_var = tk.IntVar(value=25)
        self.fps_var = tk.IntVar(value=7)
        self.motion_bucket_var = tk.IntVar(value=127)
        self.noise_aug_var = tk.DoubleVar(value=0.05)
        self.seed_var = tk.StringVar()
        self.target_preset_var = tk.StringVar(value=_DEFAULT_TARGET_PRESET)
        self.resize_mode_var = tk.StringVar(value="letterbox")
        self.output_format_var = tk.StringVar(value="mp4")
        self.save_frames_var = tk.BooleanVar(value=False)
        self.cpu_offload_var = tk.BooleanVar(value=True)
        self.forward_chunking_var = tk.BooleanVar(value=True)
        self.decode_chunk_size_var = tk.IntVar(value=2)

        self.columnconfigure(0, weight=1)
        self.rowconfigure(1, weight=1)

        self._build_header()
        self._build_body(model_options)

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
        body.rowconfigure(0, weight=1)

        help_frame = ttk.LabelFrame(body, text="SVD Img2Vid", style="Dark.TLabelframe", padding=8)
        help_frame.grid(row=0, column=0, sticky="nsew", padx=(0, 6))
        help_frame.columnconfigure(0, weight=1)

        help_text = (
            "Stable Video Diffusion animates an existing still image into a short clip.\n"
            "This path is native Python and does not use A1111/WebUI generation APIs."
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

        settings = ttk.LabelFrame(body, text="Settings", style="Dark.TLabelframe", padding=8)
        settings.grid(row=0, column=1, sticky="ns")
        settings.columnconfigure(1, weight=1)

        row = 0
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
        ).grid(row=row, column=0, columnspan=2, sticky="w", pady=(0, 12))
        row += 1

        self.animate_btn = ttk.Button(
            settings,
            text="Animate Image",
            style="Primary.TButton",
            command=self._on_submit,
        )
        self.animate_btn.grid(row=row, column=0, columnspan=2, sticky="ew")

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
                    return values
            except Exception:
                logger.exception("Failed to load SVD model options from controller")
        supported = get_supported_svd_models()
        return list(supported.keys())

    def _on_browse_image(self) -> None:
        initial_dir = self._last_folder or None
        path = filedialog.askopenfilename(title="Select source image", initialdir=initial_dir, filetypes=_IMAGE_FILETYPES)
        if path:
            self.source_image_var.set(path)
            self._last_folder = str(Path(path).parent)
            self._set_status(f"Selected {Path(path).name}")

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
        self.source_image_var.set(latest_path)
        self._last_folder = str(Path(latest_path).parent)
        self._set_status(f"Using latest output: {Path(latest_path).name}")

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
                "decode_chunk_size": int(self.decode_chunk_size_var.get()),
                "seed": seed_value,
                "cpu_offload": bool(self.cpu_offload_var.get()),
                "forward_chunking": bool(self.forward_chunking_var.get()),
            },
            "output": {
                "output_format": self.output_format_var.get(),
                "save_frames": bool(self.save_frames_var.get()),
                "save_preview_image": True,
            },
        }

    def _refresh_summary(self, source: str | None = None) -> None:
        source_name = Path(source or self.source_image_var.get() or "").name or "No source image"
        self.summary_label.configure(
            text=(
                f"Source: {source_name}\n"
                f"Frames: {int(self.frames_var.get())} at {int(self.fps_var.get())} fps\n"
                f"Output: {self.output_format_var.get()} | Resize: {self.resize_mode_var.get()}"
            )
        )

    def _set_status(self, message: str) -> None:
        self._status_text = message
        try:
            self.status_label.configure(text=message)
        except Exception:
            pass

    def get_svd_state(self) -> dict[str, Any]:
        return {
            "source_image_path": self.source_image_var.get(),
            "last_folder": self._last_folder,
            "model_id": self.model_var.get(),
            "num_frames": int(self.frames_var.get()),
            "fps": int(self.fps_var.get()),
            "motion_bucket_id": int(self.motion_bucket_var.get()),
            "noise_aug_strength": float(self.noise_aug_var.get()),
            "seed": self.seed_var.get(),
            "target_preset": self.target_preset_var.get(),
            "resize_mode": self.resize_mode_var.get(),
            "output_format": self.output_format_var.get(),
            "save_frames": bool(self.save_frames_var.get()),
            "cpu_offload": bool(self.cpu_offload_var.get()),
            "forward_chunking": bool(self.forward_chunking_var.get()),
            "decode_chunk_size": int(self.decode_chunk_size_var.get()),
        }

    def restore_svd_state(self, payload: dict[str, Any] | None) -> bool:
        if not isinstance(payload, dict):
            return False
        try:
            source_path = str(payload.get("source_image_path") or "")
            if source_path:
                self.source_image_var.set(source_path)
            self._last_folder = str(payload.get("last_folder") or self._last_folder)
            model_id = str(payload.get("model_id") or "")
            if model_id and model_id in list(self.model_combo.cget("values")):
                self.model_var.set(model_id)
            self.frames_var.set(int(payload.get("num_frames", self.frames_var.get())))
            self.fps_var.set(int(payload.get("fps", self.fps_var.get())))
            self.motion_bucket_var.set(int(payload.get("motion_bucket_id", self.motion_bucket_var.get())))
            self.noise_aug_var.set(float(payload.get("noise_aug_strength", self.noise_aug_var.get())))
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
            self.save_frames_var.set(bool(payload.get("save_frames", self.save_frames_var.get())))
            self.cpu_offload_var.set(bool(payload.get("cpu_offload", self.cpu_offload_var.get())))
            self.forward_chunking_var.set(bool(payload.get("forward_chunking", self.forward_chunking_var.get())))
            self.decode_chunk_size_var.set(int(payload.get("decode_chunk_size", self.decode_chunk_size_var.get())))
            self._refresh_summary(source_path or None)
            return True
        except Exception as exc:
            logger.warning("Failed to restore SVD tab state: %s", exc)
            return False
