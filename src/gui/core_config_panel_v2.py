"""Core configuration panel for GUI V2."""

from __future__ import annotations

import tkinter as tk
from tkinter import ttk
from typing import Iterable

from src.config import app_config
from src.gui.resolution_panel_v2 import ResolutionPanelV2


class CoreConfigPanelV2(ttk.Frame):
    """Expose core pipeline fields (model, sampler, steps, cfg, resolution)."""

    def __init__(
        self,
        master: tk.Misc,
        *,
        models: Iterable[str] | None = None,
        vaes: Iterable[str] | None = None,
        samplers: Iterable[str] | None = None,
        show_label: bool = True,
        include_vae: bool = False,
        include_refresh: bool = False,
        model_adapter: object = None,
        vae_adapter: object = None,
        sampler_adapter: object = None,
    ) -> None:
        super().__init__(master, style="Panel.TFrame", padding=8)

        # Vars seeded from app_config defaults
        self.model_var = tk.StringVar(value=app_config.get_core_model_name())
        self.vae_var = tk.StringVar(value=app_config.get_core_vae_name())
        self.sampler_var = tk.StringVar(value=app_config.get_core_sampler_name())
        self.steps_var = tk.StringVar(value=str(app_config.get_core_steps()))
        self.cfg_var = tk.StringVar(value=str(app_config.get_core_cfg_scale()))

        self._model_adapter = model_adapter
        self._vae_adapter = vae_adapter
        self._sampler_adapter = sampler_adapter

        if show_label:
            ttk.Label(self, text="Core Config", style="Heading.TLabel").grid(row=0, column=0, columnspan=3, sticky="w", pady=(0, 6))

        self._model_combo: ttk.Combobox | None = None
        self._vae_combo: ttk.Combobox | None = None
        self._sampler_combo: ttk.Combobox | None = None
        row_idx = 1
        self._model_combo = self._build_combo(self.model_var, [])
        if models:
            self._model_combo["values"] = tuple(models)
        else:
            self._model_combo["values"] = tuple(self._names_from_adapter(self._model_adapter, "get_model_names"))
        self._build_row("Model", self._model_combo, row_idx)
        row_idx += 1
        if include_vae:
            self._vae_combo = self._build_combo(self.vae_var, [])
            if vaes:
                self._vae_combo["values"] = tuple(vaes)
            else:
                self._vae_combo["values"] = tuple(self._names_from_adapter(self._vae_adapter, "get_vae_names"))
            self._build_row("VAE", self._vae_combo, row_idx)
            if include_refresh:
                refresh_btn = ttk.Button(self, text="Refresh", style="Primary.TButton", command=self._on_refresh)
                refresh_btn.grid(row=row_idx, column=2, sticky="e", padx=(8, 0), pady=(0, 4))
            row_idx += 1
        self._sampler_combo = self._build_combo(self.sampler_var, [])
        if samplers:
            self._sampler_combo["values"] = tuple(samplers)
        else:
            self._sampler_combo["values"] = tuple(self._names_from_adapter(self._sampler_adapter, "get_sampler_names"))
        self._build_row("Sampler", self._sampler_combo, row_idx)
        row_idx += 1
        self._build_row("Steps", self._build_spin(self.steps_var, from_=1, to=200, increment=1), row_idx)
        row_idx += 1
        self._build_row("CFG", self._build_spin(self.cfg_var, from_=0.0, to=30.0, increment=0.5), row_idx)
        row_idx += 1

        # Resolution sub-panel
        self.resolution_panel = ResolutionPanelV2(self)
        self.resolution_var = self.resolution_panel.preset_var
        self.resolution_panel.grid(row=row_idx, column=0, columnspan=3, sticky="ew", pady=(4, 0))

        self.columnconfigure(1, weight=1)
        self.columnconfigure(2, weight=1)

    def _on_refresh(self) -> None:
        self.refresh_from_adapters()

    def refresh_from_adapters(self) -> None:
        """Refresh dropdown values using the configured adapters."""
        try:
            models = self._names_from_adapter(self._model_adapter, "get_model_names")
            vaes = self._names_from_adapter(self._vae_adapter, "get_vae_names")
            samplers = self._names_from_adapter(self._sampler_adapter, "get_sampler_names")
            self._update_combo(self._model_combo, self.model_var, models)
            self._update_combo(self._vae_combo, self.vae_var, vaes)
            self._update_combo(self._sampler_combo, self.sampler_var, samplers)
        except Exception:
            pass

    def _names_from_adapter(self, adapter: object | None, method_name: str) -> list[str]:
        if adapter is None:
            return []
        method = getattr(adapter, method_name, None)
        if method is None or not callable(method):
            return []
        try:
            return [str(name) for name in (method() or []) if name]
        except Exception:
            return []

    def _update_combo(self, combo: ttk.Combobox | None, variable: tk.StringVar, values: Iterable[str]) -> None:
        if combo is None:
            return
        current = variable.get()
        new_values = tuple(values)
        combo["values"] = new_values
        if current in new_values:
            variable.set(current)
        elif new_values:
            variable.set(new_values[0])
        else:
            variable.set("")

    def _build_row(self, label: str, widget: tk.Widget, row_idx: int) -> None:
        label_widget = ttk.Label(self, text=label, style="Dark.TLabel")
        label_widget.grid(row=row_idx, column=0, sticky="w", padx=(0, 8), pady=(0, 4))
        widget.grid(row=row_idx, column=1, sticky="ew", pady=(0, 4))

    def _build_combo(self, variable: tk.StringVar, values: Iterable[str]) -> ttk.Combobox:
        combo = ttk.Combobox(
            self,
            textvariable=variable,
            values=tuple(values),
            state="readonly",
            style="Dark.TCombobox"
        )
        return combo

    def _build_spin(self, variable: tk.StringVar, *, from_: float, to: float, increment: float) -> ttk.Spinbox:
        spin = ttk.Spinbox(
            self,
            from_=from_,
            to=to,
            increment=increment,
            textvariable=variable,
            style="Dark.TEntry"
        )
        return spin

    def get_overrides(self) -> dict[str, object]:
        """Return current core config overrides as a dict suitable for GuiOverrides."""

        width, height = self.resolution_panel.get_resolution() if self.resolution_panel else (512, 512)
        preset = self.resolution_panel.get_preset_label() if self.resolution_panel else ""
        if preset:
            try:
                w_str, h_str = preset.lower().replace(" ", "").split("x", 1)
                width = int(w_str)
                height = int(h_str)
            except Exception:
                pass
        return {
            "model": self.model_var.get().strip(),
            "sampler": self.sampler_var.get().strip(),
            "steps": self._safe_int(self.steps_var.get(), 20),
            "cfg_scale": self._safe_float(self.cfg_var.get(), 7.0),
            "resolution_preset": preset,
            "width": width,
            "height": height,
        }

    def apply_from_overrides(self, overrides: dict[str, object]) -> None:
        if not overrides:
            return
        self.model_var.set(str(overrides.get("model", self.model_var.get())))
        self.sampler_var.set(str(overrides.get("sampler", self.sampler_var.get())))
        self.steps_var.set(str(overrides.get("steps", self.steps_var.get())))
        self.cfg_var.set(str(overrides.get("cfg_scale", self.cfg_var.get())))
        width = overrides.get("width")
        height = overrides.get("height")
        preset = overrides.get("resolution_preset")
        if self.resolution_panel:
            if preset:
                self.resolution_panel.apply_preset(str(preset))
            if width is not None and height is not None:
                try:
                    self.resolution_panel.set_resolution(int(float(str(width))), int(float(str(height))))
                except Exception:
                    pass

    @staticmethod
    def _safe_int(value: object, default: int) -> int:
        try:
            return int(float(str(value)))
        except Exception:
            return default

    @staticmethod
    def _safe_float(value: object, default: float) -> float:
        try:
            return float(str(value))
        except Exception:
            return default


__all__ = ["CoreConfigPanelV2"]
