from __future__ import annotations

import tkinter as tk
import logging
from collections.abc import Iterable
from tkinter import ttk
from typing import Any

from src.gui.stage_cards_v2.base_stage_card_v2 import BaseStageCardV2
from src.gui.theme_v2 import (
    BODY_LABEL_STYLE,
    DARK_CHECKBUTTON_STYLE,
    DARK_COMBOBOX_STYLE,
    DARK_ENTRY_STYLE,
    DARK_SPINBOX_STYLE,
    SURFACE_FRAME_STYLE,
)


class ADetailerStageCardV2(BaseStageCardV2):
    """Minimal ADetailer stage card exposing controls via BaseStageCardV2."""

    logger = logging.getLogger(__name__)

    MODEL_OPTIONS = ["face_yolov8n.pt", "adetailer_v1.pt"]
    SAMPLER_OPTIONS = ["DPM++ 2M", "Euler a", "DDIM", "DPM++ SDE"]
    MERGE_MODES = ["keep", "replace", "merge"]

    def __init__(self, master: tk.Misc, *, theme: Any | None = None, **kwargs: Any) -> None:
        # Detection settings
        self.model_var = tk.StringVar(value=self.MODEL_OPTIONS[0])
        self.confidence_var = tk.DoubleVar(value=0.35)
        self.max_detections_var = tk.IntVar(value=8)
        self.mask_blur_var = tk.IntVar(value=4)
        self.merge_var = tk.StringVar(value=self.MERGE_MODES[0])
        self.only_faces_var = tk.BooleanVar(value=True)
        self.only_hands_var = tk.BooleanVar(value=False)
        
        # Generation settings (from executor.py lines 1358-1366)
        self.steps_var = tk.IntVar(value=28)
        self.cfg_var = tk.DoubleVar(value=7.0)
        self.sampler_var = tk.StringVar(value="DPM++ 2M")
        self.denoise_var = tk.DoubleVar(value=0.4)
        
        # Prompt settings
        self.prompt_var = tk.StringVar(value="")
        self.negative_var = tk.StringVar(value="")
        
        # Inpaint settings
        self.inpaint_masked_var = tk.BooleanVar(value=True)
        self.inpaint_padding_var = tk.IntVar(value=32)
        self.use_inpaint_wh_var = tk.BooleanVar(value=False)
        
        # PR-GUI-DATA-008: Two-pass controls
        self.enable_face_pass_var = tk.BooleanVar(value=True)
        self.face_model_var = tk.StringVar(value="face_yolov8n.pt")
        self.face_padding_var = tk.IntVar(value=32)
        self.enable_hands_pass_var = tk.BooleanVar(value=False)
        self.hands_model_var = tk.StringVar(value="hand_yolov8n.pt")
        self.hands_padding_var = tk.IntVar(value=32)
        
        # PR-GUI-DATA-008: Mask filter controls
        self.mask_filter_method_var = tk.StringVar(value="largest")
        self.mask_k_largest_var = tk.IntVar(value=3)
        self.mask_min_ratio_var = tk.DoubleVar(value=0.01)
        self.mask_max_ratio_var = tk.DoubleVar(value=1.0)
        
        # PR-GUI-DATA-008: Mask processing controls
        self.dilate_erode_var = tk.IntVar(value=4)
        self.mask_feather_var = tk.IntVar(value=5)
        
        # PR-GUI-DATA-008: Scheduler control
        self.scheduler_var = tk.StringVar(value="Use sampler default")
        
        self._model_combo: ttk.Combobox | None = None
        self._sampler_combo: ttk.Combobox | None = None
        self._face_model_combo: ttk.Combobox | None = None
        self._hands_model_combo: ttk.Combobox | None = None
        self._scheduler_combo: ttk.Combobox | None = None

        super().__init__(
            master,
            title="ADetailer Stage",
            description="Fine-tune face/hand/model outputs after txt2img.",
            theme=theme,
            **kwargs,
        )

    def _build_body(self, parent: ttk.Frame) -> None:
        """Build ADetailer configuration body with PR-GUI-DATA-008 enhancements."""
        parent.columnconfigure(1, weight=1)
        row = 0

        # PR-GUI-DATA-008: Two-Pass Configuration Section
        ttk.Label(parent, text="─── Pass Configuration ───", style=BODY_LABEL_STYLE).grid(
            row=row, column=0, columnspan=2, sticky="ew", pady=(0, 4)
        )
        row += 1
        
        # Face pass
        face_frame = ttk.Frame(parent, style=SURFACE_FRAME_STYLE)
        face_frame.grid(row=row, column=0, columnspan=2, sticky="ew", pady=2)
        ttk.Checkbutton(
            face_frame,
            text="Face Pass",
            variable=self.enable_face_pass_var,
            style=DARK_CHECKBUTTON_STYLE,
        ).pack(side="left")
        self._face_model_combo = ttk.Combobox(
            face_frame,
            textvariable=self.face_model_var,
            values=["face_yolov8n.pt", "face_yolov8s.pt", "mediapipe_face_full"],
            width=20,
            state="readonly",
            style=DARK_COMBOBOX_STYLE,
        )
        self._face_model_combo.pack(side="left", padx=(8, 0))
        ttk.Label(face_frame, text="Padding:", style=BODY_LABEL_STYLE).pack(side="left", padx=(12, 4))
        ttk.Spinbox(
            face_frame,
            from_=0,
            to=256,
            textvariable=self.face_padding_var,
            width=6,
            style=DARK_SPINBOX_STYLE,
        ).pack(side="left")
        row += 1
        
        # Hands pass
        hands_frame = ttk.Frame(parent, style=SURFACE_FRAME_STYLE)
        hands_frame.grid(row=row, column=0, columnspan=2, sticky="ew", pady=2)
        ttk.Checkbutton(
            hands_frame,
            text="Hands Pass",
            variable=self.enable_hands_pass_var,
            style=DARK_CHECKBUTTON_STYLE,
        ).pack(side="left")
        self._hands_model_combo = ttk.Combobox(
            hands_frame,
            textvariable=self.hands_model_var,
            values=["hand_yolov8n.pt", "hand_yolov8s.pt"],
            width=20,
            state="readonly",
            style=DARK_COMBOBOX_STYLE,
        )
        self._hands_model_combo.pack(side="left", padx=(8, 0))
        ttk.Label(hands_frame, text="Padding:", style=BODY_LABEL_STYLE).pack(side="left", padx=(12, 4))
        ttk.Spinbox(
            hands_frame,
            from_=0,
            to=256,
            textvariable=self.hands_padding_var,
            width=6,
            style=DARK_SPINBOX_STYLE,
        ).pack(side="left")
        row += 1
        
        # Original detection settings
        ttk.Label(parent, text="─── Detection Settings ───", style=BODY_LABEL_STYLE).grid(
            row=row, column=0, columnspan=2, sticky="ew", pady=(12, 4)
        )
        row += 1

        self._model_combo = self._add_labeled_combo(
            parent,
            "ADetailer model:",
            self.model_var,
            self.MODEL_OPTIONS,
            row,
        )
        row += 1

        row = self._add_spin_section(
            parent,
            row,
            "Confidence:",
            self.confidence_var,
            0.1,
            1.0,
            0.05,
            format_str="%.2f",
        )

        row = self._add_spin_section(
            parent,
            row,
            "Max detections:",
            self.max_detections_var,
            1,
            32,
            1,
        )

        row = self._add_spin_section(parent, row, "Mask blur:", self.mask_blur_var, 0, 16, 1)

        self._add_labeled_combo(
            parent,
            "Mask merge mode:",
            self.merge_var,
            self.MERGE_MODES,
            row,
        )
        row += 1

        toggle_frame = ttk.Frame(parent, style=SURFACE_FRAME_STYLE)
        toggle_frame.grid(row=row, column=0, columnspan=2, sticky="ew", pady=(8, 0))
        ttk.Checkbutton(
            toggle_frame,
            text="Only faces",
            variable=self.only_faces_var,
            style=DARK_CHECKBUTTON_STYLE,
        ).pack(side="left", padx=(0, 6))
        ttk.Checkbutton(
            toggle_frame,
            text="Only hands",
            variable=self.only_hands_var,
            style=DARK_CHECKBUTTON_STYLE,
        ).pack(side="left")
        row += 1
        
        # PR-GUI-DATA-008: Mask Filter Controls
        ttk.Label(parent, text="─── Mask Filtering ───", style=BODY_LABEL_STYLE).grid(
            row=row, column=0, columnspan=2, sticky="ew", pady=(12, 4)
        )
        row += 1
        
        self._add_labeled_combo(
            parent,
            "Filter Method:",
            self.mask_filter_method_var,
            ["largest", "all"],
            row,
        )
        row += 1
        
        row = self._add_spin_section(
            parent, row, "Max K:", self.mask_k_largest_var, 1, 10, 1
        )
        row = self._add_spin_section(
            parent, row, "Min Ratio:", self.mask_min_ratio_var, 0.0, 1.0, 0.01, format_str="%.2f"
        )
        row = self._add_spin_section(
            parent, row, "Max Ratio:", self.mask_max_ratio_var, 0.0, 1.0, 0.01, format_str="%.2f"
        )
        
        # PR-GUI-DATA-008: Mask Processing Controls
        ttk.Label(parent, text="─── Mask Processing ───", style=BODY_LABEL_STYLE).grid(
            row=row, column=0, columnspan=2, sticky="ew", pady=(12, 4)
        )
        row += 1
        
        row = self._add_spin_section(
            parent, row, "Dilate/Erode:", self.dilate_erode_var, -32, 32, 1
        )
        row = self._add_spin_section(
            parent, row, "Feather:", self.mask_feather_var, 0, 64, 1
        )
        
        # Generation parameters section
        ttk.Label(parent, text="─── Generation Settings ───", style=BODY_LABEL_STYLE).grid(
            row=row, column=0, columnspan=2, sticky="ew", pady=(12, 4)
        )
        row += 1
        
        row = self._add_spin_section(parent, row, "Steps:", self.steps_var, 1, 150, 1)
        row = self._add_spin_section(
            parent, row, "CFG Scale:", self.cfg_var, 1.0, 30.0, 0.5, format_str="%.1f"
        )
        row = self._add_spin_section(
            parent, row, "Denoising:", self.denoise_var, 0.0, 1.0, 0.05, format_str="%.2f"
        )
        
        # Sampler dropdown
        self._sampler_combo = self._add_labeled_combo(
            parent, "Sampler:", self.sampler_var, self.SAMPLER_OPTIONS, row
        )
        row += 1
        
        # PR-GUI-DATA-008: Scheduler Control
        self._scheduler_combo = self._add_labeled_combo(
            parent,
            "Scheduler:",
            self.scheduler_var,
            ["Use sampler default", "Automatic", "Karras", "Exponential", "SGM Uniform"],
            row,
        )
        row += 1
        
        # Prompts section
        ttk.Label(parent, text="─── Prompts (optional) ───", style=BODY_LABEL_STYLE).grid(
            row=row, column=0, columnspan=2, sticky="ew", pady=(12, 4)
        )
        row += 1
        
        ttk.Label(parent, text="Prompt:", style=BODY_LABEL_STYLE).grid(
            row=row, column=0, sticky="nw", pady=2
        )
        prompt_entry = ttk.Entry(parent, textvariable=self.prompt_var, style=DARK_ENTRY_STYLE)
        prompt_entry.grid(row=row, column=1, sticky="ew", pady=2, padx=(8, 0))
        row += 1
        
        ttk.Label(parent, text="Negative:", style=BODY_LABEL_STYLE).grid(
            row=row, column=0, sticky="nw", pady=2
        )
        neg_entry = ttk.Entry(parent, textvariable=self.negative_var, style=DARK_ENTRY_STYLE)
        neg_entry.grid(row=row, column=1, sticky="ew", pady=2, padx=(8, 0))
        row += 1
        
        # Inpaint settings
        ttk.Label(parent, text="─── Inpaint Settings ───", style=BODY_LABEL_STYLE).grid(
            row=row, column=0, columnspan=2, sticky="ew", pady=(12, 4)
        )
        row += 1
        
        inpaint_frame = ttk.Frame(parent, style=SURFACE_FRAME_STYLE)
        inpaint_frame.grid(row=row, column=0, columnspan=2, sticky="ew", pady=2)
        ttk.Checkbutton(
            inpaint_frame,
            text="Only masked",
            variable=self.inpaint_masked_var,
            style=DARK_CHECKBUTTON_STYLE,
        ).pack(side="left", padx=(0, 6))
        ttk.Checkbutton(
            inpaint_frame,
            text="Use inpaint W/H",
            variable=self.use_inpaint_wh_var,
            style=DARK_CHECKBUTTON_STYLE,
        ).pack(side="left")
        row += 1
        
        row = self._add_spin_section(
            parent, row, "Inpaint padding:", self.inpaint_padding_var, 0, 256, 4
        )

    def _add_labeled_combo(
        self,
        parent: ttk.Frame,
        label: str,
        variable: tk.StringVar,
        options: Iterable[str],
        row: int,
    ) -> ttk.Combobox:
        ttk.Label(parent, text=label, style=BODY_LABEL_STYLE).grid(
            row=row, column=0, sticky="w", pady=2
        )
        combo = ttk.Combobox(
            parent,
            values=list(options),
            textvariable=variable,
            state="readonly",
            style=DARK_COMBOBOX_STYLE,
        )
        combo.grid(row=row, column=1, sticky="ew", pady=2, padx=(8, 0))
        return combo

    def _add_spin_section(
        self,
        parent: ttk.Frame,
        row: int,
        label: str,
        variable: tk.Variable,
        minimum: float,
        maximum: float,
        increment: float,
        format_str: str = "%.1f",
    ) -> int:
        ttk.Label(parent, text=label, style=BODY_LABEL_STYLE).grid(
            row=row, column=0, sticky="w", pady=2
        )
        spin_kwargs: dict[str, Any] = {
            "from_": minimum,
            "to": maximum,
            "increment": increment,
            "textvariable": variable,
            "width": 8,
            "style": DARK_SPINBOX_STYLE,
        }
        if isinstance(variable, tk.DoubleVar):
            spin_kwargs["format"] = format_str
        
        spin = ttk.Spinbox(parent, **spin_kwargs)
        spin.grid(row=row, column=1, sticky="w", pady=2, padx=(8, 0))
        return row + 1

    def load_from_dict(self, cfg: dict[str, Any] | None) -> None:
        """Load configuration from dict with PR-GUI-DATA-008 enhancements."""
        if not cfg:
            return
        # Detection settings
        self.model_var.set(cfg.get("adetailer_model") or cfg.get("ad_model") or self.MODEL_OPTIONS[0])
        self.confidence_var.set(float(cfg.get("adetailer_confidence") or cfg.get("ad_confidence", 0.35)))
        self.max_detections_var.set(int(cfg.get("max_detections", 8)))
        self.mask_blur_var.set(int(cfg.get("mask_blur") or cfg.get("ad_mask_blur", 4)))
        self.merge_var.set(cfg.get("mask_merge_mode") or self.MERGE_MODES[0])
        self.only_faces_var.set(bool(cfg.get("only_faces", True)))
        self.only_hands_var.set(bool(cfg.get("only_hands", False)))
        
        # Generation settings (from executor.py fields)
        self.steps_var.set(int(cfg.get("adetailer_steps") or cfg.get("ad_steps", 28)))
        self.cfg_var.set(float(cfg.get("adetailer_cfg") or cfg.get("ad_cfg_scale", 7.0)))
        self.sampler_var.set(cfg.get("adetailer_sampler") or cfg.get("ad_sampler", "DPM++ 2M"))
        self.denoise_var.set(float(cfg.get("adetailer_denoise") or cfg.get("ad_denoising_strength", 0.4)))
        
        # Prompt settings
        self.prompt_var.set(cfg.get("adetailer_prompt") or cfg.get("ad_prompt", ""))
        self.negative_var.set(cfg.get("adetailer_negative_prompt") or cfg.get("ad_negative_prompt", ""))
        
        # Inpaint settings
        self.inpaint_masked_var.set(bool(cfg.get("ad_inpaint_only_masked", True)))
        self.inpaint_padding_var.set(int(cfg.get("ad_inpaint_only_masked_padding", 32)))
        self.use_inpaint_wh_var.set(bool(cfg.get("ad_use_inpaint_width_height", False)))
        
        # PR-GUI-DATA-008: Two-pass controls
        self.enable_face_pass_var.set(bool(cfg.get("enable_face_pass", True)))
        self.face_model_var.set(cfg.get("face_model", "face_yolov8n.pt"))
        self.face_padding_var.set(int(cfg.get("face_padding", 32)))
        self.enable_hands_pass_var.set(bool(cfg.get("enable_hands_pass", False)))
        self.hands_model_var.set(cfg.get("hands_model", "hand_yolov8n.pt"))
        self.hands_padding_var.set(int(cfg.get("hands_padding", 32)))
        
        # PR-GUI-DATA-008: Mask filter controls
        self.mask_filter_method_var.set(cfg.get("mask_filter_method", "largest"))
        self.mask_k_largest_var.set(int(cfg.get("mask_k_largest", 3)))
        self.mask_min_ratio_var.set(float(cfg.get("mask_min_ratio", 0.01)))
        self.mask_max_ratio_var.set(float(cfg.get("mask_max_ratio", 1.0)))
        
        # PR-GUI-DATA-008: Mask processing controls
        self.dilate_erode_var.set(int(cfg.get("mask_dilate_erode", 4)))
        self.mask_feather_var.set(int(cfg.get("mask_feather", 5)))
        
        # PR-GUI-DATA-008: Scheduler control
        self.scheduler_var.set(cfg.get("scheduler", "Use sampler default"))

    def to_config_dict(self) -> dict[str, Any]:
        """Export config with keys matching executor.py expectations and PR-GUI-DATA-008 enhancements."""
        return {
            # Detection settings (original fields)
            "adetailer_model": self.model_var.get(),
            "ad_model": self.model_var.get(),  # Dual key for compatibility
            "adetailer_confidence": self.confidence_var.get(),
            "ad_confidence": self.confidence_var.get(),  # Dual key
            "max_detections": self.max_detections_var.get(),
            "mask_blur": self.mask_blur_var.get(),
            "ad_mask_blur": self.mask_blur_var.get(),  # Dual key
            "mask_merge_mode": self.merge_var.get(),
            "only_faces": self.only_faces_var.get(),
            "only_hands": self.only_hands_var.get(),
            
            # Generation settings
            "adetailer_steps": self.steps_var.get(),
            "ad_steps": self.steps_var.get(),  # Dual key
            "adetailer_cfg": self.cfg_var.get(),
            "ad_cfg_scale": self.cfg_var.get(),  # Dual key
            "adetailer_sampler": self.sampler_var.get(),
            "ad_sampler": self.sampler_var.get(),  # Dual key
            "adetailer_denoise": self.denoise_var.get(),
            "ad_denoising_strength": self.denoise_var.get(),  # Dual key
            
            # Prompt settings
            "adetailer_prompt": self.prompt_var.get(),
            "ad_prompt": self.prompt_var.get(),  # Dual key
            "adetailer_negative_prompt": self.negative_var.get(),
            "ad_negative_prompt": self.negative_var.get(),  # Dual key
            
            # Inpaint settings
            "ad_inpaint_only_masked": self.inpaint_masked_var.get(),
            "ad_inpaint_only_masked_padding": self.inpaint_padding_var.get(),
            "ad_use_inpaint_width_height": self.use_inpaint_wh_var.get(),
            
            # PR-GUI-DATA-008: Two-pass controls
            "enable_face_pass": self.enable_face_pass_var.get(),
            "face_model": self.face_model_var.get(),
            "face_padding": self.face_padding_var.get(),
            "enable_hands_pass": self.enable_hands_pass_var.get(),
            "hands_model": self.hands_model_var.get(),
            "hands_padding": self.hands_padding_var.get(),
            
            # PR-GUI-DATA-008: Mask filter controls
            "mask_filter_method": self.mask_filter_method_var.get(),
            "mask_k_largest": self.mask_k_largest_var.get(),
            "ad_mask_k_largest": self.mask_k_largest_var.get(),  # Dual key
            "mask_min_ratio": self.mask_min_ratio_var.get(),
            "ad_mask_min_ratio": self.mask_min_ratio_var.get(),  # Dual key
            "mask_max_ratio": self.mask_max_ratio_var.get(),
            "ad_mask_max_ratio": self.mask_max_ratio_var.get(),  # Dual key
            
            # PR-GUI-DATA-008: Mask processing controls
            "mask_dilate_erode": self.dilate_erode_var.get(),
            "ad_dilate_erode": self.dilate_erode_var.get(),  # Dual key
            "mask_feather": self.mask_feather_var.get(),
            "ad_mask_feather": self.mask_feather_var.get(),  # Dual key
            
            # PR-GUI-DATA-008: Scheduler control
            "scheduler": self.scheduler_var.get(),
            "ad_scheduler": self.scheduler_var.get(),  # Dual key
            
            # Legacy mask filter fields (for backward compatibility)
            "ad_mask_filter_method": "Area",
            "ad_mask_merge_invert": "None",
        }

    def watchable_vars(self) -> Iterable[tk.Variable]:
        """Return all watchable variables including PR-GUI-DATA-008 additions."""
        return [
            # Detection settings
            self.model_var,
            self.confidence_var,
            self.max_detections_var,
            self.mask_blur_var,
            self.merge_var,
            self.only_faces_var,
            self.only_hands_var,
            # Generation settings
            self.steps_var,
            self.cfg_var,
            self.sampler_var,
            self.denoise_var,
            # Prompt settings
            self.prompt_var,
            self.negative_var,
            # Inpaint settings
            self.inpaint_masked_var,
            self.inpaint_padding_var,
            self.use_inpaint_wh_var,
            # PR-GUI-DATA-008: Two-pass controls
            self.enable_face_pass_var,
            self.face_model_var,
            self.face_padding_var,
            self.enable_hands_pass_var,
            self.hands_model_var,
            self.hands_padding_var,
            # PR-GUI-DATA-008: Mask filter controls
            self.mask_filter_method_var,
            self.mask_k_largest_var,
            self.mask_min_ratio_var,
            self.mask_max_ratio_var,
            # PR-GUI-DATA-008: Mask processing controls
            self.dilate_erode_var,
            self.mask_feather_var,
            # PR-GUI-DATA-008: Scheduler control
            self.scheduler_var,
        ]

    def apply_webui_resources(self, resources: dict[str, Any] | None) -> None:
        if resources is None:
            resources = {}
        models = [str(v) for v in (resources.get("adetailer_models") or []) if str(v).strip()]
        samplers = [str(v) for v in (resources.get("samplers") or []) if str(v).strip()]

        self._configure_combo(self._model_combo, models, self.model_var)
        self._configure_combo(self._sampler_combo, samplers, self.sampler_var)

    def _configure_combo(
        self, combo: ttk.Combobox | None, values: list[str], variable: tk.StringVar
    ) -> None:
        if not combo:
            return
        # Always keep combo enabled - use default values if WebUI resources not loaded yet
        combo.configure(
            values=values if values else list(combo["values"]),
            state="readonly",
            style=DARK_COMBOBOX_STYLE,
        )
        if values:
            current = variable.get()
            if not current or current not in values:
                variable.set(values[0])

    def apply_resource_update(self, resources: dict[str, Any] | None) -> None:
        """Apply WebUI-provided resources to adetailer model/detector dropdowns."""
        self.apply_webui_resources(resources)
