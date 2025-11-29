"""img2img stage card for PipelinePanelV2."""

from __future__ import annotations

import tkinter as tk
from tkinter import ttk

from . import theme as theme_mod


class Img2ImgStageCard(ttk.Frame):
    """Stage card managing img2img fields."""

    FIELD_NAMES = [
        "model",
        "vae",
        "sampler_name",
        "denoising_strength",
        "cfg_scale",
        "steps",
    ]

    def __init__(self, master: tk.Misc, *, controller=None, theme=None, **kwargs) -> None:
        style_name = getattr(theme, "SURFACE_FRAME_STYLE", theme_mod.SURFACE_FRAME_STYLE)
        super().__init__(master, style=style_name, padding=theme_mod.PADDING_MD, **kwargs)
        self.controller = controller
        self.theme = theme

        header_style = getattr(theme, "STATUS_STRONG_LABEL_STYLE", theme_mod.STATUS_STRONG_LABEL_STYLE)
        self.header_label = ttk.Label(self, text="img2img Settings", style=header_style)
        self.header_label.pack(anchor=tk.W, pady=(0, 4))

        body_style = getattr(theme, "SURFACE_FRAME_STYLE", theme_mod.SURFACE_FRAME_STYLE)
        self.body = ttk.Frame(self, style=body_style)
        self.body.pack(fill=tk.BOTH, expand=True)

        self._vars: dict[str, tk.StringVar] = {}

        for idx, field in enumerate(self.FIELD_NAMES):
            var = tk.StringVar()
            self._vars[field] = var
            if field == "steps":
                self._add_spinbox(self.body, field, var, idx, from_=1, to=200)
            elif field in {"denoising_strength", "cfg_scale"}:
                increment = 0.05 if field == "denoising_strength" else 0.5
                to_value = 1.0 if field == "denoising_strength" else 30.0
                self._add_spinbox(self.body, field, var, idx, from_=0.0, to=to_value, increment=increment)
            else:
                self._add_entry(self.body, field, var, idx)

    def _add_entry(self, parent, label, variable, row):
        ttk.Label(parent, text=label.replace("_", " ").title(), style="Dark.TLabel").grid(
            row=row, column=0, sticky=tk.W, pady=2
        )
        entry = ttk.Entry(parent, textvariable=variable, width=28)
        entry.grid(row=row, column=1, sticky="ew", pady=2)
        parent.columnconfigure(1, weight=1)
        return entry

    def _add_spinbox(self, parent, label, variable, row, *, from_, to, increment=1.0):
        ttk.Label(parent, text=label.replace("_", " ").title(), style="Dark.TLabel").grid(
            row=row, column=0, sticky=tk.W, pady=2
        )
        spin = ttk.Spinbox(
            parent,
            textvariable=variable,
            from_=from_,
            to=to,
            increment=increment,
            width=10,
        )
        spin.grid(row=row, column=1, sticky="ew", pady=2)
        return spin

    def load_from_config(self, config: dict | None) -> None:
        section = self._get_section(config)
        for field in self.FIELD_NAMES:
            self._vars[field].set(self._coerce_str(section.get(field)))

    def to_config_dict(self) -> dict:
        section: dict[str, object] = {}
        for field in self.FIELD_NAMES:
            value = self._vars[field].get()
            if field == "steps":
                converted = self._coerce_int(value)
            elif field in {"denoising_strength", "cfg_scale"}:
                converted = self._coerce_float(value)
            else:
                converted = value.strip() if isinstance(value, str) else ""
                if not converted:
                    converted = None
            if converted not in (None, ""):
                section[field] = converted
        return {"img2img": section} if section else {}

    @staticmethod
    def _get_section(config: dict | None) -> dict:
        if isinstance(config, dict):
            section = config.get("img2img") or {}
            return section if isinstance(section, dict) else {}
        return {}

    @staticmethod
    def _coerce_str(value: object) -> str:
        if value is None:
            return ""
        return str(value)

    @staticmethod
    def _coerce_int(value: object) -> int | None:
        try:
            if value is None or str(value).strip() == "":
                return None
            return int(float(value))
        except (ValueError, TypeError):
            return None

    @staticmethod
    def _coerce_float(value: object) -> float | None:
        try:
            if value is None or str(value).strip() == "":
                return None
            return float(value)
        except (ValueError, TypeError):
            return None
