"""Output settings panel for GUI V2."""

from __future__ import annotations

import tkinter as tk
from tkinter import ttk

from src.config import app_config
from src.gui.theme_v2 import HEADING_LABEL_STYLE


class OutputSettingsPanelV2(ttk.Frame):
    """Expose output directory/profile, filename pattern, batch size, image format, seed mode."""

    FORMATS = ("png", "jpg", "webp")
    SEED_MODES = ("fixed", "increment", "random")

    def __init__(self, master: tk.Misc) -> None:
        super().__init__(master, style="Panel.TFrame", padding=8)
        ttk.Label(self, text="Output Settings", style=HEADING_LABEL_STYLE).grid(row=0, column=0, columnspan=2, sticky="w", pady=(0, 6))

        self.output_dir_var = tk.StringVar(value=app_config.output_dir_default())
        self.filename_pattern_var = tk.StringVar(value=app_config.filename_pattern_default())
        self.image_format_var = tk.StringVar(value=app_config.image_format_default())
        self.batch_size_var = tk.StringVar(value=str(app_config.batch_size_default()))
        self.seed_mode_var = tk.StringVar(value=app_config.seed_mode_default())

        self._build_row("Output Dir", ttk.Entry(self, textvariable=self.output_dir_var), 1)
        self._build_row("Filename", ttk.Entry(self, textvariable=self.filename_pattern_var), 2)
        self._build_row(
            "Format",
            ttk.Combobox(self, textvariable=self.image_format_var, values=self.FORMATS, state="readonly", width=8),
            3
        )
        self._build_row(
            "Batch Size",
            ttk.Spinbox(self, from_=1, to=99, increment=1, textvariable=self.batch_size_var, width=6),
            4
        )
        self._build_row(
            "Seed Mode",
            ttk.Combobox(self, textvariable=self.seed_mode_var, values=self.SEED_MODES, state="readonly", width=10),
            5
        )

        self.columnconfigure(1, weight=1)

    def _build_row(self, label: str, widget: tk.Widget, row_idx: int) -> None:
        label_widget = ttk.Label(self, text=label, style="TLabel")
        label_widget.grid(row=row_idx, column=0, sticky="w", padx=(0, 8), pady=(0, 4))
        widget.grid(row=row_idx, column=1, sticky="ew", pady=(0, 4))

    def get_output_overrides(self) -> dict[str, object]:
        return {
            "output_dir": self.output_dir_var.get().strip(),
            "filename_pattern": self.filename_pattern_var.get().strip(),
            "image_format": self.image_format_var.get().strip(),
            "batch_size": self._safe_int(self.batch_size_var.get(), app_config.batch_size_default()),
            "seed_mode": self.seed_mode_var.get().strip(),
        }

    def apply_from_overrides(self, overrides: dict[str, object]) -> None:
        if not overrides:
            return
        self.output_dir_var.set(str(overrides.get("output_dir", self.output_dir_var.get())))
        self.filename_pattern_var.set(str(overrides.get("filename_pattern", self.filename_pattern_var.get())))
        fmt = overrides.get("image_format")
        if fmt:
            self.image_format_var.set(str(fmt))
        batch = overrides.get("batch_size")
        if batch is not None:
            try:
                self.batch_size_var.set(str(int(float(str(batch)))))
            except Exception:
                pass
        seed = overrides.get("seed_mode")
        if seed:
            self.seed_mode_var.set(str(seed))

    @staticmethod
    def _safe_int(value: object, default: int) -> int:
        try:
            return int(float(str(value)))
        except Exception:
            return default


__all__ = ["OutputSettingsPanelV2"]
