from __future__ import annotations

import tkinter as tk
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

    MODEL_OPTIONS = ["face_yolov8n.pt", "adetailer_v1.pt"]
    DETECTOR_OPTIONS = ["face", "hand", "body"]
    SAMPLER_OPTIONS = ["DPM++ 2M", "Euler a", "DDIM", "DPM++ SDE"]
    MERGE_MODES = ["keep", "replace", "merge"]

    def __init__(self, master: tk.Misc, *, theme: Any | None = None, **kwargs: Any) -> None:
        # Detection settings
        self.model_var = tk.StringVar(value=self.MODEL_OPTIONS[0])
        self.detector_var = tk.StringVar(value=self.DETECTOR_OPTIONS[0])
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
        
        self._model_combo: ttk.Combobox | None = None
        self._detector_combo: ttk.Combobox | None = None
        self._sampler_combo: ttk.Combobox | None = None

        super().__init__(
            master,
            title="ADetailer Stage",
            description="Fine-tune face/hand/model outputs after txt2img.",
            theme=theme,
            **kwargs,
        )

    def _build_body(self, parent: ttk.Frame) -> None:
        parent.columnconfigure(1, weight=1)
        row = 0

        self._model_combo = self._add_labeled_combo(
            parent,
            "ADetailer model:",
            self.model_var,
            self.MODEL_OPTIONS,
            row,
        )
        row += 1
        self._detector_combo = self._add_labeled_combo(
            parent,
            "Detector:",
            self.detector_var,
            self.DETECTOR_OPTIONS,
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
        spin = ttk.Spinbox(
            parent,
            from_=minimum,
            to=maximum,
            increment=increment,
            textvariable=variable,
            width=8,
            format=format_str if isinstance(variable, tk.DoubleVar) else None,
            style=DARK_SPINBOX_STYLE,
        )
        spin.grid(row=row, column=1, sticky="w", pady=2, padx=(8, 0))
        return row + 1

    def load_from_dict(self, cfg: dict[str, Any] | None) -> None:
        if not cfg:
            return
        # Detection settings
        self.model_var.set(cfg.get("adetailer_model") or cfg.get("ad_model") or self.MODEL_OPTIONS[0])
        self.detector_var.set(cfg.get("detector") or self.DETECTOR_OPTIONS[0])
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

    def to_config_dict(self) -> dict[str, Any]:
        """Export config with keys matching executor.py expectations (lines 1354-1366)."""
        return {
            # Detection settings (original 8 fields)
            "adetailer_model": self.model_var.get(),
            "ad_model": self.model_var.get(),  # Dual key for compatibility
            "detector": self.detector_var.get(),
            "adetailer_confidence": self.confidence_var.get(),
            "ad_confidence": self.confidence_var.get(),  # Dual key
            "max_detections": self.max_detections_var.get(),
            "mask_blur": self.mask_blur_var.get(),
            "ad_mask_blur": self.mask_blur_var.get(),  # Dual key
            "mask_merge_mode": self.merge_var.get(),
            "only_faces": self.only_faces_var.get(),
            "only_hands": self.only_hands_var.get(),
            
            # Generation settings (NEW - from executor.py)
            "adetailer_steps": self.steps_var.get(),
            "ad_steps": self.steps_var.get(),  # Dual key
            "adetailer_cfg": self.cfg_var.get(),
            "ad_cfg_scale": self.cfg_var.get(),  # Dual key
            "adetailer_sampler": self.sampler_var.get(),
            "ad_sampler": self.sampler_var.get(),  # Dual key
            "adetailer_denoise": self.denoise_var.get(),
            "ad_denoising_strength": self.denoise_var.get(),  # Dual key
            
            # Prompt settings (NEW)
            "adetailer_prompt": self.prompt_var.get(),
            "ad_prompt": self.prompt_var.get(),  # Dual key
            "adetailer_negative_prompt": self.negative_var.get(),
            "ad_negative_prompt": self.negative_var.get(),  # Dual key
            
            # Inpaint settings (NEW)
            "ad_inpaint_only_masked": self.inpaint_masked_var.get(),
            "ad_inpaint_only_masked_padding": self.inpaint_padding_var.get(),
            "ad_use_inpaint_width_height": self.use_inpaint_wh_var.get(),
        }

    def watchable_vars(self) -> Iterable[tk.Variable]:
        return [
            # Detection settings
            self.model_var,
            self.detector_var,
            self.confidence_var,
            self.max_detections_var,
            self.mask_blur_var,
            self.merge_var,
            self.only_faces_var,
            self.only_hands_var,
            # Generation settings (NEW)
            self.steps_var,
            self.cfg_var,
            self.sampler_var,
            self.denoise_var,
            # Prompt settings (NEW)
            self.prompt_var,
            self.negative_var,
            # Inpaint settings (NEW)
            self.inpaint_masked_var,
            self.inpaint_padding_var,
            self.use_inpaint_wh_var,
        ]

    def apply_webui_resources(self, resources: dict[str, Any] | None) -> None:
        if resources is None:
            resources = {}
        models = [str(v) for v in (resources.get("adetailer_models") or []) if str(v).strip()]
        detectors = [str(v) for v in (resources.get("adetailer_detectors") or []) if str(v).strip()]
        samplers = [str(v) for v in (resources.get("samplers") or []) if str(v).strip()]

        self._configure_combo(self._model_combo, models, self.model_var)
        self._configure_combo(self._detector_combo, detectors, self.detector_var)
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
