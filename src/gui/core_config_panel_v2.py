"""Core configuration panel for GUI V2."""

from __future__ import annotations

import math
import tkinter as tk
from collections.abc import Iterable
from tkinter import ttk

from src.config import app_config
from src.gui.stage_cards_v2.base_stage_card_v2 import BaseStageCardV2
from src.gui.theme_v2 import BODY_LABEL_STYLE


class CoreConfigPanelV2(BaseStageCardV2):
    """Expose core pipeline fields (model, sampler, steps, cfg, resolution).

    When embed_mode=True, widgets are built directly into the master frame
    without creating the standard card structure (no header, no body_frame wrapper).
    """

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
        embed_mode: bool = False,
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
        self._embed_mode = embed_mode

        self.model_var = tk.StringVar(value=app_config.get_core_model_name())
        self.vae_var = tk.StringVar(value=app_config.get_core_vae_name())
        self.sampler_var = tk.StringVar(value=app_config.get_core_sampler_name())
        self.steps_var = tk.StringVar(value=str(app_config.get_core_steps()))
        self.cfg_var = tk.StringVar(value=str(app_config.get_core_cfg_scale()))
        self.width_var = tk.StringVar(value="768")
        self.height_var = tk.StringVar(value="768")
        self.resolution_preset_var = tk.StringVar(value="768x768 (1:1)")

        self._model_combo: ttk.Combobox | None = None
        self._vae_combo: ttk.Combobox | None = None
        self._sampler_combo: ttk.Combobox | None = None
        self._preset_combo: ttk.Combobox | None = None
        self._preset_map: dict[str, tuple[int, int]] = {
            "512x512 (1:1)": (512, 512),
            "640x640 (1:1)": (640, 640),
            "768x768 (1:1)": (768, 768),
            "832x1216 (3:4)": (832, 1216),
            "896x1152 (7:9)": (896, 1152),
            "1024x1024 (1:1)": (1024, 1024),
            "1152x896 (9:7)": (1152, 896),
        }
        self._preset_reverse_map = {sizes: label for label, sizes in self._preset_map.items()}

        if embed_mode:
            # PR-GUI-H: In embed mode, skip BaseStageCardV2 init and build directly into master
            ttk.Frame.__init__(self, master)
            self._title = "Core Config"
            self._description = None
            self._show_header = False
            self.body_frame = self  # Widgets go directly into self
            self._build_body(self)
        else:
            super().__init__(master, title="Core Config", show_header=show_header, **kwargs)

    def _build_body(self, parent: ttk.Frame) -> None:
        parent.columnconfigure(0, weight=0)
        parent.columnconfigure(1, weight=1)
        parent.columnconfigure(2, weight=0)
        parent.columnconfigure(3, weight=0)
        parent.columnconfigure(4, weight=0)
        parent.columnconfigure(5, weight=0)

        row_idx = 0
        self._model_combo = self._build_combo(parent, self.model_var, [])
        if self._models:
            self._model_combo["values"] = tuple(self._models)
        else:
            self._model_combo["values"] = tuple(
                self._names_from_adapter(self._model_adapter, "get_model_names")
            )
        self._build_full_width_row(parent, "Model", self._model_combo, row_idx)
        row_idx += 1

        if self._include_vae:
            self._vae_combo = self._build_combo(parent, self.vae_var, [])
            if self._vaes:
                self._vae_combo["values"] = tuple(self._vaes)
            else:
                self._vae_combo["values"] = tuple(
                    self._names_from_adapter(self._vae_adapter, "get_vae_names")
                )
            self._build_full_width_row(parent, "VAE", self._vae_combo, row_idx)
            row_idx += 1

        self._sampler_combo = self._build_combo(parent, self.sampler_var, [])
        if self._samplers:
            self._sampler_combo["values"] = tuple(self._samplers)
        else:
            self._sampler_combo["values"] = tuple(
                self._names_from_adapter(self._sampler_adapter, "get_sampler_names")
            )
        self._build_sampler_row(parent, row_idx)
        row_idx += 1
        self._build_resolution_row(parent, row_idx)

    def _on_resolution_preset_selected(self, event: object = None) -> None:
        preset = self.resolution_preset_var.get()
        entry = self._preset_map.get(preset)
        if entry:
            width, height = entry
        else:
            width, height = self._parse_preset_label(preset)
        self.width_var.set(str(width))
        self.height_var.set(str(height))

    def _on_refresh(self) -> None:
        self.refresh_from_adapters()

    def refresh_from_adapters(self) -> None:
        """Refresh dropdown values using the configured adapters."""
        try:
            models = self._names_from_adapter(self._model_adapter, "get_model_names", "list_models")
            vaes = self._names_from_adapter(self._vae_adapter, "get_vae_names", "list_vaes")
            samplers = self._names_from_adapter(
                self._sampler_adapter, "get_sampler_names", "get_available_samplers"
            )
            self._update_combo(self._model_combo, self.model_var, models)
            self._update_combo(self._vae_combo, self.vae_var, vaes)
            self._update_combo(self._sampler_combo, self.sampler_var, samplers)
        except Exception:
            pass

    def _names_from_adapter(
        self,
        adapter: object | None,
        adapter_method_name: str,
        controller_method_name: str | None = None,
    ) -> list[str]:
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
                            if hasattr(item, "display_name") and item.display_name:
                                # WebUIResource objects (models, vaes)
                                names.append(str(item.display_name))
                            elif hasattr(item, "name") and item.name:
                                # WebUIResource objects (fallback)
                                names.append(str(item.name))
                            else:
                                # Strings or other objects (samplers)
                                names.append(str(item))
                        return [name for name in names if name]
                except Exception:
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
        except Exception:
            return []

    def _update_combo(
        self, combo: ttk.Combobox | None, variable: tk.StringVar, values: Iterable[str]
    ) -> None:
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

    def _build_full_width_row(
        self, parent: ttk.Frame, label: str, widget: tk.Widget, row_idx: int
    ) -> None:
        label_widget = ttk.Label(parent, text=label, style=BODY_LABEL_STYLE)
        label_widget.grid(row=row_idx, column=0, sticky="w", padx=(0, 8), pady=(0, 4))
        widget.grid(row=row_idx, column=1, columnspan=5, sticky="ew", pady=(0, 4))

    def _build_sampler_row(self, parent: ttk.Frame, row_idx: int) -> None:
        sampler_label = ttk.Label(parent, text="Sampler", style=BODY_LABEL_STYLE)
        sampler_label.grid(row=row_idx, column=0, sticky="w", padx=(0, 4), pady=(0, 4))
        self._sampler_combo.grid(row=row_idx, column=1, sticky="w", padx=(0, 4), pady=(0, 4))
        try:
            self._sampler_combo.configure(width=20)
        except Exception:
            pass

        steps_label = ttk.Label(parent, text="Steps", style=BODY_LABEL_STYLE)
        steps_label.grid(row=row_idx, column=2, sticky="w", padx=(0, 4), pady=(0, 4))
        steps_spin = self._build_spin(parent, self.steps_var, from_=1, to=200, increment=1, width=4)
        steps_spin.grid(row=row_idx, column=3, sticky="ew", padx=(0, 16), pady=(0, 4))
        try:
            steps_spin.configure(width=6)
        except Exception:
            pass

        cfg_label = ttk.Label(parent, text="CFG", style=BODY_LABEL_STYLE)
        cfg_label.grid(row=row_idx, column=4, sticky="w", padx=(0, 4), pady=(0, 4))
        cfg_spin = self._build_spin(
            parent, self.cfg_var, from_=0.0, to=30.0, increment=0.5, width=4
        )
        cfg_spin.grid(row=row_idx, column=5, sticky="ew", pady=(0, 4))

    def _build_resolution_row(self, parent: ttk.Frame, row_idx: int) -> None:
        preset_label = ttk.Label(parent, text="Preset", style=BODY_LABEL_STYLE)
        preset_label.grid(row=row_idx, column=0, sticky="w", padx=(0, 4), pady=(0, 4))
        self._preset_combo = self._build_combo(
            parent, self.resolution_preset_var, tuple(self._preset_map.keys())
        )
        self._preset_combo.grid(row=row_idx, column=1, sticky="ew", padx=(0, 16), pady=(0, 4))
        self._preset_combo.bind("<<ComboboxSelected>>", self._on_resolution_preset_selected)

        width_label = ttk.Label(parent, text="Width", style=BODY_LABEL_STYLE)
        width_label.grid(row=row_idx, column=2, sticky="w", padx=(0, 4), pady=(0, 4))
        width_values = [str(i) for i in range(256, 2049, 128)]
        width_combo = self._build_combo(parent, self.width_var, width_values)
        width_combo.grid(row=row_idx, column=3, sticky="ew", padx=(0, 16), pady=(0, 4))
        try:
            width_combo.configure(width=8)
        except Exception:
            pass

        height_label = ttk.Label(parent, text="Height", style=BODY_LABEL_STYLE)
        height_label.grid(row=row_idx, column=4, sticky="w", padx=(0, 4), pady=(0, 4))
        height_values = [str(i) for i in range(256, 2049, 128)]
        height_combo = self._build_combo(parent, self.height_var, height_values)
        height_combo.grid(row=row_idx, column=5, sticky="ew", pady=(0, 4))
        try:
            height_combo.configure(width=8)
        except Exception:
            pass

    @staticmethod
    def _format_ratio(width: int, height: int) -> str:
        if width <= 0 or height <= 0:
            return "1:1"
        divisor = math.gcd(width, height) or 1
        return f"{width // divisor}:{height // divisor}"

    def _build_combo(
        self, parent: ttk.Frame, variable: tk.StringVar, values: Iterable[str]
    ) -> ttk.Combobox:
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
        width: int | None = None,
    ) -> ttk.Spinbox:
        spin_kwargs = {
            "from_": from_,
            "to": to,
            "increment": increment,
            "textvariable": variable,
            "style": "Dark.TSpinbox",
        }
        if width:
            spin_kwargs["width"] = width
        return ttk.Spinbox(parent, **spin_kwargs)

    def get_overrides(self) -> dict[str, object]:
        """Return current core config overrides as a dict suitable for GuiOverrides."""

        width = self._safe_int(self.width_var.get(), 768)
        height = self._safe_int(self.height_var.get(), 768)
        preset = self._preset_value_from_label(self.resolution_preset_var.get())
        return {
            "model": self.model_var.get().strip(),
            "sampler": self.sampler_var.get().strip(),
            "steps": self._safe_int(self.steps_var.get(), 20),
            "cfg_scale": self._safe_float(self.cfg_var.get(), 7.0),
            "resolution_preset": preset,
            "width": width,
            "height": height,
            "ratio": self._format_ratio(width, height),
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
        if preset:
            label = self._preset_label_from_value(str(preset))
            self.resolution_preset_var.set(label)
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

    def _preset_value_from_label(self, label: str) -> str:
        return label.split(" ", 1)[0]

    def _preset_label_from_value(self, value: str) -> str:
        try:
            width, height = map(int, value.split("x"))
        except Exception:
            return value
        return self._preset_reverse_map.get(
            (width, height), f"{width}x{height} ({self._format_ratio(width, height)})"
        )

    def _parse_preset_label(self, label: str) -> tuple[int, int]:
        try:
            base = label.split(" ", 1)[0]
            width, height = map(int, base.split("x"))
            return width, height
        except Exception:
            return 768, 768


__all__ = ["CoreConfigPanelV2"]
