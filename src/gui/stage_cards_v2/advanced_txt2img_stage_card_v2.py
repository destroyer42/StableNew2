"""Advanced Txt2Img stage card for V2 GUI."""

from __future__ import annotations

import tkinter as tk
from tkinter import ttk
from typing import Any

from src.gui.app_state_v2 import CurrentConfig
from src.gui.stage_cards_v2.base_stage_card_v2 import BaseStageCardV2
from src.gui.stage_cards_v2.components import LabeledSlider, SamplerSection, SeedSection
from src.gui.stage_cards_v2.validation_result import ValidationResult
from src.gui.theme_v2 import BODY_LABEL_STYLE, SURFACE_FRAME_STYLE


class AdvancedTxt2ImgStageCardV2(BaseStageCardV2):
    panel_header = "Txt2Img Configuration"
    NO_VAE_DISPLAY = "No VAE (model default)"

    def __init__(
        self, master: tk.Misc, *, controller: Any = None, theme: Any = None, **kwargs: Any
    ) -> None:
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

        self._refiner_model_name_map: dict[str, str] = {}
        self._refiner_model_values: list[str] = []
        model_resources = (
            self.controller.list_models()
            if self.controller and hasattr(self.controller, "list_models")
            else []
        )
        refiner_values = self._load_refiner_models(model_resources)
        # Note: _apply_refiner_hiress_defaults() is called later after refiner/hires vars are defined

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
        ttk.Label(self.sampler_section, text="Sampler", style=BODY_LABEL_STYLE).grid(
            row=0, column=0, sticky="w", padx=(0, 4)
        )
        sampler_resources = (
            self.controller.list_upscalers()
            if self.controller and hasattr(self.controller, "list_upscalers")
            else []
        )
        sampler_values = (
            [r.display_name for r in sampler_resources]
            if sampler_resources
            else getattr(self.controller, "get_available_samplers", lambda: [])()
            if self.controller
            else ["Euler", "DPM++ 2M"]
        )
        self.sampler_combo = ttk.Combobox(
            self.sampler_section,
            textvariable=self.sampler_var,
            values=sampler_values,
            state="readonly",
            width=18,
            style="Dark.TCombobox",
        )
        self.sampler_combo.grid(row=0, column=1, sticky="ew", padx=(0, 8))

        ttk.Label(self.sampler_section, text="Steps", style=BODY_LABEL_STYLE).grid(
            row=0, column=2, sticky="w", padx=(0, 4)
        )
        # Steps spinbox so users can type exact values or use arrows
        self.steps_spinbox = ttk.Spinbox(
            self.sampler_section,
            from_=1,
            to=150,
            textvariable=self.steps_var,
            width=6,
            style="Dark.TSpinbox",
        )
        self.steps_spinbox.grid(row=0, column=3, sticky="ew")

        ttk.Label(self.sampler_section, text="CFG", style=BODY_LABEL_STYLE).grid(
            row=1, column=0, sticky="w", padx=(0, 4), pady=(6, 0)
        )
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
        ttk.Label(meta, text="Model", style=BODY_LABEL_STYLE).grid(
            row=0, column=0, sticky="w", padx=(0, 4)
        )
        model_display_names = (
            [r.display_name for r in model_resources]
            if model_resources
            else ["sd_xl_base_1.0", "sd15"]
        )
        self.model_combo = ttk.Combobox(
            meta,
            textvariable=self.model_var,
            values=model_display_names,
            state="readonly",
            width=18,
            style="Dark.TCombobox",
        )
        self.model_combo.grid(row=0, column=1, sticky="ew", padx=(0, 8))
        ttk.Label(meta, text="VAE", style=BODY_LABEL_STYLE).grid(
            row=0, column=2, sticky="w", padx=(0, 4)
        )
        vae_resources = (
            self.controller.list_vaes()
            if self.controller and hasattr(self.controller, "list_vaes")
            else []
        )
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
            if hasattr(self, "config") and isinstance(self.config, dict):
                self.config["model"] = selected_name
                self.config["model_name"] = selected_name
            if hasattr(self.controller, "on_model_selected"):
                self.controller.on_model_selected(selected_name)

        def on_vae_selected(*_: Any) -> None:
            selected_display = self.vae_var.get()
            selected_name = self._vae_name_map.get(selected_display, selected_display)
            # Update config dict for payload correctness
            if hasattr(self, "config") and isinstance(self.config, dict):
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
                model_display = next(
                    (
                        d
                        for d, n in self._model_name_map.items()
                        if n == getattr(last_run, "model", None)
                    ),
                    None,
                )
                vae_display = next(
                    (
                        d
                        for d, n in self._vae_name_map.items()
                        if n == getattr(last_run, "vae", None)
                    ),
                    None,
                )
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

        ttk.Label(meta, text="Scheduler", style=BODY_LABEL_STYLE).grid(
            row=1, column=0, sticky="w", pady=(6, 2)
        )
        scheduler_values = (
            getattr(self.controller, "get_available_schedulers", lambda: [])()
            if self.controller
            else ["Normal", "Karras"]
        )
        self.scheduler_combo = ttk.Combobox(
            meta,
            textvariable=self.scheduler_var,
            values=scheduler_values,
            state="readonly",
            width=14,
            style="Dark.TCombobox",
        )
        self.scheduler_combo.grid(row=1, column=1, sticky="ew", padx=(0, 8))
        ttk.Label(meta, text="Clip skip", style=BODY_LABEL_STYLE).grid(
            row=1, column=2, sticky="w", pady=(6, 2)
        )
        self.clip_skip_spin = ttk.Spinbox(
            meta,
            from_=1,
            to=8,
            increment=1,
            textvariable=self.clip_skip_var,
            width=6,
            style="Dark.TSpinbox",
        )
        self.clip_skip_spin.grid(row=1, column=3, sticky="ew")

        ttk.Label(meta, text="Width", style=BODY_LABEL_STYLE).grid(
            row=2, column=0, sticky="w", pady=(6, 2)
        )
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

        ttk.Label(meta, text="Height", style=BODY_LABEL_STYLE).grid(
            row=2, column=2, sticky="w", pady=(6, 2)
        )
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
        
        # Add trace for randomize checkbox
        try:
            self.seed_section.randomize_var.trace_add("write", lambda *_: self._notify_change())
        except Exception:
            pass

        parent.columnconfigure(0, weight=1)

        # --- Refiner & Hires helpers --------------------------------------------
        self.refiner_enabled_var = tk.BooleanVar(value=False)
        self.refiner_model_var = tk.StringVar(value="")
        self.refiner_switch_var = tk.DoubleVar(value=0.8)

        self.hires_enabled_var = tk.BooleanVar(value=False)
        self.hires_upscaler_var = tk.StringVar(value="Latent")
        self.hires_factor_var = tk.DoubleVar(value=2.0)
        self.hires_steps_var = tk.IntVar(value=0)
        self.hires_denoise_var = tk.DoubleVar(value=0.3)
        self.hires_use_base_model_var = tk.BooleanVar(value=True)
        self.hires_model_var = tk.StringVar(value="")  # PR-GUI-E: Hires model override

        self._apply_refiner_hiress_defaults()

        self.refiner_enabled_var.trace_add("write", lambda *_: self._on_refiner_toggle())
        self.refiner_model_var.trace_add("write", lambda *_: self._on_refiner_model_changed())
        self.refiner_switch_var.trace_add("write", lambda *_: self._on_refiner_switch_changed())

        # --- Refiner Frame with collapsible options (PR-GUI-E) ---
        refiner_frame = ttk.LabelFrame(parent, text="SDXL Refiner", style=SURFACE_FRAME_STYLE)
        refiner_frame.grid(row=3, column=0, sticky="ew", pady=(8, 4))
        refiner_frame.columnconfigure(1, weight=1)
        self._refiner_frame = refiner_frame

        ttk.Checkbutton(
            refiner_frame,
            text="Enable refiner",
            variable=self.refiner_enabled_var,
            command=self._on_refiner_toggle,
            style="Dark.TCheckbutton",
        ).grid(row=0, column=0, columnspan=2, sticky="w")

        # PR-GUI-E: Container frame for refiner options (hidden when disabled)
        self._refiner_options_frame = ttk.Frame(refiner_frame, style=SURFACE_FRAME_STYLE)
        self._refiner_options_frame.grid(row=1, column=0, columnspan=2, sticky="ew")
        self._refiner_options_frame.columnconfigure(1, weight=1)

        ttk.Label(self._refiner_options_frame, text="Refiner model", style="Dark.TLabel").grid(
            row=0, column=0, sticky="w", pady=(4, 0)
        )
        self.refiner_model_combo = ttk.Combobox(
            self._refiner_options_frame,
            textvariable=self.refiner_model_var,
            values=refiner_values,
            state="readonly",
            style="Dark.TCombobox",
        )
        self.refiner_model_combo.grid(row=0, column=1, sticky="ew", pady=(4, 0))
        self._set_combo_values(self.refiner_model_combo, self.refiner_model_var, refiner_values)
        ttk.Label(self._refiner_options_frame, text="Refiner start", style="Dark.TLabel").grid(
            row=1, column=0, sticky="w", pady=(4, 0)
        )
        self._refiner_slider = LabeledSlider(
            self._refiner_options_frame,
            variable=self.refiner_switch_var,
            from_=0,
            to=100,
            show_percent=True,
            length=180,
            command=lambda value: self._on_refiner_switch_changed(),
        )
        self._refiner_slider.grid(row=1, column=1, sticky="ew", pady=(4, 0))

        # --- Hires Frame with collapsible options (PR-GUI-E) ---
        hires_frame = ttk.LabelFrame(parent, text="Hires fix", style=SURFACE_FRAME_STYLE)
        hires_frame.grid(row=4, column=0, sticky="ew", pady=(0, 4))
        hires_frame.columnconfigure(1, weight=1)
        self._hires_frame = hires_frame

        ttk.Checkbutton(
            hires_frame,
            text="Enable Hires fix",
            variable=self.hires_enabled_var,
            command=self._on_hires_toggle,
            style="Dark.TCheckbutton",
        ).grid(row=0, column=0, columnspan=2, sticky="w")

        # PR-GUI-E: Container frame for hires options (hidden when disabled)
        self._hires_options_frame = ttk.Frame(hires_frame, style=SURFACE_FRAME_STYLE)
        self._hires_options_frame.grid(row=1, column=0, columnspan=2, sticky="ew")
        self._hires_options_frame.columnconfigure(1, weight=1)

        ttk.Label(self._hires_options_frame, text="Upscaler", style="Dark.TLabel").grid(
            row=0, column=0, sticky="w", pady=(4, 0)
        )
        upscaler_values = self._load_upscaler_options()
        self.hires_upscaler_combo = ttk.Combobox(
            self._hires_options_frame,
            textvariable=self.hires_upscaler_var,
            values=upscaler_values,
            state="readonly",
            style="Dark.TCombobox",
        )
        self.hires_upscaler_combo.grid(row=0, column=1, sticky="ew", pady=(4, 0))

        # PR-GUI-E: Hires model selector
        ttk.Label(self._hires_options_frame, text="Hires model", style="Dark.TLabel").grid(
            row=1, column=0, sticky="w", pady=(4, 0)
        )
        hires_model_values = self._build_hires_model_values()
        self._hires_model_combo = ttk.Combobox(
            self._hires_options_frame,
            textvariable=self.hires_model_var,
            values=hires_model_values,
            state="readonly",
            style="Dark.TCombobox",
        )
        self._hires_model_combo.grid(row=1, column=1, sticky="ew", pady=(4, 0))
        self.hires_model_var.trace_add("write", lambda *_: self._on_hires_model_changed())

        ttk.Label(self._hires_options_frame, text="Upscale factor", style="Dark.TLabel").grid(
            row=2, column=0, sticky="w", pady=(4, 0)
        )
        ttk.Spinbox(
            self._hires_options_frame,
            from_=1.0,
            to=4.0,
            increment=0.1,
            textvariable=self.hires_factor_var,
            width=8,
            style="Dark.TSpinbox",
        ).grid(row=2, column=1, sticky="ew", pady=(4, 0))
        ttk.Label(self._hires_options_frame, text="Hires steps", style="Dark.TLabel").grid(
            row=3, column=0, sticky="w", pady=(4, 0)
        )
        ttk.Spinbox(
            self._hires_options_frame,
            from_=0,
            to=200,
            increment=1,
            textvariable=self.hires_steps_var,
            width=8,
            command=self._on_hires_steps_changed,
            style="Dark.TSpinbox",
        ).grid(row=3, column=1, sticky="ew", pady=(4, 0))
        ttk.Label(self._hires_options_frame, text="Denoise", style="Dark.TLabel").grid(
            row=4, column=0, sticky="w", pady=(4, 0)
        )
        self._hires_denoise_slider = LabeledSlider(
            self._hires_options_frame,
            variable=self.hires_denoise_var,
            from_=0.0,
            to=1.0,
            label_format="{:.2f}",
            length=180,
            command=lambda value: self._on_hires_denoise_changed(),
        )
        self._hires_denoise_slider.grid(row=4, column=1, sticky="ew", pady=(4, 0))
        ttk.Checkbutton(
            self._hires_options_frame,
            text="Use base model during hires",
            variable=self.hires_use_base_model_var,
            command=self._on_hires_use_base_model_changed,
            style="Dark.TCheckbutton",
        ).grid(row=5, column=0, columnspan=2, sticky="w", pady=(4, 0))

        self.hires_upscaler_combo.bind(
            "<<ComboboxSelected>>", lambda *_: self._on_hires_upscaler_changed()
        )
        self.hires_enabled_var.trace_add("write", lambda *_: self._on_hires_toggle())
        self.hires_upscaler_var.trace_add("write", lambda *_: self._on_hires_upscaler_changed())
        self.hires_factor_var.trace_add("write", lambda *_: self._on_hires_factor_changed())
        self.hires_steps_var.trace_add("write", lambda *_: self._on_hires_steps_changed())
        self.hires_denoise_var.trace_add("write", lambda *_: self._on_hires_denoise_changed())
        self.hires_use_base_model_var.trace_add(
            "write", lambda *_: self._on_hires_use_base_model_changed()
        )

        # PR-GUI-E: Set initial visibility (in case no config is loaded)
        self._update_refiner_visibility()
        self._update_hires_visibility()

    def set_on_change(self, callback: Any) -> None:
        self._on_change = callback

    def _notify_change(self) -> None:
        if self._on_change:
            try:
                self._on_change()
            except Exception:
                pass

    def _get_current_config(self) -> CurrentConfig | None:
        controller = getattr(self, "controller", None)
        if not controller:
            return None
        state = getattr(controller, "state", None)
        if not state:
            return None
        return getattr(state, "current_config", None)

    def _update_current_config(self, **kwargs: object) -> None:
        cfg = self._get_current_config()
        if not cfg:
            return
        for attr, value in kwargs.items():
            try:
                setattr(cfg, attr, value)
            except Exception:
                continue
        self._notify_change()

    def _apply_refiner_hiress_defaults(self) -> None:
        cfg = self._get_current_config()
        if not cfg:
            return
        self.refiner_enabled_var.set(cfg.refiner_enabled)
        display_name = self._find_refiner_display_name(cfg.refiner_model_name)
        if display_name:
            self.refiner_model_var.set(display_name)
        else:
            self.refiner_model_var.set(cfg.refiner_model_name or "")
        self.refiner_switch_var.set(int((cfg.refiner_switch_at or 0.0) * 100))
        self.hires_enabled_var.set(cfg.hires_enabled)
        self.hires_upscaler_var.set(cfg.hires_upscaler_name or "Latent")
        self.hires_factor_var.set(cfg.hires_upscale_factor or 2.0)
        self.hires_steps_var.set(cfg.hires_steps or 0)
        self.hires_denoise_var.set(cfg.hires_denoise or 0.3)
        self.hires_use_base_model_var.set(cfg.hires_use_base_model_for_hires)

        # PR-GUI-E: Set hires model override if present
        hires_model_override = getattr(cfg, "hires_model_override", None)
        if hires_model_override:
            # Find display name for the override model
            display = next(
                (d for d, n in self._model_name_map.items() if n == hires_model_override),
                hires_model_override,
            )
            self.hires_model_var.set(display)
        else:
            self.hires_model_var.set(self.USE_BASE_MODEL_LABEL)

        # PR-GUI-E: Update visibility based on initial enabled state
        self._update_refiner_visibility()
        self._update_hires_visibility()

    def _load_refiner_models(self, entries: list[Any] | None = None) -> list[str]:
        values, mapping = self._compute_refiner_model_choices(entries)
        self._refiner_model_name_map = mapping
        self._refiner_model_values = values
        return values

    def _load_upscaler_options(self) -> list[str]:
        upscalers: list[str] = []
        controller = getattr(self, "controller", None)
        if controller and hasattr(controller, "list_upscalers"):
            for entry in controller.list_upscalers():
                name = (
                    getattr(entry, "display_name", None)
                    or getattr(entry, "name", None)
                    or str(entry)
                )
                if name:
                    upscalers.append(name)
        return upscalers or ["Latent", "R-ESRGAN 4x+"]

    # PR-GUI-E: Hires model values builder
    USE_BASE_MODEL_LABEL = "Use base model"

    def _build_hires_model_values(self) -> list[str]:
        """Build list of models for hires selector, with 'Use base model' as default."""
        values = [self.USE_BASE_MODEL_LABEL]
        controller = getattr(self, "controller", None)
        if controller and hasattr(controller, "list_models"):
            for entry in controller.list_models():
                name = (
                    getattr(entry, "display_name", None)
                    or getattr(entry, "name", None)
                    or str(entry)
                )
                if name:
                    values.append(name)
        return values

    def _on_hires_model_changed(self) -> None:
        """Handle hires model selector change (PR-GUI-E)."""
        selected = self.hires_model_var.get()
        if selected == self.USE_BASE_MODEL_LABEL or not selected:
            # No override - use base model
            self._update_current_config(hires_model_override=None)
        else:
            # User selected a specific model
            model_name = self._model_name_map.get(selected, selected)
            self._update_current_config(hires_model_override=model_name)

    # PR-GUI-E: Visibility toggle helpers
    def _update_refiner_visibility(self) -> None:
        """Show/hide refiner options based on enable checkbox."""
        if not hasattr(self, "_refiner_options_frame"):
            return
        enabled = bool(self.refiner_enabled_var.get())
        if enabled:
            self._refiner_options_frame.grid()
        else:
            self._refiner_options_frame.grid_remove()

    def _update_hires_visibility(self) -> None:
        """Show/hide hires options based on enable checkbox."""
        if not hasattr(self, "_hires_options_frame"):
            return
        enabled = bool(self.hires_enabled_var.get())
        if enabled:
            self._hires_options_frame.grid()
        else:
            self._hires_options_frame.grid_remove()

    def _on_refiner_toggle(self) -> None:
        self._update_current_config(refiner_enabled=bool(self.refiner_enabled_var.get()))
        self._update_refiner_visibility()  # PR-GUI-E

    def _on_refiner_model_changed(self) -> None:
        selected_display = str(self.refiner_model_var.get() or "").strip()
        selected_name = self._refiner_model_name_map.get(selected_display, selected_display)
        self._update_current_config(refiner_model_name=selected_name)

    def _on_refiner_switch_changed(self) -> None:
        try:
            value = float(self.refiner_switch_var.get()) / 100.0
        except Exception:
            value = 0.8
        self._update_current_config(refiner_switch_at=max(0.0, min(1.0, value)))

    def _on_hires_toggle(self) -> None:
        self._update_current_config(hires_enabled=bool(self.hires_enabled_var.get()))
        self._update_hires_visibility()  # PR-GUI-E

    def _on_hires_upscaler_changed(self) -> None:
        self._update_current_config(
            hires_upscaler_name=str(self.hires_upscaler_var.get() or "Latent")
        )

    def _on_hires_factor_changed(self) -> None:
        try:
            value = float(self.hires_factor_var.get())
        except Exception:
            value = 2.0
        self._update_current_config(hires_upscale_factor=max(1.0, value))

    def _on_hires_steps_changed(self) -> None:
        try:
            value = int(self.hires_steps_var.get())
        except Exception:
            value = 0
        self._update_current_config(hires_steps=value if value > 0 else None)

    def _on_hires_denoise_changed(self) -> None:
        try:
            value = float(self.hires_denoise_var.get())
        except Exception:
            value = 0.3
        self._update_current_config(hires_denoise=max(0.0, min(1.0, value)))

    def _on_hires_use_base_model_changed(self) -> None:
        self._update_current_config(
            hires_use_base_model_for_hires=bool(self.hires_use_base_model_var.get())
        )

    def _on_cfg_changed(self, value: float) -> None:
        """Handle CFG slider changes"""
        self.cfg_var.set(value)
        self._notify_change()

    def load_from_section(self, section: dict[str, Any] | None) -> None:
        data = section or {}
        # Basic fields
        # Model: config has internal name, need to find matching display name
        model_internal = data.get("model") or data.get("model_name", "")
        model_display = next(
            (d for d, n in self._model_name_map.items() if n == model_internal),
            model_internal  # Fallback to internal name if no match
        )
        self.model_var.set(model_display)
        
        # VAE: config has internal name, need to find matching display name
        vae_internal = data.get("vae") or data.get("vae_name", "")
        vae_display = next(
            (d for d, n in self._vae_name_map.items() if n == vae_internal),
            vae_internal  # Fallback to internal name if no match
        )
        self.vae_var.set(vae_display)
        
        self.sampler_var.set(data.get("sampler_name", ""))
        self.scheduler_var.set(data.get("scheduler", ""))
        self.steps_var.set(int(self._safe_int(data.get("steps", 20), 20)))
        self.cfg_var.set(float(self._safe_float(data.get("cfg_scale", 7.0), 7.0)))
        self.width_var.set(int(self._safe_int(data.get("width", 512), 512)))
        self.height_var.set(int(self._safe_int(data.get("height", 512), 512)))
        self.clip_skip_var.set(int(self._safe_int(data.get("clip_skip", 2), 2)))
        
        # Seed (load from seed field)
        seed_value = data.get("seed", -1)
        if hasattr(self, 'seed_var'):
            self.seed_var.set(str(int(self._safe_int(seed_value, -1))))
        
        # Subseed and strength
        if hasattr(self.seed_section, 'subseed_var'):
            subseed_value = data.get("subseed", -1)
            self.seed_section.subseed_var.set(str(int(self._safe_int(subseed_value, -1))))
        if hasattr(self.seed_section, 'subseed_strength_var'):
            subseed_strength = data.get("subseed_strength", 0.0)
            self.seed_section.subseed_strength_var.set(str(float(self._safe_float(subseed_strength, 0.0))))
        
        # Refiner fields
        self.refiner_enabled_var.set(bool(data.get("use_refiner", False)))
        refiner_model = data.get("refiner_model_name") or data.get("refiner_checkpoint", "")
        if refiner_model:
            self.refiner_model_var.set(refiner_model)
        self.refiner_switch_var.set(float(self._safe_float(data.get("refiner_switch_at", 0.8), 0.8)))
        
        # Hires fix fields  
        self.hires_enabled_var.set(bool(data.get("enable_hr", False)))
        self.hires_upscaler_var.set(data.get("hr_upscaler", "Latent"))
        self.hires_factor_var.set(float(self._safe_float(data.get("hr_scale", 2.0), 2.0)))
        self.hires_steps_var.set(int(self._safe_int(data.get("hr_second_pass_steps", 0), 0)))
        self.hires_denoise_var.set(float(self._safe_float(data.get("denoising_strength", 0.3), 0.3)))
        self.hires_use_base_model_var.set(bool(data.get("hires_use_base_model", True)))
        
        # Hires model override
        hires_model = data.get("hr_checkpoint_name", "")
        if hires_model:
            self.hires_model_var.set(hires_model)

    def load_from_config(self, cfg: dict[str, Any]) -> None:
        section = (cfg or {}).get("txt2img", {}) or {}
        self.load_from_section(section)

    def to_config_dict(self) -> dict[str, Any]:
        # Use internal names for model/vae, and all selected values for payload correctness
        model_name = self._model_name_map.get(self.model_var.get(), self.model_var.get().strip())
        vae_name = self._vae_name_map.get(self.vae_var.get(), self.vae_var.get().strip())
        
        # Store use_refiner flag for conditional field writing
        use_refiner = bool(self.refiner_enabled_var.get())
        
        config = {
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
                "seed": -1 if self.seed_section.randomize_var.get() else int(self.seed_var.get() or -1),
                "subseed": int(self.seed_section.subseed_var.get() or -1),
                "subseed_strength": float(self.seed_section.subseed_strength_var.get() or 0.0),
                
                # Refiner fields - only write if explicitly enabled
                "use_refiner": use_refiner,
                **({
                    "refiner_checkpoint": self._refiner_model_name_map.get(
                        self.refiner_model_var.get(), 
                        self.refiner_model_var.get().strip()
                    ),
                    "refiner_model_name": self._refiner_model_name_map.get(
                        self.refiner_model_var.get(), 
                        self.refiner_model_var.get().strip()
                    ),
                    "refiner_switch_at": float(self.refiner_switch_var.get() or 0.8)
                } if use_refiner else {}),
                
                # Hires fix fields
                "enable_hr": bool(self.hires_enabled_var.get()),
                "hr_upscaler": self.hires_upscaler_var.get().strip(),
                "hr_scale": float(self.hires_factor_var.get() or 2.0),
                "hr_second_pass_steps": int(self.hires_steps_var.get() or 0),
                "denoising_strength": float(self.hires_denoise_var.get() or 0.3),
                "hires_use_base_model": bool(self.hires_use_base_model_var.get()),
                "hr_checkpoint_name": self.hires_model_var.get().strip() if self.hires_model_var.get() else "",
            }
        }
        
        return config

    def validate(self) -> ValidationResult:
        # All controls are now constrained by UI, minimal validation needed
        try:
            steps = int(self.steps_var.get())
            if steps < 1:
                return ValidationResult(
                    False, "Steps must be >= 1", errors={"steps": "Steps must be >= 1"}
                )
        except Exception:
            return ValidationResult(
                False, "Steps must be an integer", errors={"steps": "Steps must be an integer"}
            )
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
        self._update_refiner_model_options(resources.get("models") or [])
        self._update_hires_upscaler_options(resources.get("upscalers") or [])
        self._update_hires_model_options(resources.get("models") or [])

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

    def _update_refiner_model_options(self, entries: list[Any]) -> None:
        values = self._load_refiner_models(entries)
        self._set_combo_values(self.refiner_model_combo, self.refiner_model_var, values)

    def _compute_refiner_model_choices(
        self, entries: list[Any] | None = None
    ) -> tuple[list[str], dict[str, str]]:
        resolved = entries
        if resolved is None:
            controller = getattr(self, "controller", None)
            resolved = (
                controller.list_models()
                if controller and hasattr(controller, "list_models")
                else []
            )
        values, mapping = self._normalize_dropdown_entries(resolved)
        if not values:
            fallback = "SDXL Refinement"
            values = [fallback]
            mapping = {fallback: fallback}
        return values, mapping

    def _find_refiner_display_name(self, model_name: str | None) -> str | None:
        if not model_name:
            return None
        for display, internal in self._refiner_model_name_map.items():
            if internal == model_name:
                return display
        return None

    def _update_hires_upscaler_options(self, entries: list[Any]) -> None:
        values = [
            getattr(entry, "display_name", None) or getattr(entry, "name", None) or str(entry)
            for entry in entries
        ]
        values = [str(value).strip() for value in values if str(value).strip()]
        
        # Always include built-in upscalers at the beginning
        builtin_upscalers = ["Latent", "Latent (antialiased)", "Latent (bicubic)", "Latent (bicubic antialiased)", "Latent (nearest)", "Latent (nearest-exact)", "None"]
        for upscaler in reversed(builtin_upscalers):
            if upscaler not in values:
                values.insert(0, upscaler)
        
        if not values:
            values = ["Latent", "R-ESRGAN 4x+"]
        self._set_combo_values(self.hires_upscaler_combo, self.hires_upscaler_var, values)

    def _update_hires_model_options(self, entries: list[Any]) -> None:
        """Update hires model dropdown with available models."""
        values = [self.USE_BASE_MODEL_LABEL]
        for entry in entries:
            name = (
                getattr(entry, "display_name", None)
                or getattr(entry, "name", None)
                or str(entry)
            )
            if name:
                values.append(name)
        self._set_combo_values(self._hires_model_combo, self.hires_model_var, values)

    @staticmethod
    def _normalize_dropdown_entries(entries: list[Any]) -> tuple[list[str], dict[str, str]]:
        seen: set[str] = set()
        values: list[str] = []
        mapping: dict[str, str] = {}
        for entry in entries:
            display = (
                getattr(entry, "display_name", None) or getattr(entry, "name", None) or str(entry)
            )
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
            return str(
                entry.get("name")
                or entry.get("label")
                or entry.get("sampler_name")
                or entry.get("title")
                or ""
            ).strip()
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
