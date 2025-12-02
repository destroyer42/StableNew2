"""Advanced Txt2Img stage card for V2 GUI."""

from __future__ import annotations

import tkinter as tk
from tkinter import ttk
from typing import Any

from src.gui.stage_cards_v2.base_stage_card_v2 import BaseStageCardV2
from src.gui.stage_cards_v2.components import SamplerSection, SeedSection
from src.gui.stage_cards_v2.validation_result import ValidationResult
from src.gui.theme_v2 import BODY_LABEL_STYLE, SURFACE_FRAME_STYLE


class AdvancedTxt2ImgStageCardV2(BaseStageCardV2):
    panel_header = "Txt2Img Configuration"
    NO_VAE_DISPLAY = "No VAE (model default)"

    def __init__(self, master: tk.Misc, *, controller: Any = None, theme: Any = None, **kwargs: Any) -> None:
        self.controller = controller
        self.theme = theme
        self._on_change = None
        super().__init__(master, title=self.panel_header, **kwargs)

    def _build_body(self, parent: ttk.Frame) -> None:
        # Core vars
        self.model_var = tk.StringVar()
        self.vae_var = tk.StringVar()
        self.sampler_var = tk.StringVar()
        self.scheduler_var = tk.StringVar()
        self.steps_var = tk.IntVar(value=20)
        self.cfg_var = tk.DoubleVar(value=7.0)
        self.width_var = tk.IntVar(value=512)
        self.height_var = tk.IntVar(value=512)
        self.clip_skip_var = tk.IntVar(value=2)

        # Sampler/steps/cfg
        self.sampler_section = SamplerSection(parent)
        self.sampler_section.grid(row=0, column=0, sticky="ew", pady=(0, 8))
        # Link primary sampler vars to section vars to preserve API
        self.sampler_section.sampler_var = self.sampler_var
        # Replace sampler section widgets with spinboxes/bound vars
        try:
            for child in self.sampler_section.winfo_children():
                child.destroy()
        except Exception:
            pass
        ttk.Label(self.sampler_section, text="Sampler", style=BODY_LABEL_STYLE).grid(row=0, column=0, sticky="w", padx=(0, 4))
        sampler_resources = self.controller.list_upscalers() if self.controller and hasattr(self.controller, "list_upscalers") else []
        sampler_values = [r.display_name for r in sampler_resources] if sampler_resources else getattr(self.controller, "get_available_samplers", lambda: [])() if self.controller else ["Euler", "DPM++ 2M"]
        self.sampler_combo = ttk.Combobox(
            self.sampler_section,
            textvariable=self.sampler_var,
            values=sampler_values,
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

        # Model/vae/scheduler/clip/size
        meta = ttk.Frame(parent, style=SURFACE_FRAME_STYLE)
        meta.grid(row=1, column=0, sticky="ew", pady=(0, 8))
        ttk.Label(meta, text="Model", style=BODY_LABEL_STYLE).grid(row=0, column=0, sticky="w", padx=(0, 4))
        model_resources = self.controller.list_models() if self.controller and hasattr(self.controller, "list_models") else []
        model_display_names = [r.display_name for r in model_resources] if model_resources else ["sd_xl_base_1.0", "sd15"]
        self.model_combo = ttk.Combobox(
            meta,
            textvariable=self.model_var,
            values=model_display_names,
            state="readonly",
            width=18,
            style="Dark.TCombobox",
        )
        self.model_combo.grid(row=0, column=1, sticky="ew", padx=(0, 8))
        ttk.Label(meta, text="VAE", style=BODY_LABEL_STYLE).grid(row=0, column=2, sticky="w", padx=(0, 4))
        vae_resources = self.controller.list_vaes() if self.controller and hasattr(self.controller, "list_vaes") else []
        vae_display_names = [self.NO_VAE_DISPLAY]
        if vae_resources:
            vae_display_names.extend(r.display_name for r in vae_resources)
        else:
            vae_display_names.append("default")
        self.vae_combo = ttk.Combobox(
            meta,
            textvariable=self.vae_var,
            values=vae_display_names,
            state="readonly",
            width=18,
            style="Dark.TCombobox",
        )
        self.vae_combo.grid(row=0, column=3, sticky="ew")
        # Map display_name to internal name for config
        self._model_name_map = {r.display_name: r.name for r in model_resources}
        self._vae_name_map = {r.display_name: r.name for r in vae_resources}
        self._vae_name_map[self.NO_VAE_DISPLAY] = ""
        def on_model_selected(*_: Any) -> None:
            selected_display = self.model_var.get()
            selected_name = self._model_name_map.get(selected_display, selected_display)
            # Update config dict for payload correctness
            if hasattr(self, 'config') and isinstance(self.config, dict):
                self.config["model"] = selected_name
                self.config["model_name"] = selected_name
            if hasattr(self.controller, "on_model_selected"):
                self.controller.on_model_selected(selected_name)
        def on_vae_selected(*_: Any) -> None:
            selected_display = self.vae_var.get()
            selected_name = self._vae_name_map.get(selected_display, selected_display)
            # Update config dict for payload correctness
            if hasattr(self, 'config') and isinstance(self.config, dict):
                self.config["vae"] = selected_name
                self.config["vae_name"] = selected_name
            if hasattr(self.controller, "on_vae_selected"):
                self.controller.on_vae_selected(selected_name)
        self.model_var.trace_add("write", on_model_selected)
        self.vae_var.trace_add("write", on_vae_selected)

        # Preload last-run config if available
        if self.controller and hasattr(self.controller, "get_last_run_config"):
            last_run = self.controller.get_last_run_config()
            if last_run:
                # Set dropdowns to last-run values if present
                model_display = next((d for d, n in self._model_name_map.items() if n == getattr(last_run, "model", None)), None)
                vae_display = next((d for d, n in self._vae_name_map.items() if n == getattr(last_run, "vae", None)), None)
                if model_display:
                    self.model_var.set(model_display)
                if vae_display:
                    self.vae_var.set(vae_display)
                if hasattr(last_run, "sampler_name"):
                    self.sampler_var.set(getattr(last_run, "sampler_name", ""))
                if hasattr(last_run, "scheduler"):
                    self.scheduler_var.set(getattr(last_run, "scheduler", ""))
                if hasattr(last_run, "steps"):
                    self.steps_var.set(getattr(last_run, "steps", 20))
                if hasattr(last_run, "cfg_scale"):
                    self.cfg_var.set(getattr(last_run, "cfg_scale", 7.0))
                if hasattr(last_run, "width"):
                    self.width_var.set(getattr(last_run, "width", 512))
                if hasattr(last_run, "height"):
                    self.height_var.set(getattr(last_run, "height", 512))

        ttk.Label(meta, text="Scheduler", style=BODY_LABEL_STYLE).grid(row=1, column=0, sticky="w", pady=(6, 2))
        scheduler_values = getattr(self.controller, "get_available_schedulers", lambda: [])() if self.controller else ["Normal", "Karras"]
        self.scheduler_combo = ttk.Combobox(
            meta,
            textvariable=self.scheduler_var,
            values=scheduler_values,
            state="readonly",
            width=14,
            style="Dark.TCombobox",
        )
        self.scheduler_combo.grid(row=1, column=1, sticky="ew", padx=(0, 8))
        ttk.Label(meta, text="Clip skip", style=BODY_LABEL_STYLE).grid(row=1, column=2, sticky="w", pady=(6, 2))
        self.clip_skip_spin = tk.Spinbox(meta, from_=1, to=8, increment=1, textvariable=self.clip_skip_var, width=6)
        self.clip_skip_spin.grid(row=1, column=3, sticky="ew")

        ttk.Label(meta, text="Width", style=BODY_LABEL_STYLE).grid(row=2, column=0, sticky="w", pady=(6, 2))
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
        self.width_combo.grid(row=2, column=1, sticky="ew", padx=(0, 8))
        
        ttk.Label(meta, text="Height", style=BODY_LABEL_STYLE).grid(row=2, column=2, sticky="w", pady=(6, 2))
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
        self.height_combo.grid(row=2, column=3, sticky="ew")
        for col in range(4):
            meta.columnconfigure(col, weight=1 if col in (1, 3) else 0)

        # Seed/randomize
        self.seed_section = SeedSection(parent)
        self.seed_section.grid(row=2, column=0, sticky="ew")
        self.seed_var = self.seed_section.seed_var  # exposed for compatibility

        for var in self.watchable_vars():
            try:
                var.trace_add("write", lambda *_: self._notify_change())
            except Exception:
                pass

        parent.columnconfigure(0, weight=1)

    def set_on_change(self, callback: Any) -> None:
        self._on_change = callback

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

    def load_from_section(self, section: dict[str, Any] | None) -> None:
        data = section or {}
        self.model_var.set(data.get("model") or data.get("model_name", ""))
        self.vae_var.set(data.get("vae") or data.get("vae_name", ""))
        self.sampler_var.set(data.get("sampler_name", ""))
        self.scheduler_var.set(data.get("scheduler", ""))
        self.steps_var.set(int(self._safe_int(data.get("steps", 20), 20)))
        self.cfg_var.set(float(self._safe_float(data.get("cfg_scale", 7.0), 7.0)))
        self.width_var.set(int(self._safe_int(data.get("width", 512), 512)))
        self.height_var.set(int(self._safe_int(data.get("height", 512), 512)))
        self.clip_skip_var.set(int(self._safe_int(data.get("clip_skip", 2), 2)))

    def load_from_config(self, cfg: dict[str, Any]) -> None:
        section = (cfg or {}).get("txt2img", {}) or {}
        self.load_from_section(section)

    def to_config_dict(self) -> dict[str, Any]:
        # Use internal names for model/vae, and all selected values for payload correctness
        model_name = self._model_name_map.get(self.model_var.get(), self.model_var.get().strip())
        vae_name = self._vae_name_map.get(self.vae_var.get(), self.vae_var.get().strip())
        return {
            "txt2img": {
                "model": model_name,
                "model_name": model_name,
                "vae": vae_name,
                "vae_name": vae_name,
                "sampler_name": self.sampler_var.get().strip(),
                "scheduler": self.scheduler_var.get().strip(),
                "steps": int(self.steps_var.get() or 20),
                "cfg_scale": float(self.cfg_var.get() or 7.0),
                "width": int(self.width_var.get() or 512),
                "height": int(self.height_var.get() or 512),
                "clip_skip": int(self.clip_skip_var.get() or 2),
                "seed": int(self.seed_var.get() or 0),
            }
        }

    def validate(self) -> ValidationResult:
        # All controls are now constrained by UI, minimal validation needed
        try:
            steps = int(self.steps_var.get())
            if steps < 1:
                return ValidationResult(False, "Steps must be >= 1", errors={"steps": "Steps must be >= 1"})
        except Exception:
            return ValidationResult(False, "Steps must be an integer", errors={"steps": "Steps must be an integer"})
        return ValidationResult(True, None)

    def watchable_vars(self) -> list[tk.Variable]:
        return [
            self.model_var,
            self.vae_var,
            self.sampler_var,
            self.scheduler_var,
            self.steps_var,
            self.cfg_var,
            self.width_var,
            self.height_var,
            self.clip_skip_var,
        ]

    def apply_resource_update(self, resources: dict[str, list[Any]] | None) -> None:
        if not resources:
            return
        self._update_model_options(resources.get("models") or [])
        self._update_vae_options(resources.get("vaes") or [])
        self._set_sampler_options(resources.get("samplers") or [])
        self._set_scheduler_options(resources.get("schedulers") or [])

    def _update_model_options(self, entries: list[Any]) -> None:
        values, mapping = self._normalize_dropdown_entries(entries)
        self._model_name_map = mapping
        self._set_combo_values(self.model_combo, self.model_var, values)

    def _update_vae_options(self, entries: list[Any]) -> None:
        values, mapping = self._normalize_dropdown_entries(entries)
        if self.NO_VAE_DISPLAY not in values:
            values.insert(0, self.NO_VAE_DISPLAY)
        mapping[self.NO_VAE_DISPLAY] = ""
        self._vae_name_map = mapping
        self._set_combo_values(self.vae_combo, self.vae_var, values)

    def _set_sampler_options(self, entries: list[Any]) -> None:
        values = [self._normalize_sampler_entry(entry) for entry in entries]
        values = [value for value in values if value]
        self._set_combo_values(self.sampler_combo, self.sampler_var, values)

    def _set_scheduler_options(self, entries: list[Any]) -> None:
        values = [str(entry).strip() for entry in entries if str(entry).strip()]
        self._set_combo_values(self.scheduler_combo, self.scheduler_var, values)

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
    def _normalize_sampler_entry(entry: Any) -> str:
        if isinstance(entry, dict):
            return (
                str(entry.get("name") or entry.get("label") or entry.get("sampler_name") or entry.get("title") or "")
                .strip()
            )
        return str(entry).strip()

    @staticmethod
    def _set_combo_values(combo: ttk.Combobox, var: tk.Variable, values: list[str]) -> None:
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
