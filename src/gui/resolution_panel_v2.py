"""Advanced resolution controls for GUI V2."""

from __future__ import annotations

import tkinter as tk
from tkinter import ttk

from src.gui import theme_v2 as theme_mod


class ResolutionPanelV2(ttk.Frame):
    """Expose width/height with presets, ratios, and MP hint."""

    PRESETS: dict[str, tuple[int, int]] = {
        "512x512": (512, 512),
        "640x640": (640, 640),
        "768x768": (768, 768),
        "832x1216": (832, 1216),
        "896x1152": (896, 1152),
        "1024x1024": (1024, 1024),
        "1152x896": (1152, 896),
    }

    RATIOS: dict[str, tuple[int, int]] = {
        "1:1": (1, 1),
        "3:2": (3, 2),
        "16:9": (16, 9),
        "9:16": (9, 16),
    }

    def __init__(
        self,
        master: tk.Misc,
        *,
        theme: object = None,
        presets: dict[str, tuple[int, int]] | None = None,
    ) -> None:
        style_name = theme_mod.SURFACE_FRAME_STYLE
        super().__init__(master, style=style_name, padding=theme_mod.PADDING_MD)
        self.theme = theme or theme_mod
        self.presets = dict(presets or self.PRESETS)

        header_style = theme_mod.STATUS_STRONG_LABEL_STYLE
        ttk.Label(self, text="Resolution", style=header_style).pack(anchor=tk.W, pady=(0, 4))

        self.width_var = tk.StringVar(value=str(self.presets.get("768x768", (768, 768))[0]))
        self.height_var = tk.StringVar(value=str(self.presets.get("768x768", (768, 768))[1]))
        self.preset_var = tk.StringVar(value="768x768" if "768x768" in self.presets else "")
        self.ratio_var = tk.StringVar(value="1:1")

        row = ttk.Frame(self, style=style_name)
        row.pack(fill=tk.X, pady=(0, theme_mod.PADDING_SM))
        ttk.Label(row, text="Width", style=theme_mod.STATUS_LABEL_STYLE).pack(side=tk.LEFT)
        self.width_entry = ttk.Spinbox(
            row,
            from_=64,
            to=4096,
            increment=64,
            textvariable=self.width_var,
            width=8,
            command=self._on_dimension_change,
        )
        self.width_entry.pack(side=tk.LEFT, padx=(4, 8))

        ttk.Label(row, text="Height", style=theme_mod.STATUS_LABEL_STYLE).pack(side=tk.LEFT)
        self.height_entry = ttk.Spinbox(
            row,
            from_=64,
            to=4096,
            increment=64,
            textvariable=self.height_var,
            width=8,
            command=self._on_dimension_change,
        )
        self.height_entry.pack(side=tk.LEFT, padx=(4, 0))

        preset_row = ttk.Frame(self, style=style_name)
        preset_row.pack(fill=tk.X, pady=(0, theme_mod.PADDING_SM))
        ttk.Label(preset_row, text="Preset", style=theme_mod.STATUS_LABEL_STYLE).pack(side=tk.LEFT)
        self.preset_combo = ttk.Combobox(
            preset_row,
            values=tuple(self.presets.keys()),
            textvariable=self.preset_var,
            state="readonly",
            width=12,
        )
        self.preset_combo.pack(side=tk.LEFT, padx=(4, 8))
        self.preset_combo.bind("<<ComboboxSelected>>", self._on_preset_selected)

        ttk.Label(preset_row, text="Ratio", style=theme_mod.STATUS_LABEL_STYLE).pack(side=tk.LEFT)
        self.ratio_combo = ttk.Combobox(
            preset_row,
            values=tuple(self.RATIOS.keys()),
            textvariable=self.ratio_var,
            state="readonly",
            width=8,
        )
        self.ratio_combo.pack(side=tk.LEFT, padx=(4, 0))
        self.ratio_combo.bind("<<ComboboxSelected>>", self._on_ratio_selected)

        self.mp_var = tk.StringVar(value=self._build_mp_label())
        ttk.Label(self, textvariable=self.mp_var, style=theme_mod.STATUS_LABEL_STYLE).pack(
            anchor=tk.W, pady=(theme_mod.PADDING_SM, 0)
        )

        self.width_var.trace_add("write", lambda *_: self._update_mp_label())
        self.height_var.trace_add("write", lambda *_: self._update_mp_label())

    def get_resolution(self) -> tuple[int, int]:
        return self._safe_int(self.width_var.get(), 512), self._safe_int(self.height_var.get(), 512)

    def get_preset_label(self) -> str:
        return self.preset_var.get().strip()

    def set_resolution(self, width: int, height: int, *, preserve_preset: bool = False) -> None:
        if not preserve_preset:
            self.preset_var.set("")
        self.width_var.set(str(int(width)))
        self.height_var.set(str(int(height)))
        self._update_mp_label()

    def apply_preset(self, label: str) -> None:
        dims = self.presets.get(label)
        if not dims:
            return
        self.preset_var.set(label)
        self.set_resolution(*dims, preserve_preset=True)

    def _on_preset_selected(self, _event: object = None) -> None:
        self.apply_preset(self.preset_var.get())

    def _on_ratio_selected(self, _event: object = None) -> None:
        ratio = self.RATIOS.get(self.ratio_var.get())
        if not ratio:
            return
        w = self._safe_int(self.width_var.get(), 512)
        width, height = self._apply_ratio(w, ratio)
        self.set_resolution(width, height)

    def _apply_ratio(self, width: int, ratio: tuple[int, int]) -> tuple[int, int]:
        num, den = ratio
        if num <= 0 or den <= 0:
            return width, self._safe_int(self.height_var.get(), 512)
        height = max(64, int(width * den / num))
        return width, height

    def _on_dimension_change(self) -> None:
        self.preset_var.set("")
        self._update_mp_label()

    def _safe_int(self, value: str, default: int) -> int:
        try:
            return int(value)
        except Exception:
            return default

    def _build_mp_label(self) -> str:
        width, height = self.get_resolution()
        mp = (width * height) / 1_000_000
        return f"Approx {mp:.2f} MP (will clamp to assembler limit)"

    def _update_mp_label(self) -> None:
        try:
            self.mp_var.set(self._build_mp_label())
        except Exception:
            pass


__all__ = ["ResolutionPanelV2"]
