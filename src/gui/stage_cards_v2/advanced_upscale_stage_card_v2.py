"""Advanced Upscale stage card for V2 GUI."""

from __future__ import annotations

import tkinter as tk
from tkinter import ttk
from typing import Any

from src.gui.stage_cards_v2.base_stage_card_v2 import BaseStageCardV2
from src.gui.stage_cards_v2.validation_result import ValidationResult
from src.gui.theme_v2 import BODY_LABEL_STYLE


class AdvancedUpscaleStageCardV2(BaseStageCardV2):
    panel_header = "Upscale Configuration"

    def __init__(self, master: tk.Misc, *, controller: Any = None, theme: Any = None, **kwargs: Any) -> None:
        self.controller = controller
        self.theme = theme
        self.current_input_width = 512
        self.current_input_height = 512
        self.final_dimensions_label: ttk.Label | None = None
        self._upscaler_name_map: dict[str, str] = {}
        super().__init__(master, title=self.panel_header, **kwargs)

    def _build_body(self, parent: ttk.Frame) -> None:
        self.upscaler_var = tk.StringVar()
        self.mode_var = tk.StringVar(value="single")
        self.steps_var = tk.IntVar(value=20)
        self.denoise_var = tk.DoubleVar(value=0.35)
        self.factor_var = tk.DoubleVar(value=2.0)
        self.factor_var.trace_add("write", self._on_factor_changed)
        self.tile_size_var = tk.IntVar(value=0)
        self.face_restore_var = tk.BooleanVar(value=False)

        ttk.Label(parent, text="Upscaler", style=BODY_LABEL_STYLE).grid(row=0, column=0, sticky="w", padx=(0, 4))
        self.upscaler_combo = ttk.Combobox(
            parent,
            textvariable=self.upscaler_var,
            values=[],
            state="readonly",
            width=18,
            style="Dark.TCombobox",
        )
        self.upscaler_combo.grid(row=0, column=1, sticky="ew", padx=(0, 8))

        ttk.Label(parent, text="Mode", style=BODY_LABEL_STYLE).grid(row=0, column=2, sticky="w", padx=(0, 4))
        ttk.Combobox(
            parent,
            textvariable=self.mode_var,
            values=["single", "batch"],
            state="readonly",
            width=12,
            style="Dark.TCombobox",
        ).grid(row=0, column=3, sticky="ew")

        ttk.Label(parent, text="Steps", style=BODY_LABEL_STYLE).grid(row=1, column=0, sticky="w", pady=(6, 2))
        ttk.Spinbox(
            parent,
            from_=1,
            to=150,
            increment=1,
            textvariable=self.steps_var,
            width=8,
            style="Dark.TSpinbox",
        ).grid(row=1, column=1, sticky="ew", padx=(0, 8))
        ttk.Label(parent, text="Denoise", style=BODY_LABEL_STYLE).grid(row=1, column=2, sticky="w", pady=(6, 2))
        ttk.Spinbox(
            parent,
            from_=0.0,
            to=1.0,
            increment=0.05,
            textvariable=self.denoise_var,
            width=8,
            style="Dark.TSpinbox",
        ).grid(row=1, column=3, sticky="ew")

        ttk.Label(parent, text="Scale", style=BODY_LABEL_STYLE).grid(row=2, column=0, sticky="w", pady=(6, 2))
        self._scale_spinbox = ttk.Spinbox(
            parent,
            from_=1.0,
            to=4.0,
            increment=0.1,
            textvariable=self.factor_var,
            width=8,
            style="Dark.TSpinbox",
        )
        self._scale_spinbox.grid(row=2, column=1, sticky="ew", padx=(0, 8))
        ttk.Label(parent, text="Tile size", style=BODY_LABEL_STYLE).grid(row=2, column=2, sticky="w", pady=(6, 2))
        ttk.Spinbox(
            parent,
            from_=0,
            to=4096,
            increment=16,
            textvariable=self.tile_size_var,
            width=8,
            style="Dark.TSpinbox",
        ).grid(row=2, column=3, sticky="ew")

        ttk.Checkbutton(
            parent,
            text="Face restore",
            variable=self.face_restore_var,
            style="Dark.TCheckbutton",
        ).grid(row=3, column=0, columnspan=2, sticky="w", pady=(6, 0))

        # Final dimensions display
        ttk.Label(parent, text="Final size", style=BODY_LABEL_STYLE).grid(row=4, column=0, sticky="w", pady=(6, 2))
        self.final_dimensions_label = ttk.Label(
            parent,
            text=self._compute_final_size_text(),
            style="Dark.TLabel",
        )
        self.final_dimensions_label.grid(row=4, column=1, columnspan=3, sticky="w", pady=(6, 2))

        for col in range(4):
            parent.columnconfigure(col, weight=1 if col in (1, 3) else 0)

    def load_from_config(self, cfg: dict[str, Any]) -> None:
        section = (cfg or {}).get("upscale", {}) or {}
        upscaler_name = section.get("upscaler", "")
        # Find display name for the stored upscaler name
        upscaler_display = next((d for d, n in self._upscaler_name_map.items() if n == upscaler_name), upscaler_name)
        self.upscaler_var.set(upscaler_display)
        self.mode_var.set(section.get("upscale_mode", "single"))
        self.steps_var.set(int(self._safe_int(section.get("steps", 20), 20)))
        self.denoise_var.set(float(self._safe_float(section.get("denoising_strength", 0.35), 0.35)))
        self.factor_var.set(float(self._safe_float(section.get("upscaling_resize", section.get("upscale_factor", 2.0)), 2.0)))
        self.tile_size_var.set(int(self._safe_int(section.get("tile_size", 0), 0)))
        self.face_restore_var.set(bool(section.get("face_restore", False)))

    def to_config_dict(self) -> dict[str, Any]:
        upscaler_name = self._upscaler_name_map.get(self.upscaler_var.get(), self.upscaler_var.get().strip())
        return {
            "upscale": {
                "upscaler": upscaler_name,
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

    def apply_resource_update(self, resources: dict[str, list[Any]] | None) -> None:
        if not resources:
            return
        upscaler_entries = resources.get("upscalers") or []
        values, mapping = self._normalize_dropdown_entries(upscaler_entries)
        self._upscaler_name_map = mapping
        self._set_combo_values(self.upscaler_combo, self.upscaler_var, values)

    @staticmethod
    def _normalize_dropdown_entries(entries: list[Any]) -> tuple[list[str], dict[str, str]]:
        seen: set[str] = set()
        values: list[str] = []
        mapping: dict[str, str] = {}
        for entry in entries:
            display = getattr(entry, "display_name", None) or getattr(entry, "name", None) or str(entry)
            display = str(display).strip()
            if not display or display in seen:
                continue
            seen.add(display)
            values.append(display)
            mapping[display] = getattr(entry, "name", display)
        return values, mapping

    @staticmethod
    def _set_combo_values(combo: ttk.Combobox, var: tk.StringVar, values: list[str]) -> None:
        combo["values"] = values
        if values:
            current = var.get()
            if current in values:
                var.set(current)
            else:
                var.set(values[0])
        else:
            var.set("")

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

    def update_input_dimensions(self, width: int, height: int) -> None:
        """Update the input dimensions and recalculate final size."""
        self.current_input_width = width
        self.current_input_height = height
        self._update_final_dimensions_display()

    def _on_factor_changed(self, *args: Any) -> None:
        """Update final dimensions when upscale factor changes."""
        self._update_final_dimensions_display()

    def _compute_final_size_text(self) -> str:
        """Compute the final size text based on current input dimensions and factor."""
        try:
            factor = float(self.factor_var.get())
            if self.current_input_width <= 0 or self.current_input_height <= 0:
                return "— x —"
            final_width = int(self.current_input_width * factor)
            final_height = int(self.current_input_height * factor)
            if final_width <= 0 or final_height <= 0:
                return "— x —"
            return f"{final_width}x{final_height}"
        except Exception:
            return "— x —"

    def _update_final_dimensions_display(self) -> None:
        """Update the final dimensions label based on current input and factor."""
        if self.final_dimensions_label is None:
            return
        self.final_dimensions_label.config(text=self._compute_final_size_text())
