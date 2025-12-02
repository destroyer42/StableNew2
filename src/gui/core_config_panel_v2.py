"""Core configuration panel for GUI V2."""

from __future__ import annotations

import tkinter as tk
from tkinter import ttk
from typing import Iterable

from src.config import app_config
from src.gui.stage_cards_v2.base_stage_card_v2 import BaseStageCardV2
from src.gui.theme_v2 import BODY_LABEL_STYLE, PRIMARY_BUTTON_STYLE


class CoreConfigPanelV2(BaseStageCardV2):
    """Expose core pipeline fields (model, sampler, steps, cfg, resolution)."""

    def __init__(
        self,
        master: tk.Misc,
        *,
        models: Iterable[str] | None = None,
        vaes: Iterable[str] | None = None,
        samplers: Iterable[str] | None = None,
        include_vae: bool = False,
        include_refresh: bool = False,
        model_adapter: object | None = None,
        vae_adapter: object | None = None,
        sampler_adapter: object | None = None,
        controller: object | None = None,
        show_header: bool = True,
        **kwargs: object,
    ) -> None:
        self._include_vae = include_vae
        self._include_refresh = include_refresh
        self._model_adapter = model_adapter
        self._vae_adapter = vae_adapter
        self._sampler_adapter = sampler_adapter
        self._controller = controller
        self._models = models
        self._vaes = vaes
        self._samplers = samplers

        self.model_var = tk.StringVar(value=app_config.get_core_model_name())
        self.vae_var = tk.StringVar(value=app_config.get_core_vae_name())
        self.sampler_var = tk.StringVar(value=app_config.get_core_sampler_name())
        self.steps_var = tk.StringVar(value=str(app_config.get_core_steps()))
        self.cfg_var = tk.StringVar(value=str(app_config.get_core_cfg_scale()))
        self.width_var = tk.StringVar(value="768")
        self.height_var = tk.StringVar(value="768")
        self.resolution_preset_var = tk.StringVar(value="768x768")
        self.ratio_var = tk.StringVar(value="1:1")

        self._model_combo: ttk.Combobox | None = None
        self._vae_combo: ttk.Combobox | None = None
        self._sampler_combo: ttk.Combobox | None = None

        super().__init__(master, title="Core Config", show_header=show_header, **kwargs)

    def _build_body(self, parent: ttk.Frame) -> None:
        parent.columnconfigure(0, weight=0)
        parent.columnconfigure(1, weight=1)
        parent.columnconfigure(2, weight=0)
        parent.columnconfigure(3, weight=1)

        row_idx = 0
        self._model_combo = self._build_combo(parent, self.model_var, [])
        if self._models:
            self._model_combo["values"] = tuple(self._models)
        else:
            self._model_combo["values"] = tuple(self._names_from_adapter(self._model_adapter, "get_model_names"))
        self._build_row(parent, "Model", self._model_combo, row_idx)
        row_idx += 1

        if self._include_vae:
            self._vae_combo = self._build_combo(parent, self.vae_var, [])
            if self._vaes:
                self._vae_combo["values"] = tuple(self._vaes)
            else:
                self._vae_combo["values"] = tuple(self._names_from_adapter(self._vae_adapter, "get_vae_names"))
            self._build_row(parent, "VAE", self._vae_combo, row_idx)
            row_idx += 1

        self._sampler_combo = self._build_combo(parent, self.sampler_var, [])
        if self._samplers:
            self._sampler_combo["values"] = tuple(self._samplers)
        else:
            self._sampler_combo["values"] = tuple(self._names_from_adapter(self._sampler_adapter, "get_sampler_names"))
        self._build_row(parent, "Sampler", self._sampler_combo, row_idx)
        row_idx += 1

        self._build_row(
            parent,
            "Steps",
            self._build_spin(parent, self.steps_var, from_=1, to=200, increment=1),
            row_idx,
        )
        row_idx += 1
        self._build_row(
            parent,
            "CFG",
            self._build_spin(parent, self.cfg_var, from_=0.0, to=30.0, increment=0.5),
            row_idx,
        )
        row_idx += 1

        # Width and height controls share additional columns
        width_label = ttk.Label(parent, text="Width", style=BODY_LABEL_STYLE)
        width_label.grid(row=row_idx, column=0, sticky="w", padx=(0, 8), pady=(0, 4))
        width_values = [str(i) for i in range(256, 2049, 128)]
        width_combo = self._build_combo(parent, self.width_var, width_values)
        width_combo.grid(row=row_idx, column=1, sticky="ew", pady=(0, 4))

        height_label = ttk.Label(parent, text="Height", style=BODY_LABEL_STYLE)
        height_label.grid(row=row_idx, column=2, sticky="w", padx=(8, 8), pady=(0, 4))
        height_values = [str(i) for i in range(256, 2049, 128)]
        height_combo = self._build_combo(parent, self.height_var, height_values)
        height_combo.grid(row=row_idx, column=3, sticky="ew", pady=(0, 4))
        row_idx += 1

        preset_label = ttk.Label(parent, text="Preset", style=BODY_LABEL_STYLE)
        preset_label.grid(row=row_idx, column=0, sticky="w", padx=(0, 8), pady=(0, 4))
        preset_combo = self._build_combo(
            parent,
            self.resolution_preset_var,
            ["512x512", "640x640", "768x768", "832x1216", "896x1152", "1024x1024", "1152x896"],
        )
        preset_combo.grid(row=row_idx, column=1, sticky="ew", pady=(0, 4))
        preset_combo.bind("<<ComboboxSelected>>", self._on_resolution_preset_selected)

        ratio_label = ttk.Label(parent, text="Ratio", style=BODY_LABEL_STYLE)
        ratio_label.grid(row=row_idx, column=2, sticky="w", padx=(8, 8), pady=(0, 4))
        ratio_combo = self._build_combo(
            parent,
            self.ratio_var,
            ["1:1", "4:3", "3:4", "16:9", "9:16", "21:9", "9:21"],
        )
        ratio_combo.grid(row=row_idx, column=3, sticky="ew", pady=(0, 4))
        row_idx += 1

    def _on_resolution_preset_selected(self, event: object = None) -> None:
        preset = self.resolution_preset_var.get()
        if preset in ["512x512", "640x640", "768x768", "832x1216", "896x1152", "1024x1024", "1152x896"]:
            width, height = map(int, preset.split("x"))
            self.width_var.set(str(width))
            self.height_var.set(str(height))

    def _on_refresh(self) -> None:
        self.refresh_from_adapters()

    def refresh_from_adapters(self) -> None:
        """Refresh dropdown values using the configured adapters."""
        try:
            models = self._names_from_adapter(self._model_adapter, "get_model_names", "list_models")
            vaes = self._names_from_adapter(self._vae_adapter, "get_vae_names", "list_vaes")
            samplers = self._names_from_adapter(self._sampler_adapter, "get_sampler_names", "get_available_samplers")
            self._update_combo(self._model_combo, self.model_var, models)
            self._update_combo(self._vae_combo, self.vae_var, vaes)
            self._update_combo(self._sampler_combo, self.sampler_var, samplers)
        except Exception as e:
            pass

    def _names_from_adapter(self, adapter: object | None, adapter_method_name: str, controller_method_name: str | None = None) -> list[str]:
        # First try controller methods (preferred for consistency with stage cards)
        if self._controller is not None and controller_method_name is not None:
            controller_method = getattr(self._controller, controller_method_name, None)
            if controller_method is not None and callable(controller_method):
                try:
                    result = controller_method()
                    if result:
                        # Handle different return types from controller methods
                        names = []
                        for item in result:
                            if hasattr(item, 'display_name') and item.display_name:
                                # WebUIResource objects (models, vaes)
                                names.append(str(item.display_name))
                            elif hasattr(item, 'name') and item.name:
                                # WebUIResource objects (fallback)
                                names.append(str(item.name))
                            else:
                                # Strings or other objects (samplers)
                                names.append(str(item))
                        return [name for name in names if name]
                except Exception as e:
                    pass
        
        # Fall back to adapter methods
        if adapter is None:
            return []
        method = getattr(adapter, adapter_method_name, None)
        if method is None or not callable(method):
            return []
        try:
            result = method()
            names = [str(name) for name in (result or []) if name]
            return names
        except Exception as e:
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

    def _build_row(self, parent: ttk.Frame, label: str, widget: tk.Widget, row_idx: int) -> None:
        label_widget = ttk.Label(parent, text=label, style=BODY_LABEL_STYLE)
        label_widget.grid(row=row_idx, column=0, sticky="w", padx=(0, 8), pady=(0, 4))
        widget.grid(row=row_idx, column=1, sticky="ew", pady=(0, 4))

    def _build_combo(self, parent: ttk.Frame, variable: tk.StringVar, values: Iterable[str]) -> ttk.Combobox:
        combo = ttk.Combobox(
            parent,
            textvariable=variable,
            values=tuple(values),
            state="readonly",
            style="Dark.TCombobox",
        )
        return combo

    def _build_spin(
        self,
        parent: ttk.Frame,
        variable: tk.StringVar,
        *,
        from_: float,
        to: float,
        increment: float,
    ) -> ttk.Spinbox:
        spin = ttk.Spinbox(
            parent,
            from_=from_,
            to=to,
            increment=increment,
            textvariable=variable,
        )
        return spin

    def get_overrides(self) -> dict[str, object]:
        """Return current core config overrides as a dict suitable for GuiOverrides."""

        width = self._safe_int(self.width_var.get(), 768)
        height = self._safe_int(self.height_var.get(), 768)
        preset = self.resolution_preset_var.get().strip()
        return {
            "model": self.model_var.get().strip(),
            "sampler": self.sampler_var.get().strip(),
            "steps": self._safe_int(self.steps_var.get(), 20),
            "cfg_scale": self._safe_float(self.cfg_var.get(), 7.0),
            "resolution_preset": preset,
            "width": width,
            "height": height,
            "ratio": self.ratio_var.get().strip(),
        }

    def apply_from_overrides(self, overrides: dict[str, object]) -> None:
        if not overrides:
            return
        self.model_var.set(str(overrides.get("model", self.model_var.get())))
        self.sampler_var.set(str(overrides.get("sampler", self.sampler_var.get())))
        self.steps_var.set(str(overrides.get("steps", self.steps_var.get())))
        self.cfg_var.set(str(overrides.get("cfg_scale", self.cfg_var.get())))
        ratio = overrides.get("ratio")
        if ratio:
            self.ratio_var.set(str(ratio))
        width = overrides.get("width")
        height = overrides.get("height")
        preset = overrides.get("resolution_preset")
        if preset:
            self.resolution_preset_var.set(str(preset))
            self._on_resolution_preset_selected()
        if width is not None and height is not None:
            try:
                self.width_var.set(str(int(float(str(width)))))
                self.height_var.set(str(int(float(str(height)))))
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
