"""Advanced Upscale stage card for V2 GUI."""

from __future__ import annotations

import tkinter as tk
from tkinter import ttk
from typing import Any

from src.gui.stage_cards_v2.base_stage_card_v2 import BaseStageCardV2
from src.gui.stage_cards_v2.validation_result import ValidationResult


class AdvancedUpscaleStageCardV2(BaseStageCardV2):
    panel_header = "Upscale Configuration"

    def __init__(self, master: tk.Misc, *, controller=None, theme=None, **kwargs: Any) -> None:
        self.controller = controller
        self.theme = theme
        super().__init__(master, title=self.panel_header, **kwargs)

    def _build_body(self, parent: ttk.Frame) -> None:
        self.upscaler_var = tk.StringVar()
        self.mode_var = tk.StringVar(value="single")
        self.steps_var = tk.IntVar(value=20)
        self.denoise_var = tk.DoubleVar(value=0.35)
        self.factor_var = tk.DoubleVar(value=2.0)
        self.tile_size_var = tk.IntVar(value=0)
        self.face_restore_var = tk.BooleanVar(value=False)

        ttk.Label(parent, text="Upscaler", style="Muted.TLabel").grid(row=0, column=0, sticky="w", padx=(0, 4))
        ttk.Combobox(
            parent,
            textvariable=self.upscaler_var,
            values=["R-ESRGAN 4x+", "4x-UltraSharp", "Remacri"],
            state="readonly",
            width=18,
        ).grid(row=0, column=1, sticky="ew", padx=(0, 8))

        ttk.Label(parent, text="Mode", style="Muted.TLabel").grid(row=0, column=2, sticky="w", padx=(0, 4))
        ttk.Combobox(
            parent,
            textvariable=self.mode_var,
            values=["single", "batch"],
            state="readonly",
            width=12,
        ).grid(row=0, column=3, sticky="ew")

        ttk.Label(parent, text="Steps", style="Muted.TLabel").grid(row=1, column=0, sticky="w", pady=(6, 2))
        tk.Spinbox(parent, from_=1, to=150, increment=1, textvariable=self.steps_var, width=8).grid(
            row=1, column=1, sticky="ew", padx=(0, 8)
        )
        ttk.Label(parent, text="Denoise", style="Muted.TLabel").grid(row=1, column=2, sticky="w", pady=(6, 2))
        tk.Spinbox(parent, from_=0.0, to=1.0, increment=0.05, textvariable=self.denoise_var, width=8).grid(
            row=1, column=3, sticky="ew"
        )

        ttk.Label(parent, text="Scale", style="Muted.TLabel").grid(row=2, column=0, sticky="w", pady=(6, 2))
        tk.Spinbox(parent, from_=1.0, to=4.0, increment=0.1, textvariable=self.factor_var, width=8).grid(
            row=2, column=1, sticky="ew", padx=(0, 8)
        )
        ttk.Label(parent, text="Tile size", style="Muted.TLabel").grid(row=2, column=2, sticky="w", pady=(6, 2))
        tk.Spinbox(parent, from_=0, to=4096, increment=16, textvariable=self.tile_size_var, width=8).grid(
            row=2, column=3, sticky="ew"
        )

        ttk.Checkbutton(parent, text="Face restore", variable=self.face_restore_var).grid(
            row=3, column=0, columnspan=2, sticky="w", pady=(6, 0)
        )

        for col in range(4):
            parent.columnconfigure(col, weight=1 if col in (1, 3) else 0)

    def load_from_config(self, cfg: dict[str, Any]) -> None:
        section = (cfg or {}).get("upscale", {}) or {}
        self.upscaler_var.set(section.get("upscaler", ""))
        self.mode_var.set(section.get("upscale_mode", "single"))
        self.steps_var.set(int(self._safe_int(section.get("steps", 20), 20)))
        self.denoise_var.set(float(self._safe_float(section.get("denoising_strength", 0.35), 0.35)))
        self.factor_var.set(float(self._safe_float(section.get("upscaling_resize", section.get("upscale_factor", 2.0)), 2.0)))
        self.tile_size_var.set(int(self._safe_int(section.get("tile_size", 0), 0)))
        self.face_restore_var.set(bool(section.get("face_restore", False)))

    def to_config_dict(self) -> dict[str, Any]:
        return {
            "upscale": {
                "upscaler": self.upscaler_var.get().strip(),
                "upscale_mode": self.mode_var.get().strip(),
                "steps": int(self.steps_var.get() or 20),
                "denoising_strength": float(self.denoise_var.get() or 0.35),
                "upscaling_resize": float(self.factor_var.get() or 2.0),
                "tile_size": int(self.tile_size_var.get() or 0),
                "face_restore": bool(self.face_restore_var.get()),
            }
        }

    def validate(self) -> ValidationResult:
        try:
            factor = float(self.factor_var.get())
        except Exception:
            return ValidationResult(False, "Factor must be numeric")
        if factor < 1.0:
            return ValidationResult(False, "Factor must be >= 1")
        return ValidationResult(True, None)

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
