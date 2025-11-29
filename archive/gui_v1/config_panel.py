"""ConfigPanel for Center Zone core settings."""

from __future__ import annotations

import tkinter as tk
from tkinter import ttk
from typing import Any, Callable

from . import theme

MAX_DIMENSION = 2260


class ConfigPanel(ttk.Frame):
    """Basic configuration controls for model/sampler/resolution/steps/CFG."""

    def __init__(
        self,
        master: tk.Misc,
        on_change: Callable[[str, Any], None] | None = None,
        *,
        coordinator: Any | None = None,
        style: str | None = None,
        **kwargs: Any,
    ) -> None:
        frame_style = style or theme.SURFACE_FRAME_STYLE
        super().__init__(master, padding=theme.PADDING_MD, style=frame_style, **kwargs)
        self.on_change = on_change
        self.coordinator = coordinator

        self.columnconfigure(0, weight=1)
        self.columnconfigure(1, weight=1)

        self.model_var = tk.StringVar()
        self.sampler_var = tk.StringVar()
        self.width_var = tk.IntVar(value=512)
        self.height_var = tk.IntVar(value=512)
        self.steps_var = tk.IntVar(value=30)
        self.cfg_var = tk.DoubleVar(value=7.0)
        self.hires_steps_var = tk.IntVar(value=0)
        self.face_restoration_enabled = tk.BooleanVar(value=False)
        self.face_restoration_model = tk.StringVar(value="GFPGAN")
        self.face_restoration_weight = tk.DoubleVar(value=0.5)
        self.refiner_switch_at = tk.DoubleVar(value=0.5)
        self.refiner_switch_steps = tk.IntVar(value=0)

        # Legacy compatibility dictionaries expected by StableNewGUI
        self.txt2img_vars: dict[str, tk.StringVar] = {
            "model": self.model_var,
            "sampler_name": self.sampler_var,
            "width": self.width_var,
            "height": self.height_var,
            "steps": self.steps_var,
            "cfg_scale": self.cfg_var,
            "hires_steps": self.hires_steps_var,
            "face_restoration_enabled": self.face_restoration_enabled,
            "face_restoration_model": self.face_restoration_model,
            "face_restoration_weight": self.face_restoration_weight,
            "refiner_switch_at": self.refiner_switch_at,
            "refiner_switch_steps": self.refiner_switch_steps,
        }
        self.img2img_vars: dict[str, tk.StringVar] = {
            "model": tk.StringVar(),
            "sampler_name": tk.StringVar(),
        }
        self.upscale_vars: dict[str, tk.StringVar] = {
            "upscaler": tk.StringVar(),
        }
        self.api_vars: dict[str, tk.StringVar] = {"base_url": tk.StringVar()}
        self.txt2img_widgets: dict[str, tk.Widget] = {}
        self.upscale_widgets: dict[str, tk.Widget] = {}

        ttk.Label(self, text="Model", style=theme.STATUS_STRONG_LABEL_STYLE).grid(
            row=0, column=0, sticky="w", columnspan=2
        )
        self.model_combo = ttk.Combobox(
            self,
            textvariable=self.model_var,
            state="readonly",
        )
        self.model_combo.grid(row=1, column=0, columnspan=2, sticky="ew", pady=(0, theme.PADDING_MD))
        self.model_combo.bind("<<ComboboxSelected>>", self._handle_model_change)
        self.txt2img_widgets["model"] = self.model_combo

        ttk.Label(self, text="Sampler", style=theme.STATUS_STRONG_LABEL_STYLE).grid(
            row=2, column=0, sticky="w", columnspan=2
        )
        self.sampler_combo = ttk.Combobox(
            self,
            textvariable=self.sampler_var,
            state="readonly",
        )
        self.sampler_combo.grid(row=3, column=0, columnspan=2, sticky="ew", pady=(0, theme.PADDING_MD))
        self.sampler_combo.bind("<<ComboboxSelected>>", self._handle_sampler_change)
        self.txt2img_widgets["sampler_name"] = self.sampler_combo

        ttk.Label(self, text="Resolution", style=theme.STATUS_STRONG_LABEL_STYLE).grid(
            row=4, column=0, sticky="w", columnspan=2
        )
        width_entry = ttk.Spinbox(self, from_=64, to=MAX_DIMENSION, textvariable=self.width_var, width=8, wrap=True)
        height_entry = ttk.Spinbox(self, from_=64, to=MAX_DIMENSION, textvariable=self.height_var, width=8, wrap=True)
        width_entry.grid(row=5, column=0, sticky="ew", pady=(0, theme.PADDING_SM))
        height_entry.grid(row=5, column=1, sticky="ew", pady=(0, theme.PADDING_SM))
        width_entry.bind("<FocusOut>", self._handle_resolution_change)
        height_entry.bind("<FocusOut>", self._handle_resolution_change)
        self.txt2img_widgets["width"] = width_entry
        self.txt2img_widgets["height"] = height_entry
        self.dim_warning_label = ttk.Label(
            self,
            text=f"⚠️ Maximum recommended: {MAX_DIMENSION}x{MAX_DIMENSION}",
            style=theme.STATUS_LABEL_STYLE,
        )
        self.dim_warning_label.grid(row=6, column=0, columnspan=2, sticky="w", pady=(0, theme.PADDING_SM))

        ttk.Label(self, text="Steps", style=theme.STATUS_STRONG_LABEL_STYLE).grid(
            row=7, column=0, sticky="w"
        )
        ttk.Label(self, text="CFG", style=theme.STATUS_STRONG_LABEL_STYLE).grid(
            row=7, column=1, sticky="w"
        )

        steps_spin = ttk.Spinbox(
            self,
            from_=1,
            to=200,
            textvariable=self.steps_var,
            width=10,
            wrap=True,
        )
        cfg_spin = ttk.Spinbox(
            self,
            from_=1.0,
            to=30.0,
            increment=0.5,
            textvariable=self.cfg_var,
            width=10,
        )
        steps_spin.grid(row=8, column=0, sticky="ew", pady=(0, theme.PADDING_SM))
        cfg_spin.grid(row=8, column=1, sticky="ew", pady=(0, theme.PADDING_SM))
        steps_spin.bind("<FocusOut>", self._handle_steps_change)
        cfg_spin.bind("<FocusOut>", self._handle_cfg_change)
        self.txt2img_widgets["steps"] = steps_spin
        self.txt2img_widgets["cfg_scale"] = cfg_spin

        ttk.Label(self, text="Hires Fix Steps", style=theme.STATUS_STRONG_LABEL_STYLE).grid(
            row=9, column=0, sticky="w", columnspan=2
        )
        hires_spin = ttk.Spinbox(
            self,
            from_=0,
            to=200,
            textvariable=self.hires_steps_var,
            width=10,
            wrap=True,
        )
        hires_spin.grid(row=10, column=0, sticky="ew", pady=(0, theme.PADDING_SM))
        self.txt2img_widgets["hires_steps"] = hires_spin

        # Face restoration controls
        ttk.Label(self, text="Face Restoration", style=theme.STATUS_STRONG_LABEL_STYLE).grid(
            row=11, column=0, sticky="w", columnspan=2
        )
        self.face_restoration_widgets: list[tk.Widget] = []
        face_toggle = ttk.Checkbutton(
            self,
            text="Enable",
            variable=self.face_restoration_enabled,
            command=self._toggle_face_restoration,
        )
        face_toggle.grid(row=12, column=0, sticky="w")
        self.face_restoration_widgets.append(face_toggle)

        face_model = ttk.Combobox(self, textvariable=self.face_restoration_model, state="readonly")
        face_model["values"] = ["GFPGAN", "CodeFormer"]
        face_model.grid(row=13, column=0, columnspan=2, sticky="ew", pady=(0, theme.PADDING_SM))
        self.face_restoration_widgets.append(face_model)

        face_weight = ttk.Spinbox(
            self,
            from_=0.0,
            to=1.0,
            increment=0.05,
            textvariable=self.face_restoration_weight,
            width=10,
        )
        face_weight.grid(row=14, column=0, sticky="ew", pady=(0, theme.PADDING_MD))
        self.face_restoration_widgets.append(face_weight)

        # Refiner switch controls
        ttk.Label(self, text="Refiner Switch", style=theme.STATUS_STRONG_LABEL_STYLE).grid(
            row=15, column=0, sticky="w", columnspan=2
        )
        refiner_ratio = ttk.Spinbox(
            self,
            from_=0.0,
            to=1.0,
            increment=0.05,
            textvariable=self.refiner_switch_at,
            width=10,
            wrap=True,
            command=self._update_refiner_mapping_label,
        )
        refiner_ratio.grid(row=16, column=0, sticky="ew", pady=(0, theme.PADDING_SM))
        self.txt2img_widgets["refiner_switch_at"] = refiner_ratio

        refiner_steps_spin = ttk.Spinbox(
            self,
            from_=0,
            to=200,
            textvariable=self.refiner_switch_steps,
            width=10,
            wrap=True,
            command=self._update_refiner_mapping_label,
        )
        refiner_steps_spin.grid(row=16, column=1, sticky="ew", pady=(0, theme.PADDING_SM))
        self.txt2img_widgets["refiner_switch_steps"] = refiner_steps_spin

        self.refiner_mapping_label = ttk.Label(self, text="", style=theme.STATUS_LABEL_STYLE)
        self.refiner_mapping_label.grid(row=17, column=0, columnspan=2, sticky="w")

        self.config_status_label = ttk.Label(self, text="", style=theme.STATUS_LABEL_STYLE)
        self.config_status_label.grid(row=18, column=0, columnspan=2, sticky="w")

        self._toggle_face_restoration()
        self._update_refiner_mapping_label()

    def refresh_from_controller(
        self,
        config: dict[str, Any],
        model_options: list[str],
        sampler_options: list[str],
    ) -> None:
        """Sync widget values with controller state and available options."""
        if model_options:
            self.model_combo["values"] = model_options
        if sampler_options:
            self.sampler_combo["values"] = sampler_options

        self.model_var.set(config.get("model", ""))
        self.sampler_var.set(config.get("sampler_name", ""))
        self.width_var.set(str(config.get("width", "")))
        self.height_var.set(str(config.get("height", "")))
        self.steps_var.set(str(config.get("steps", "")))
        self.cfg_var.set(str(config.get("cfg_scale", "")))

    def _handle_model_change(self, _event: tk.Event | None) -> None:
        self._notify_change("model", self.model_var.get())

    def _handle_sampler_change(self, _event: tk.Event | None) -> None:
        self._notify_change("sampler_name", self.sampler_var.get())

    def _handle_resolution_change(self, _event: tk.Event | None) -> None:
        self._notify_change("width", self.width_var.get())
        self._notify_change("height", self.height_var.get())

    def _handle_steps_change(self, _event: tk.Event | None) -> None:
        self._notify_change("steps", self.steps_var.get())

    def _handle_cfg_change(self, _event: tk.Event | None) -> None:
        self._notify_change("cfg_scale", self.cfg_var.get())

    def _toggle_face_restoration(self) -> None:
        """Show/hide face restoration widgets based on toggle."""
        show = bool(self.face_restoration_enabled.get())
        for widget in self.face_restoration_widgets[1:]:
            if show:
                widget.grid()
            else:
                widget.grid_remove()

    def _update_refiner_mapping_label(self) -> None:
        """Update label showing refiner switch mapping."""
        total_steps = max(int(self.steps_var.get() or 0), 1)
        ratio = float(self.refiner_switch_at.get() or 0)
        switch_steps = int(self.refiner_switch_steps.get() or 0)
        if switch_steps > 0:
            ratio = min(max(switch_steps / total_steps, 0.0), 1.0)
        else:
            switch_steps = int(total_steps * ratio)
        self.refiner_mapping_label.config(
            text=f"Refiner starts at step {switch_steps}/{total_steps} (ratio={ratio:.3f})"
        )

    def _notify_change(self, field: str, value: Any) -> None:
        if self.on_change:
            self.on_change(field, value)

    def get_config(self) -> dict[str, Any]:
        """Return a minimal config dict for tests/legacy callers."""
        cfg = {
            "txt2img": {
                "model": self.model_var.get(),
                "sampler_name": self.sampler_var.get(),
                "width": int(self.width_var.get() or 0),
                "height": int(self.height_var.get() or 0),
                "steps": int(self.steps_var.get() or 0),
                "cfg_scale": float(self.cfg_var.get() or 0),
                "hires_steps": int(self.hires_steps_var.get() or 0),
                "face_restoration_enabled": bool(self.face_restoration_enabled.get()),
                "face_restoration_model": self.face_restoration_model.get(),
                "face_restoration_weight": float(self.face_restoration_weight.get() or 0),
                "refiner_switch_at": float(self.refiner_switch_at.get() or 0),
                "refiner_switch_steps": int(self.refiner_switch_steps.get() or 0),
            }
        }
        return cfg
