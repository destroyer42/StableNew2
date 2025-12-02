"""Advanced Img2Img stage card for V2 GUI."""

from __future__ import annotations

import tkinter as tk
from tkinter import ttk
from typing import Any

from src.gui.stage_cards_v2.base_stage_card_v2 import BaseStageCardV2
from src.gui.stage_cards_v2.components import SamplerSection, SeedSection
from src.gui.stage_cards_v2.validation_result import ValidationResult
from src.gui.enhanced_slider import EnhancedSlider
from src.gui.theme_v2 import BODY_LABEL_STYLE, SURFACE_FRAME_STYLE


class AdvancedImg2ImgStageCardV2(BaseStageCardV2):
    panel_header = "Img2Img Configuration"

    def __init__(self, master: tk.Misc, *, controller=None, theme=None, **kwargs: Any) -> None:
        self.controller = controller
        self.theme = theme
        self._on_change = None
        super().__init__(master, title=self.panel_header, **kwargs)

    def _build_body(self, parent: ttk.Frame) -> None:
        # Core vars
        self.model_var = tk.StringVar()
        self.vae_var = tk.StringVar()
        self.sampler_var = tk.StringVar()
        self.steps_var = tk.IntVar(value=20)
        self.cfg_var = tk.DoubleVar(value=7.0)
        self.denoise_var = tk.DoubleVar(value=0.3)
        self.width_var = tk.IntVar(value=0)
        self.height_var = tk.IntVar(value=0)
        self.mask_mode_var = tk.StringVar(value="none")

        # Sampler/steps/cfg shared section (reuse cfg var)
        self.sampler_section = SamplerSection(parent)
        self.sampler_section.grid(row=0, column=0, sticky="ew", pady=(0, 8))
        self.sampler_section.sampler_var = self.sampler_var  # type: ignore[assignment]
        try:
            for child in self.sampler_section.winfo_children():
                child.destroy()
        except Exception:
            pass
        ttk.Label(self.sampler_section, text="Sampler", style=BODY_LABEL_STYLE).grid(row=0, column=0, sticky="w", padx=(0, 4))
        self.sampler_combo = ttk.Combobox(
            self.sampler_section,
            textvariable=self.sampler_var,
            values=getattr(self.controller, "get_available_samplers", lambda: [])() or ["Euler", "DPM++ 2M"],
            state="readonly",
            width=18,
            style="Dark.TCombobox",
        )
        self.sampler_combo.grid(row=0, column=1, sticky="ew", padx=(0, 8))

        ttk.Label(self.sampler_section, text="Steps", style=BODY_LABEL_STYLE).grid(row=0, column=2, sticky="w", padx=(0, 4))
        # Steps combobox with common values
        steps_values = ["10", "15", "20", "25", "30", "40", "50", "75", "100"]
        self.steps_combo = ttk.Combobox(
            self.sampler_section,
            textvariable=self.steps_var,
            values=steps_values,
            state="readonly",
            width=6,
            style="Dark.TCombobox",
        )
        self.steps_combo.grid(row=0, column=3, sticky="ew")

        ttk.Label(self.sampler_section, text="CFG", style=BODY_LABEL_STYLE).grid(row=1, column=0, sticky="w", padx=(0, 4), pady=(6, 0))
        # CFG slider with fixed range 1.0-30.0
        from src.gui.enhanced_slider import EnhancedSlider
        self.cfg_slider = EnhancedSlider(
            self.sampler_section,
            from_=1.0,
            to=30.0,
            variable=self.cfg_var,
            resolution=0.1,
            width=120,
            label="",
            command=self._on_cfg_changed,
        )
        self.cfg_slider.grid(row=1, column=1, sticky="ew", pady=(6, 0), padx=(0, 8))
        for col in range(4):
            self.sampler_section.columnconfigure(col, weight=1 if col in (1, 3) else 0)

        meta = ttk.Frame(parent, style=SURFACE_FRAME_STYLE)
        meta.grid(row=1, column=0, sticky="ew", pady=(0, 8))

        ttk.Label(meta, text="Denoise", style=BODY_LABEL_STYLE).grid(row=0, column=0, sticky="w", padx=(0, 4))
        slider_frame = ttk.Frame(meta, style=SURFACE_FRAME_STYLE)
        slider_frame.grid(row=0, column=1, sticky="ew", padx=(0, 8))
        EnhancedSlider(
            slider_frame,
            variable=self.denoise_var,
            from_=0.0,
            to=1.0,
            resolution=0.01,
            label="",
        ).pack(fill="x", expand=True)

        ttk.Label(meta, text="Mask mode", style=BODY_LABEL_STYLE).grid(row=0, column=2, sticky="w", padx=(0, 4))
        ttk.Combobox(
            meta,
            textvariable=self.mask_mode_var,
            values=["none", "keep", "discard", "auto"],
            state="readonly",
            width=12,
            style="Dark.TCombobox",
        ).grid(row=0, column=3, sticky="ew")

        ttk.Label(meta, text="Width", style=BODY_LABEL_STYLE).grid(row=1, column=0, sticky="w", pady=(6, 2))
        # Width combobox with multiples of 128 only
        width_values = [str(i) for i in range(256, 2049, 128)]  # 256 to 2048 in steps of 128
        self.width_combo = ttk.Combobox(
            meta,
            textvariable=self.width_var,
            values=width_values,
            state="readonly",
            width=8,
            style="Dark.TCombobox",
        )
        self.width_combo.grid(row=1, column=1, sticky="ew", padx=(0, 8))
        
        ttk.Label(meta, text="Height", style=BODY_LABEL_STYLE).grid(row=1, column=2, sticky="w", pady=(6, 2))
        # Height combobox with multiples of 128 only  
        height_values = [str(i) for i in range(256, 2049, 128)]  # 256 to 2048 in steps of 128
        self.height_combo = ttk.Combobox(
            meta,
            textvariable=self.height_var,
            values=height_values,
            state="readonly",
            width=8,
            style="Dark.TCombobox",
        )
        self.height_combo.grid(row=1, column=3, sticky="ew")
        for col in range(4):
            meta.columnconfigure(col, weight=1 if col in (1, 3) else 0)

        self.seed_section = SeedSection(parent)
        self.seed_section.grid(row=2, column=0, sticky="ew")
        self.seed_var = self.seed_section.seed_var  # compatibility exposure

        for var in self.watchable_vars():
            try:
                var.trace_add("write", lambda *_: self._notify_change())
            except Exception:
                pass

        parent.columnconfigure(0, weight=1)

    def _notify_change(self) -> None:
        if self._on_change:
            try:
                self._on_change()
            except Exception:
                pass

    def _on_cfg_changed(self, value: float) -> None:
        """Handle CFG slider changes"""
        self.cfg_var.set(value)
        self._notify_change()

    def set_on_change(self, callback: Any) -> None:
        self._on_change = callback

    def load_from_section(self, section: dict[str, Any] | None) -> None:
        data = section or {}
        self.model_var.set(data.get("model") or data.get("model_name", ""))
        self.vae_var.set(data.get("vae") or data.get("vae_name", ""))
        self.sampler_var.set(data.get("sampler_name", ""))
        self.steps_var.set(int(self._safe_int(data.get("steps", 20), 20)))
        self.cfg_var.set(float(self._safe_float(data.get("cfg_scale", 7.0), 7.0)))
        self.denoise_var.set(float(self._safe_float(data.get("denoising_strength", 0.3), 0.3)))
        self.width_var.set(int(self._safe_int(data.get("width", 0), 0)))
        self.height_var.set(int(self._safe_int(data.get("height", 0), 0)))
        self.mask_mode_var.set(str(data.get("mask_mode", "none")))

    def load_from_config(self, cfg: dict[str, Any]) -> None:
        section = (cfg or {}).get("img2img", {}) or {}
        self.load_from_section(section)

    def to_config_dict(self) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "model": self.model_var.get().strip(),
            "model_name": self.model_var.get().strip(),
            "vae": self.vae_var.get().strip(),
            "vae_name": self.vae_var.get().strip(),
            "sampler_name": self.sampler_var.get().strip(),
            "steps": int(self.steps_var.get() or 20),
            "cfg_scale": float(self.cfg_var.get() or 7.0),
            "denoising_strength": float(self.denoise_var.get() or 0.3),
        }
        if self.width_var.get():
            payload["width"] = int(self.width_var.get())
        if self.height_var.get():
            payload["height"] = int(self.height_var.get())
        if self.mask_mode_var.get():
            payload["mask_mode"] = self.mask_mode_var.get()
        return {"img2img": payload}

    def validate(self) -> ValidationResult:
        try:
            denoise = float(self.denoise_var.get())
        except Exception:
            return ValidationResult(False, "Denoise must be numeric")
        if not 0.0 <= denoise <= 1.0:
            return ValidationResult(False, "Denoise must be between 0 and 1")
        return ValidationResult(True, None)

    def watchable_vars(self) -> list[tk.Variable]:
        return [
            self.sampler_var,
            self.cfg_var,
            self.denoise_var,
            self.width_var,
            self.height_var,
            self.mask_mode_var,
            self.steps_var,
            self.model_var,
            self.vae_var,
        ]

    def apply_resource_update(self, resources: dict[str, list[Any]] | None) -> None:
        if not resources:
            return
        samplers = resources.get("samplers") or []
        self._set_sampler_values(samplers)

    def _set_sampler_values(self, entries: list[Any]) -> None:
        values = [self._normalize_sampler_entry(entry) for entry in entries]
        values = [value for value in values if value]
        combo = self.sampler_combo
        combo["values"] = values
        if not values:
            return
        current = self.sampler_var.get()
        if current in values:
            self.sampler_var.set(current)
        else:
            self.sampler_var.set(values[0])

    @staticmethod
    def _normalize_sampler_entry(entry: Any) -> str:
        if isinstance(entry, dict):
            return (
                str(entry.get("name") or entry.get("label") or entry.get("sampler_name") or entry.get("title") or "")
                .strip()
            )
        return str(entry).strip()

    @staticmethod
    def _safe_int(value: Any, default: int) -> int:
        try:
            return int(value)
        except Exception:
            return default

    @staticmethod
    def _safe_float(value: Any, default: float) -> float:
        try:
            return float(value)
        except Exception:
            return default
