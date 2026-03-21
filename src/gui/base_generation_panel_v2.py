"""Base generation panel for GUI V2."""

from __future__ import annotations

import math
import tkinter as tk
from collections.abc import Callable, Iterable
from tkinter import ttk
from typing import Any

from src.config import app_config
from src.gui.stage_cards_v2.base_stage_card_v2 import BaseStageCardV2
from src.gui.theme_v2 import BODY_LABEL_STYLE, MUTED_LABEL_STYLE


class BaseGenerationPanelV2(BaseStageCardV2):
    """Expose shared image-generation defaults for the active pipeline UI."""

    MIN_DIMENSION = 64
    MAX_DIMENSION = 4096

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
        on_change: Callable[[], None] | None = None,
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
        self._on_change = on_change
        self._sync_enabled = False
        self._model_name_map: dict[str, str] = {}
        self._vae_name_map: dict[str, str] = {"No VAE (model default)": ""}
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

        cfg = self._get_current_config()
        model_name = self._coerce_string(
            getattr(cfg, "model_name", None), app_config.get_core_model_name()
        )
        vae_name = self._coerce_string(
            getattr(cfg, "vae_name", None), app_config.get_core_vae_name()
        )
        sampler_name = self._coerce_string(
            getattr(cfg, "sampler_name", None), app_config.get_core_sampler_name()
        )
        scheduler_name = self._coerce_string(getattr(cfg, "scheduler_name", None), "")
        steps = self._coerce_int(getattr(cfg, "steps", None), app_config.get_core_steps())
        cfg_scale = self._coerce_float(
            getattr(cfg, "cfg_scale", None), app_config.get_core_cfg_scale()
        )
        width = self._coerce_int(getattr(cfg, "width", None), 768)
        height = self._coerce_int(getattr(cfg, "height", None), 768)
        seed = getattr(cfg, "seed", None)

        self.model_var = tk.StringVar(value=str(model_name))
        self.vae_var = tk.StringVar(value=str(vae_name))
        self.sampler_var = tk.StringVar(value=str(sampler_name))
        self.scheduler_var = tk.StringVar(value=str(scheduler_name))
        self.steps_var = tk.IntVar(value=int(steps))
        self.cfg_var = tk.DoubleVar(value=float(cfg_scale))
        subseed = self._coerce_int(getattr(cfg, "subseed", None), -1)
        subseed_strength = self._coerce_float(getattr(cfg, "subseed_strength", None), 0.0)

        self.width_var = tk.StringVar(value=str(int(width)))
        self.height_var = tk.StringVar(value=str(int(height)))
        self.seed_var = tk.StringVar(value="" if seed is None else str(seed))
        self.subseed_var = tk.StringVar(value="" if int(subseed) < 0 else str(int(subseed)))
        self.subseed_strength_var = tk.StringVar(value=str(float(subseed_strength)))
        self.resolution_preset_var = tk.StringVar(
            value=self._preset_label_from_dimensions(int(width), int(height))
        )

        self._model_combo: ttk.Combobox | None = None
        self._vae_combo: ttk.Combobox | None = None
        self._sampler_combo: ttk.Combobox | None = None
        self._scheduler_combo: ttk.Combobox | None = None
        self._preset_combo: ttk.Combobox | None = None
        self._width_combo: ttk.Combobox | None = None
        self._height_combo: ttk.Combobox | None = None
        self._steps_spin: ttk.Spinbox | None = None
        self._cfg_spin: ttk.Spinbox | None = None
        self._helper_label: ttk.Label | None = None
        self._dimension_validate_cmd = None

        if embed_mode:
            ttk.Frame.__init__(self, master)
            self._title = "Base Generation"
            self._description = None
            self._show_header = False
            self.body_frame = self
            self._build_body(self)
        else:
            super().__init__(master, title="Base Generation", show_header=show_header, **kwargs)

        self._sync_enabled = False
        self.refresh_from_adapters()
        self.apply_from_overrides(
            {
                "model": model_name,
                "vae": vae_name,
                "sampler": sampler_name,
                "scheduler": scheduler_name,
                "steps": steps,
                "cfg_scale": cfg_scale,
                "width": width,
                "height": height,
                "seed": seed,
            }
        )
        self._sync_enabled = True
        self._attach_change_traces()

    def _build_body(self, parent: ttk.Frame) -> None:
        parent.columnconfigure(0, weight=0)
        parent.columnconfigure(1, weight=1)
        parent.columnconfigure(2, weight=0)
        parent.columnconfigure(3, weight=0)
        parent.columnconfigure(4, weight=0)
        parent.columnconfigure(5, weight=0)

        row_idx = 0
        helper = ttk.Label(
            parent,
            text="Width and height are the source of truth. The preset dropdown is only a helper for common resolution pairs.",
            style=MUTED_LABEL_STYLE,
            wraplength=420,
            justify="left",
        )
        helper.grid(row=row_idx, column=0, columnspan=6, sticky="ew", pady=(0, 8))
        self._helper_label = helper
        row_idx += 1

        model_values = self._build_model_values()
        self._model_combo = self._build_combo(parent, self.model_var, model_values)
        self._build_full_width_row(parent, "Model", self._model_combo, row_idx)
        row_idx += 1

        if self._include_vae:
            vae_values = self._build_vae_values()
            self._vae_combo = self._build_combo(parent, self.vae_var, vae_values)
            self._build_full_width_row(parent, "VAE", self._vae_combo, row_idx)
            row_idx += 1

        self._sampler_combo = self._build_combo(parent, self.sampler_var, [])
        if self._samplers:
            self._sampler_combo["values"] = tuple(self._samplers)
        else:
            self._sampler_combo["values"] = tuple(
                self._names_from_adapter(
                    self._sampler_adapter,
                    "get_sampler_names",
                    "get_available_samplers",
                )
            )
        self._build_sampler_row(parent, row_idx)
        row_idx += 2
        self._build_resolution_row(parent, row_idx)
        row_idx += 1
        self._build_seed_row(parent, row_idx)

    def _build_sampler_row(self, parent: ttk.Frame, row_idx: int) -> None:
        sampler_label = ttk.Label(parent, text="Sampler", style=BODY_LABEL_STYLE)
        sampler_label.grid(row=row_idx, column=0, sticky="w", padx=(0, 4), pady=(0, 4))
        self._sampler_combo.grid(row=row_idx, column=1, sticky="w", padx=(0, 4), pady=(0, 4))

        scheduler_values = self._available_schedulers()
        self._scheduler_combo = self._build_combo(parent, self.scheduler_var, scheduler_values)
        scheduler_label = ttk.Label(parent, text="Scheduler", style=BODY_LABEL_STYLE)
        scheduler_label.grid(row=row_idx, column=2, sticky="w", padx=(0, 4), pady=(0, 4))
        self._scheduler_combo.grid(row=row_idx, column=3, sticky="ew", padx=(0, 16), pady=(0, 4))

        steps_label = ttk.Label(parent, text="Steps", style=BODY_LABEL_STYLE)
        steps_label.grid(row=row_idx + 1, column=0, sticky="w", padx=(0, 4), pady=(0, 4))
        self._steps_spin = self._build_spin(
            parent, self.steps_var, from_=1, to=200, increment=1, width=6
        )
        self._steps_spin.grid(row=row_idx + 1, column=1, sticky="ew", padx=(0, 16), pady=(0, 4))

        cfg_label = ttk.Label(parent, text="CFG", style=BODY_LABEL_STYLE)
        cfg_label.grid(row=row_idx + 1, column=2, sticky="w", padx=(0, 4), pady=(0, 4))
        self._cfg_spin = self._build_spin(
            parent, self.cfg_var, from_=0.0, to=30.0, increment=0.5, width=6
        )
        self._cfg_spin.grid(row=row_idx + 1, column=3, sticky="ew", pady=(0, 4))

    def _build_resolution_row(self, parent: ttk.Frame, row_idx: int) -> None:
        preset_label = ttk.Label(parent, text="Preset", style=BODY_LABEL_STYLE)
        preset_label.grid(row=row_idx, column=0, sticky="w", padx=(0, 4), pady=(0, 4))
        self._preset_combo = self._build_combo(parent, self.resolution_preset_var, tuple(self._preset_map.keys()))
        self._preset_combo.grid(row=row_idx, column=1, sticky="ew", padx=(0, 16), pady=(0, 4))
        self._preset_combo.bind("<<ComboboxSelected>>", self._on_resolution_preset_selected)

        width_label = ttk.Label(parent, text="Width", style=BODY_LABEL_STYLE)
        width_label.grid(row=row_idx, column=2, sticky="w", padx=(0, 4), pady=(0, 4))
        width_values = [str(i) for i in range(256, 2049, 128)]
        self._width_combo = self._build_numeric_combo(parent, self.width_var, width_values)
        self._width_combo.grid(row=row_idx, column=3, sticky="ew", padx=(0, 16), pady=(0, 4))

        height_label = ttk.Label(parent, text="Height", style=BODY_LABEL_STYLE)
        height_label.grid(row=row_idx, column=4, sticky="w", padx=(0, 4), pady=(0, 4))
        height_values = [str(i) for i in range(256, 2049, 128)]
        self._height_combo = self._build_numeric_combo(parent, self.height_var, height_values)
        self._height_combo.grid(row=row_idx, column=5, sticky="ew", pady=(0, 4))

    def _build_seed_row(self, parent: ttk.Frame, row_idx: int) -> None:
        seed_label = ttk.Label(parent, text="Seed", style=BODY_LABEL_STYLE)
        seed_label.grid(row=row_idx, column=0, sticky="w", padx=(0, 4), pady=(0, 4))
        seed_entry = ttk.Entry(parent, textvariable=self.seed_var, style="Dark.TEntry")
        seed_entry.grid(row=row_idx, column=1, sticky="ew", padx=(0, 16), pady=(0, 4))
        seed_hint = ttk.Label(
            parent,
            text="Blank or -1 = random.",
            style=MUTED_LABEL_STYLE,
        )
        seed_hint.grid(row=row_idx, column=2, sticky="w", pady=(0, 4))
        seed_button = ttk.Button(parent, text="Rand", width=6, command=self._randomize_seed)
        seed_button.grid(row=row_idx, column=3, sticky="w", pady=(0, 4))

        subseed_label = ttk.Label(parent, text="Subseed", style=BODY_LABEL_STYLE)
        subseed_label.grid(row=row_idx + 1, column=0, sticky="w", padx=(0, 4), pady=(0, 4))
        subseed_entry = ttk.Entry(parent, textvariable=self.subseed_var, style="Dark.TEntry")
        subseed_entry.grid(row=row_idx + 1, column=1, sticky="ew", padx=(0, 16), pady=(0, 4))
        subseed_hint = ttk.Label(
            parent,
            text="Blank or -1 = disabled.",
            style=MUTED_LABEL_STYLE,
        )
        subseed_hint.grid(row=row_idx + 1, column=2, sticky="w", pady=(0, 4))
        subseed_button = ttk.Button(parent, text="Rand", width=6, command=self._randomize_subseed)
        subseed_button.grid(row=row_idx + 1, column=3, sticky="w", pady=(0, 4))

        subseed_strength_label = ttk.Label(
            parent, text="Subseed Strength", style=BODY_LABEL_STYLE
        )
        subseed_strength_label.grid(
            row=row_idx + 1, column=4, sticky="w", padx=(0, 4), pady=(0, 4)
        )
        subseed_strength_entry = ttk.Entry(
            parent, textvariable=self.subseed_strength_var, style="Dark.TEntry"
        )
        subseed_strength_entry.grid(row=row_idx + 1, column=5, sticky="ew", pady=(0, 4))

    def _attach_change_traces(self) -> None:
        for var in (
            self.model_var,
            self.vae_var,
            self.sampler_var,
            self.scheduler_var,
            self.steps_var,
            self.cfg_var,
            self.width_var,
            self.height_var,
            self.seed_var,
            self.subseed_var,
            self.subseed_strength_var,
        ):
            try:
                var.trace_add("write", lambda *_: self._on_value_changed())
            except Exception:
                pass

    def _on_value_changed(self) -> None:
        if not self._sync_enabled:
            return
        controller = self._controller
        model_name = self._normalize_model_name(self.model_var.get())
        vae_name = self._normalize_vae_name(self.vae_var.get())
        if controller is not None:
            try:
                if hasattr(controller, "on_model_selected"):
                    controller.on_model_selected(model_name)
            except Exception:
                pass
            try:
                if hasattr(controller, "on_vae_selected"):
                    controller.on_vae_selected(vae_name)
            except Exception:
                pass
            try:
                if hasattr(controller, "on_sampler_selected"):
                    controller.on_sampler_selected(self.sampler_var.get().strip())
            except Exception:
                pass
            try:
                if hasattr(controller, "on_scheduler_selected"):
                    controller.on_scheduler_selected(self.scheduler_var.get().strip())
            except Exception:
                pass
            try:
                if hasattr(controller, "on_resolution_changed"):
                    controller.on_resolution_changed(self._safe_int(self.width_var.get(), 768), self._safe_int(self.height_var.get(), 768))
            except Exception:
                pass
        self._update_current_config()
        if callable(self._on_change):
            try:
                self._on_change()
            except Exception:
                pass

    def _update_current_config(self) -> None:
        controller = self._controller
        if controller is None:
            return
        state = getattr(controller, "state", None)
        cfg = getattr(state, "current_config", None)
        if cfg is None:
            return
        try:
            cfg.model_name = self._normalize_model_name(self.model_var.get())
            cfg.vae_name = self._normalize_vae_name(self.vae_var.get())
            cfg.sampler_name = self.sampler_var.get().strip()
            cfg.scheduler_name = self.scheduler_var.get().strip()
            cfg.steps = self._safe_int(self.steps_var.get(), 20)
            cfg.cfg_scale = self._safe_float(self.cfg_var.get(), 7.0)
            cfg.width = self._safe_int(self.width_var.get(), 768)
            cfg.height = self._safe_int(self.height_var.get(), 768)
            seed_text = str(self.seed_var.get()).strip()
            if not seed_text or seed_text == "-1":
                cfg.seed = None
            else:
                cfg.seed = self._safe_int(seed_text, -1)
            subseed_text = str(self.subseed_var.get()).strip()
            cfg.subseed = -1 if not subseed_text or subseed_text == "-1" else self._safe_int(subseed_text, -1)
            cfg.subseed_strength = self._safe_float(self.subseed_strength_var.get(), 0.0)
        except Exception:
            pass

    def _get_current_config(self) -> Any | None:
        controller = self._controller
        if not controller:
            return None
        state = getattr(controller, "state", None)
        if not state:
            return None
        return getattr(state, "current_config", None)

    def _available_schedulers(self) -> tuple[str, ...]:
        controller = self._controller
        if controller and hasattr(controller, "get_available_schedulers"):
            try:
                values = [str(v) for v in (controller.get_available_schedulers() or []) if v]
                return tuple(values)
            except Exception:
                return ()
        return ()

    def refresh_from_adapters(self) -> None:
        try:
            models = self._build_model_values()
            vaes = self._build_vae_values()
            samplers = self._names_from_adapter(
                self._sampler_adapter,
                "get_sampler_names",
                "get_available_samplers",
            )
            schedulers = self._available_schedulers()
            self._update_combo(self._model_combo, self.model_var, models)
            self._update_combo(self._vae_combo, self.vae_var, vaes)
            self._update_combo(self._sampler_combo, self.sampler_var, samplers)
            self._update_combo(self._scheduler_combo, self.scheduler_var, schedulers)
        except Exception:
            pass

    def _names_from_adapter(
        self,
        adapter: object | None,
        adapter_method_name: str,
        controller_method_name: str | None = None,
    ) -> list[str]:
        if self._controller is not None and controller_method_name is not None:
            controller_method = getattr(self._controller, controller_method_name, None)
            if controller_method is not None and callable(controller_method):
                try:
                    result = controller_method()
                    if result:
                        names: list[str] = []
                        for item in result:
                            if hasattr(item, "display_name") and item.display_name:
                                names.append(str(item.display_name))
                            elif hasattr(item, "name") and item.name:
                                names.append(str(item.name))
                            else:
                                names.append(str(item))
                        return [name for name in names if name]
                except Exception:
                    pass
        if adapter is None:
            return []
        method = getattr(adapter, adapter_method_name, None)
        if method is None or not callable(method):
            return []
        try:
            result = method()
            return [str(name) for name in (result or []) if name]
        except Exception:
            return []

    def _update_combo(
        self,
        combo: ttk.Combobox | None,
        variable: tk.Variable,
        values: Iterable[str],
    ) -> None:
        if combo is None:
            return
        current = str(variable.get())
        new_values = tuple(values)
        combo["values"] = new_values
        reverse_lookup = {}
        if variable is self.model_var:
            reverse_lookup = {internal: display for display, internal in self._model_name_map.items()}
        elif variable is self.vae_var:
            reverse_lookup = {internal: display for display, internal in self._vae_name_map.items()}
        if current in new_values:
            variable.set(current)
        elif current in reverse_lookup and reverse_lookup[current] in new_values:
            variable.set(reverse_lookup[current])
        elif new_values:
            variable.set(new_values[0])
        elif isinstance(variable, tk.StringVar):
            variable.set("")

    def _build_full_width_row(
        self, parent: ttk.Frame, label: str, widget: tk.Widget, row_idx: int
    ) -> None:
        label_widget = ttk.Label(parent, text=label, style=BODY_LABEL_STYLE)
        label_widget.grid(row=row_idx, column=0, sticky="w", padx=(0, 8), pady=(0, 4))
        widget.grid(row=row_idx, column=1, columnspan=5, sticky="ew", pady=(0, 4))

    def _build_combo(
        self,
        parent: ttk.Frame,
        variable: tk.Variable,
        values: Iterable[str],
        *,
        readonly: bool = True,
    ) -> ttk.Combobox:
        return ttk.Combobox(
            parent,
            textvariable=variable,
            values=tuple(values),
            state="readonly" if readonly else "normal",
            style="Dark.TCombobox",
        )

    def _build_numeric_combo(
        self, parent: ttk.Frame, variable: tk.StringVar, values: Iterable[str]
    ) -> ttk.Combobox:
        combo = self._build_combo(parent, variable, values, readonly=False)
        if self._dimension_validate_cmd is None:
            self._dimension_validate_cmd = parent.register(self._validate_dimension_input)
        combo.configure(
            validate="key",
            validatecommand=(self._dimension_validate_cmd, "%P"),
        )
        combo.bind("<<ComboboxSelected>>", self._on_dimension_commit)
        combo.bind("<FocusOut>", self._on_dimension_commit)
        combo.bind("<Return>", self._on_dimension_commit)
        return combo

    def _build_spin(
        self,
        parent: ttk.Frame,
        variable: tk.Variable,
        *,
        from_: float,
        to: float,
        increment: float,
        width: int | None = None,
    ) -> ttk.Spinbox:
        kwargs: dict[str, Any] = {
            "from_": from_,
            "to": to,
            "increment": increment,
            "textvariable": variable,
            "style": "Dark.TSpinbox",
        }
        if width:
            kwargs["width"] = width
        return ttk.Spinbox(parent, **kwargs)

    def _on_resolution_preset_selected(self, _event: object = None) -> None:
        preset = self.resolution_preset_var.get()
        width, height = self._preset_map.get(preset, self._parse_preset_label(preset))
        self.width_var.set(str(width))
        self.height_var.set(str(height))
        self._sync_resolution_label_from_dimensions()

    def _on_dimension_commit(self, _event: object = None) -> None:
        self.width_var.set(str(self._normalize_dimension_value(self.width_var.get(), 768)))
        self.height_var.set(str(self._normalize_dimension_value(self.height_var.get(), 768)))
        self._sync_resolution_label_from_dimensions()

    def _sync_resolution_label_from_dimensions(self) -> None:
        width = self._normalize_dimension_value(self.width_var.get(), 768)
        height = self._normalize_dimension_value(self.height_var.get(), 768)
        target = self._preset_label_from_dimensions(width, height)
        if self.resolution_preset_var.get() != target:
            self.resolution_preset_var.set(target)

    def _randomize_seed(self) -> None:
        import random

        self.seed_var.set(str(random.randint(0, 2**32 - 1)))

    def _randomize_subseed(self) -> None:
        import random

        self.subseed_var.set(str(random.randint(0, 2**32 - 1)))

    def _validate_dimension_input(self, proposed: str) -> bool:
        if proposed == "":
            return True
        if not proposed.isdigit():
            return False
        try:
            return int(proposed) <= self.MAX_DIMENSION
        except ValueError:
            return False

    def _normalize_dimension_value(self, value: object, default: int) -> int:
        normalized = self._safe_int(value, default)
        return max(self.MIN_DIMENSION, min(self.MAX_DIMENSION, normalized))

    def get_overrides(self) -> dict[str, object]:
        width = self._safe_int(self.width_var.get(), 768)
        height = self._safe_int(self.height_var.get(), 768)
        seed_text = str(self.seed_var.get()).strip()
        seed_value: int | None
        if not seed_text or seed_text == "-1":
            seed_value = None
        else:
            seed_value = self._safe_int(seed_text, -1)
        subseed_text = str(self.subseed_var.get()).strip()
        subseed_value = -1 if not subseed_text or subseed_text == "-1" else self._safe_int(subseed_text, -1)
        return {
            "model": self._normalize_model_name(self.model_var.get()),
            "model_name": self._normalize_model_name(self.model_var.get()),
            "vae_name": self._normalize_vae_name(self.vae_var.get()),
            "vae": self._normalize_vae_name(self.vae_var.get()),
            "sampler": self.sampler_var.get().strip(),
            "scheduler": self.scheduler_var.get().strip(),
            "steps": self._safe_int(self.steps_var.get(), 20),
            "cfg_scale": self._safe_float(self.cfg_var.get(), 7.0),
            "resolution_preset": self._preset_value_from_label(
                self._preset_label_from_dimensions(width, height)
            ),
            "width": width,
            "height": height,
            "ratio": self._format_ratio(width, height),
            "seed": seed_value,
            "subseed": subseed_value,
            "subseed_strength": self._safe_float(self.subseed_strength_var.get(), 0.0),
        }

    def apply_from_overrides(self, overrides: dict[str, object]) -> None:
        if not overrides:
            return
        self._sync_enabled = False
        try:
            model_value = str(overrides.get("model") or overrides.get("model_name") or self.model_var.get())
            model_display = self._display_model_name(model_value)
            self.model_var.set(model_display)
            vae_value = str(overrides.get("vae") or overrides.get("vae_name") or self.vae_var.get())
            vae_display = self._display_vae_name(vae_value)
            self.vae_var.set(vae_display)
            self.sampler_var.set(str(overrides.get("sampler") or overrides.get("sampler_name") or self.sampler_var.get()))
            self.scheduler_var.set(str(overrides.get("scheduler") or self.scheduler_var.get()))
            self.steps_var.set(self._safe_int(overrides.get("steps", self.steps_var.get()), 20))
            self.cfg_var.set(self._safe_float(overrides.get("cfg_scale", self.cfg_var.get()), 7.0))
            width = overrides.get("width")
            height = overrides.get("height")
            if width is not None and height is not None:
                self.width_var.set(str(self._safe_int(width, 768)))
                self.height_var.set(str(self._safe_int(height, 768)))
                self.resolution_preset_var.set(
                    self._preset_label_from_dimensions(self._safe_int(width, 768), self._safe_int(height, 768))
                )
            else:
                preset = overrides.get("resolution_preset")
                if preset:
                    self.resolution_preset_var.set(self._preset_label_from_value(str(preset)))
                    self._on_resolution_preset_selected()
            seed = overrides.get("seed")
            self.seed_var.set("" if seed in (None, "", -1, "-1") else str(self._safe_int(seed, -1)))
            subseed = overrides.get("subseed")
            self.subseed_var.set(
                "" if subseed in (None, "", -1, "-1") else str(self._safe_int(subseed, -1))
            )
            subseed_strength = overrides.get("subseed_strength")
            if subseed_strength is not None:
                self.subseed_strength_var.set(
                    str(self._safe_float(subseed_strength, 0.0))
                )
        finally:
            self._sync_enabled = True
        self._update_current_config()
        if callable(self._on_change):
            try:
                self._on_change()
            except Exception:
                pass

    def _normalize_model_name(self, raw: object) -> str:
        value = str(raw or "").strip()
        if not value:
            return ""
        return self._model_name_map.get(value, value)

    def _normalize_vae_name(self, raw: object) -> str:
        value = str(raw or "").strip()
        if not value:
            return ""
        return self._vae_name_map.get(value, value)

    def _display_model_name(self, internal_name: object) -> str:
        value = str(internal_name or "").strip()
        if not value:
            return ""
        for display, internal in self._model_name_map.items():
            if internal == value:
                return display
        return value

    def _display_vae_name(self, internal_name: object) -> str:
        value = str(internal_name or "").strip()
        if not value:
            return "No VAE (model default)"
        for display, internal in self._vae_name_map.items():
            if internal == value:
                return display
        return value

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

    @staticmethod
    def _coerce_string(value: object, default: str) -> str:
        if value is None:
            return default
        if isinstance(value, str):
            return value or default
        return default

    @classmethod
    def _coerce_int(cls, value: object, default: int) -> int:
        if value is None:
            return default
        return cls._safe_int(value, default)

    @classmethod
    def _coerce_float(cls, value: object, default: float) -> float:
        if value is None:
            return default
        return cls._safe_float(value, default)

    @staticmethod
    def _format_ratio(width: int, height: int) -> str:
        if width <= 0 or height <= 0:
            return "1:1"
        divisor = math.gcd(width, height) or 1
        return f"{width // divisor}:{height // divisor}"

    def _preset_value_from_label(self, label: str) -> str:
        return label.split(" ", 1)[0]

    def _preset_label_from_value(self, value: str) -> str:
        try:
            width, height = map(int, value.split("x"))
        except Exception:
            return value
        return self._preset_label_from_dimensions(width, height)

    def _preset_label_from_dimensions(self, width: int, height: int) -> str:
        return self._preset_reverse_map.get(
            (width, height),
            f"{width}x{height} ({self._format_ratio(width, height)})",
        )

    def _parse_preset_label(self, label: str) -> tuple[int, int]:
        try:
            base = label.split(" ", 1)[0]
            width, height = map(int, base.split("x"))
            return width, height
        except Exception:
            return 768, 768

    def _build_model_values(self) -> tuple[str, ...]:
        controller = self._controller
        if controller is not None and hasattr(controller, "list_models"):
            values: list[str] = []
            mapping: dict[str, str] = {}
            try:
                for item in controller.list_models() or []:
                    display = getattr(item, "display_name", None) or getattr(item, "name", None) or str(item)
                    internal = getattr(item, "name", None) or str(item)
                    if display:
                        values.append(str(display))
                        mapping[str(display)] = str(internal)
            except Exception:
                values = []
                mapping = {}
            if values:
                self._model_name_map = mapping
                return tuple(values)
        values = tuple(self._models or self._names_from_adapter(self._model_adapter, "get_model_names", "list_models"))
        self._model_name_map = {value: value for value in values}
        return values

    def _build_vae_values(self) -> tuple[str, ...]:
        controller = self._controller
        if controller is not None and hasattr(controller, "list_vaes"):
            values = ["No VAE (model default)"]
            mapping: dict[str, str] = {"No VAE (model default)": ""}
            try:
                for item in controller.list_vaes() or []:
                    display = getattr(item, "display_name", None) or getattr(item, "name", None) or str(item)
                    internal = getattr(item, "name", None) or str(item)
                    if display:
                        values.append(str(display))
                        mapping[str(display)] = str(internal)
            except Exception:
                values = ["No VAE (model default)"]
                mapping = {"No VAE (model default)": ""}
            self._vae_name_map = mapping
            return tuple(values)
        values = tuple(self._vaes or self._names_from_adapter(self._vae_adapter, "get_vae_names", "list_vaes"))
        full_values = ("No VAE (model default)",) + values
        self._vae_name_map = {"No VAE (model default)": "", **{value: value for value in values}}
        return full_values


__all__ = ["BaseGenerationPanelV2"]
