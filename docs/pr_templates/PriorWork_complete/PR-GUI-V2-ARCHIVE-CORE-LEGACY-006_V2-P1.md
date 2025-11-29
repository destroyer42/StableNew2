# PR-GUI-V2-ARCHIVE-CORE-LEGACY-006_V2-P1 — Archive legacy ConfigPanel, PipelineControlsPanel, and Img2ImgStageCard

**Baseline snapshot:** `StableNew-snapshot-20251128-154233.zip`  

**Intent:**  
You requested that we first ensure all active V2 usages in `pipeline_panel_v2`, `views/*_v2.py`, and tests have migrated to the newer `*_v2` stage cards / controls, and then archive the old modules:

- `src/gui/config_panel.py`
- `src/gui/pipeline_controls_panel.py`
- `src/gui/img2img_stage_card.py`

### Verification (already satisfied in this snapshot)

From the current snapshot:

- `pipeline_panel_v2` uses:
  - `AdvancedTxt2ImgStageCardV2`
  - `AdvancedImg2ImgStageCardV2`
  - `AdvancedUpscaleStageCardV2`
  - **No dependency** on `Img2ImgStageCard`, `ConfigPanel`, or `PipelineControlsPanel`.

- `views/*_v2.py` use:
  - `CoreConfigPanelV2`
  - `StageCardsPanelV2` (which itself uses only the `advanced_*_stage_card_v2` classes)
  - **No dependency** on the legacy modules above.

- GUI V2 tests:
  - Import only the `advanced_*_stage_card_v2` classes and `CoreConfigPanelV2`.
  - Do not import `ConfigPanel`, `PipelineControlsPanel`, or `Img2ImgStageCard` directly.

The only remaining references to these legacy modules are:

- `src/gui/main_window.py` (which will be converted to a pure V2 shim in PR-GUI-V2-SHIM-AND-ARCHIVE-005_V2-P1)
- Legacy tests under `archive/tests_v1/` and `tests/legacy/` (which are allowed to reference archived copies).

With that confirmed, this PR stubs the legacy modules in place and archives their full implementations.

---

## Files touched

- `src/gui/config_panel.py` → replaced with a stub
- `src/gui/pipeline_controls_panel.py` → replaced with a stub
- `src/gui/img2img_stage_card.py` → replaced with a stub
- `archive/gui_v1/config_panel.py` → new file with archived legacy implementation
- `archive/gui_v1/pipeline_controls_panel.py` → new file with archived legacy implementation
- `archive/gui_v1/img2img_stage_card.py` → new file with archived legacy implementation

---

## Patch: stub out `src/gui/config_panel.py`

```diff
--- a/src/gui/config_panel.py
+++ b/src/gui/config_panel.py
@@ -1,306 +1,2 @@
-"""ConfigPanel for Center Zone core settings."""
-
-from __future__ import annotations
-
-import tkinter as tk
-from tkinter import ttk
-from typing import Any, Callable
-
-from . import theme
-
-MAX_DIMENSION = 2260
-
-
-class ConfigPanel(ttk.Frame):
-    """Basic configuration controls for model/sampler/resolution/steps/CFG."""
-
-    def __init__(
-        self,
-        master: tk.Misc,
-        on_change: Callable[[str, Any], None] | None = None,
-        *,
-        coordinator: Any | None = None,
-        style: str | None = None,
-        **kwargs: Any,
-    ) -> None:
-        frame_style = style or theme.SURFACE_FRAME_STYLE
-        super().__init__(master, padding=theme.PADDING_MD, style=frame_style, **kwargs)
-        self.on_change = on_change
-        self.coordinator = coordinator
-
-        self.columnconfigure(0, weight=1)
-        self.columnconfigure(1, weight=1)
-
-        self.model_var = tk.StringVar()
-        self.sampler_var = tk.StringVar()
-        self.width_var = tk.IntVar(value=512)
-        self.height_var = tk.IntVar(value=512)
-        self.steps_var = tk.IntVar(value=30)
-        self.cfg_var = tk.DoubleVar(value=7.0)
-        self.hires_steps_var = tk.IntVar(value=0)
-        self.face_restoration_enabled = tk.BooleanVar(value=False)
-        self.face_restoration_model = tk.StringVar(value="GFPGAN")
-        self.face_restoration_weight = tk.DoubleVar(value=0.5)
-        self.refiner_switch_at = tk.DoubleVar(value=0.5)
-        self.refiner_switch_steps = tk.IntVar(value=0)
-
-        # Legacy compatibility dictionaries expected by StableNewGUI
-        self.txt2img_vars: dict[str, tk.StringVar] = {
-            "model": self.model_var,
-            "sampler_name": self.sampler_var,
-            "width": self.width_var,
-            "height": self.height_var,
-            "steps": self.steps_var,
-            "cfg_scale": self.cfg_var,
-            "hires_steps": self.hires_steps_var,
-            "face_restoration_enabled": self.face_restoration_enabled,
-            "face_restoration_model": self.face_restoration_model,
-            "face_restoration_weight": self.face_restoration_weight,
-            "refiner_switch_at": self.refiner_switch_at,
-            "refiner_switch_steps": self.refiner_switch_steps,
-        }
-        self.img2img_vars: dict[str, tk.StringVar] = {
-            "model": tk.StringVar(),
-            "sampler_name": tk.StringVar(),
-        }
-        self.upscale_vars: dict[str, tk.StringVar] = {
-            "upscaler": tk.StringVar(),
-        }
-        self.api_vars: dict[str, tk.StringVar] = {"base_url": tk.StringVar()}
-        self.txt2img_widgets: dict[str, tk.Widget] = {}
-        self.upscale_widgets: dict[str, tk.Widget] = {}
-
-        ttk.Label(self, text="Model", style=theme.STATUS_STRONG_LABEL_STYLE).grid(
-            row=0, column=0, sticky="w", columnspan=2
-        )
-        self.model_combo = ttk.Combobox(
-            self,
-            textvariable=self.model_var,
-            state="readonly",
-        )
-        self.model_combo.grid(row=1, column=0, columnspan=2, sticky="ew", pady=(0, theme.PADDING_MD))
-        self.model_combo.bind("<<ComboboxSelected>>", self._handle_model_change)
-        self.txt2img_widgets["model"] = self.model_combo
-
-        ttk.Label(self, text="Sampler", style=theme.STATUS_STRONG_LABEL_STYLE).grid(
-            row=2, column=0, sticky="w", columnspan=2
-        )
-        self.sampler_combo = ttk.Combobox(
-            self,
-            textvariable=self.sampler_var,
-            state="readonly",
-        )
-        self.sampler_combo.grid(row=3, column=0, columnspan=2, sticky="ew", pady=(0, theme.PADDING_MD))
-        self.sampler_combo.bind("<<ComboboxSelected>>", self._handle_sampler_change)
-        self.txt2img_widgets["sampler_name"] = self.sampler_combo
-
-        ttk.Label(self, text="Resolution", style=theme.STATUS_STRONG_LABEL_STYLE).grid(
-            row=4, column=0, sticky="w", columnspan=2
-        )
-        width_entry = ttk.Spinbox(self, from_=64, to=MAX_DIMENSION, textvariable=self.width_var, width=8, wrap=True)
-        height_entry = ttk.Spinbox(self, from_=64, to=MAX_DIMENSION, textvariable=self.height_var, width=8, wrap=True)
-        width_entry.grid(row=5, column=0, sticky="ew", pady=(0, theme.PADDING_SM))
-        height_entry.grid(row=5, column=1, sticky="ew", pady=(0, theme.PADDING_SM))
-        width_entry.bind("<FocusOut>", self._handle_resolution_change)
-        height_entry.bind("<FocusOut>", self._handle_resolution_change)
-        self.txt2img_widgets["width"] = width_entry
-        self.txt2img_widgets["height"] = height_entry
-        self.dim_warning_label = ttk.Label(
-            self,
-            text=f"⚠️ Maximum recommended: {MAX_DIMENSION}x{MAX_DIMENSION}",
-            style=theme.STATUS_LABEL_STYLE,
-        )
-        self.dim_warning_label.grid(row=6, column=0, columnspan=2, sticky="w", pady=(0, theme.PADDING_SM))
-
-        ttk.Label(self, text="Steps", style=theme.STATUS_STRONG_LABEL_STYLE).grid(
-            row=7, column=0, sticky="w"
-        )
-        ttk.Label(self, text="CFG", style=theme.STATUS_STRONG_LABEL_STYLE).grid(
-            row=7, column=1, sticky="w"
-        )
-
-        steps_spin = ttk.Spinbox(
-            self,
-            from_=1,
-            to=200,
-            textvariable=self.steps_var,
-            width=10,
-            wrap=True,
-        )
-        cfg_spin = ttk.Spinbox(
-            self,
-            from_=1.0,
-            to=30.0,
-            increment=0.5,
-            textvariable=self.cfg_var,
-            width=10,
-        )
-        steps_spin.grid(row=8, column=0, sticky="ew", pady=(0, theme.PADDING_SM))
-        cfg_spin.grid(row=8, column=1, sticky="ew", pady=(0, theme.PADDING_SM))
-        steps_spin.bind("<FocusOut>", self._handle_steps_change)
-        cfg_spin.bind("<FocusOut>", self._handle_cfg_change)
-        self.txt2img_widgets["steps"] = steps_spin
-        self.txt2img_widgets["cfg_scale"] = cfg_spin
-
-        ttk.Label(self, text="Hires Fix Steps", style=theme.STATUS_STRONG_LABEL_STYLE).grid(
-            row=9, column=0, sticky="w", columnspan=2
-        )
-        hires_spin = ttk.Spinbox(
-            self,
-            from_=0,
-            to=200,
-            textvariable=self.hires_steps_var,
-            width=10,
-            wrap=True,
-        )
-        hires_spin.grid(row=10, column=0, sticky="ew", pady=(0, theme.PADDING_SM))
-        self.txt2img_widgets["hires_steps"] = hires_spin
-
-        # Face restoration controls
-        ttk.Label(self, text="Face Restoration", style=theme.STATUS_STRONG_LABEL_STYLE).grid(
-            row=11, column=0, sticky="w", columnspan=2
-        )
-        self.face_restoration_widgets: list[tk.Widget] = []
-        face_toggle = ttk.Checkbutton(
-            self,
-            text="Enable",
-            variable=self.face_restoration_enabled,
-            command=self._toggle_face_restoration,
-        )
-        face_toggle.grid(row=12, column=0, sticky="w")
-        self.face_restoration_widgets.append(face_toggle)
-
-        face_model = ttk.Combobox(self, textvariable=self.face_restoration_model, state="readonly")
-        face_model["values"] = ["GFPGAN", "CodeFormer"]
-        face_model.grid(row=13, column=0, columnspan=2, sticky="ew", pady=(0, theme.PADDING_SM))
-        self.face_restoration_widgets.append(face_model)
-
-        face_weight = ttk.Spinbox(
-            self,
-            from_=0.0,
-            to=1.0,
-            increment=0.05,
-            textvariable=self.face_restoration_weight,
-            width=10,
-        )
-        face_weight.grid(row=14, column=0, sticky="ew", pady=(0, theme.PADDING_MD))
-        self.face_restoration_widgets.append(face_weight)
-
-        # Refiner switch controls
-        ttk.Label(self, text="Refiner Switch", style=theme.STATUS_STRONG_LABEL_STYLE).grid(
-            row=15, column=0, sticky="w", columnspan=2
-        )
-        refiner_ratio = ttk.Spinbox(
-            self,
-            from_=0.0,
-            to=1.0,
-            increment=0.05,
-            textvariable=self.refiner_switch_at,
-            width=10,
-            wrap=True,
-            command=self._update_refiner_mapping_label,
-        )
-        refiner_ratio.grid(row=16, column=0, sticky="ew", pady=(0, theme.PADDING_SM))
-        self.txt2img_widgets["refiner_switch_at"] = refiner_ratio
-
-        refiner_steps_spin = ttk.Spinbox(
-            self,
-            from_=0,
-            to=200,
-            textvariable=self.refiner_switch_steps,
-            width=10,
-            wrap=True,
-            command=self._update_refiner_mapping_label,
-        )
-        refiner_steps_spin.grid(row=16, column=1, sticky="ew", pady=(0, theme.PADDING_SM))
-        self.txt2img_widgets["refiner_switch_steps"] = refiner_steps_spin
-
-        self.refiner_mapping_label = ttk.Label(self, text="", style=theme.STATUS_LABEL_STYLE)
-        self.refiner_mapping_label.grid(row=17, column=0, columnspan=2, sticky="w")
-
-        self.config_status_label = ttk.Label(self, text="", style=theme.STATUS_LABEL_STYLE)
-        self.config_status_label.grid(row=18, column=0, columnspan=2, sticky="w")
-
-        self._toggle_face_restoration()
-        self._update_refiner_mapping_label()
-
-    def refresh_from_controller(
-        self,
-        config: dict[str, Any],
-        model_options: list[str],
-        sampler_options: list[str],
-    ) -> None:
-        """Sync widget values with controller state and available options."""
-        if model_options:
-            self.model_combo["values"] = model_options
-        if sampler_options:
-            self.sampler_combo["values"] = sampler_options
-
-        self.model_var.set(config.get("model", ""))
-        self.sampler_var.set(config.get("sampler_name", ""))
-        self.width_var.set(str(config.get("width", "")))
-        self.height_var.set(str(config.get("height", "")))
-        self.steps_var.set(str(config.get("steps", "")))
-        self.cfg_var.set(str(config.get("cfg_scale", "")))
-
-    def _handle_model_change(self, _event: tk.Event | None) -> None:
-        self._notify_change("model", self.model_var.get())
-
-    def _handle_sampler_change(self, _event: tk.Event | None) -> None:
-        self._notify_change("sampler_name", self.sampler_var.get())
-
-    def _handle_resolution_change(self, _event: tk.Event | None) -> None:
-        self._notify_change("width", self.width_var.get())
-        self._notify_change("height", self.height_var.get())
-
-    def _handle_steps_change(self, _event: tk.Event | None) -> None:
-        self._notify_change("steps", self.steps_var.get())
-
-    def _handle_cfg_change(self, _event: tk.Event | None) -> None:
-        self._notify_change("cfg_scale", self.cfg_var.get())
-
-    def _toggle_face_restoration(self) -> None:
-        """Show/hide face restoration widgets based on toggle."""
-        show = bool(self.face_restoration_enabled.get())
-        for widget in self.face_restoration_widgets[1:]:
-            if show:
-                widget.grid()
-            else:
-                widget.grid_remove()
-
-    def _update_refiner_mapping_label(self) -> None:
-        """Update label showing refiner switch mapping."""
-        total_steps = max(int(self.steps_var.get() or 0), 1)
-        ratio = float(self.refiner_switch_at.get() or 0)
-        switch_steps = int(self.refiner_switch_steps.get() or 0)
-        if switch_steps > 0:
-            ratio = min(max(switch_steps / total_steps, 0.0), 1.0)
-        else:
-            switch_steps = int(total_steps * ratio)
-        self.refiner_mapping_label.config(
-            text=f"Refiner starts at step {switch_steps}/{total_steps} (ratio={ratio:.3f})"
-        )
-
-    def _notify_change(self, field: str, value: Any) -> None:
-        if self.on_change:
-            self.on_change(field, value)
-
-    def get_config(self) -> dict[str, Any]:
-        """Return a minimal config dict for tests/legacy callers."""
-        cfg = {
-            "txt2img": {
-                "model": self.model_var.get(),
-                "sampler_name": self.sampler_var.get(),
-                "width": int(self.width_var.get() or 0),
-                "height": int(self.height_var.get() or 0),
-                "steps": int(self.steps_var.get() or 0),
-                "cfg_scale": float(self.cfg_var.get() or 0),
-                "hires_steps": int(self.hires_steps_var.get() or 0),
-                "face_restoration_enabled": bool(self.face_restoration_enabled.get()),
-                "face_restoration_model": self.face_restoration_model.get(),
-                "face_restoration_weight": float(self.face_restoration_weight.get() or 0),
-                "refiner_switch_at": float(self.refiner_switch_at.get() or 0),
-                "refiner_switch_steps": int(self.refiner_switch_steps.get() or 0),
-            }
-        }
-        return cfg
+# This legacy config panel has been archived to archive/gui_v1/config_panel.py
+# It is kept as a stub to prevent new code from depending on it.

```

---

## Patch: stub out `src/gui/pipeline_controls_panel.py`

```diff
--- a/src/gui/pipeline_controls_panel.py
+++ b/src/gui/pipeline_controls_panel.py
@@ -1,600 +1,2 @@
-"""
-Pipeline Controls Panel - UI component for configuring pipeline execution.
-"""
-
-import logging
-import re
-import tkinter as tk
-from tkinter import ttk
-from typing import Any, Callable
-
-logger = logging.getLogger(__name__)
-
-
-class PipelineControlsPanel(ttk.Frame):
-    def get_settings(self) -> dict[str, Any]:
-        """
-        Return current toggles and loop/batch settings as a dictionary.
-        """
-        try:
-            loop_count = int(self.loop_count_var.get())
-        except ValueError:
-            loop_count = 1
-
-        try:
-            images_per_prompt = int(self.images_per_prompt_var.get())
-        except ValueError:
-            images_per_prompt = 1
-
-        return {
-            "txt2img_enabled": bool(self.txt2img_enabled.get()),
-            "img2img_enabled": bool(self.img2img_enabled.get()),
-            "adetailer_enabled": bool(self.adetailer_enabled.get()),
-            "upscale_enabled": bool(self.upscale_enabled.get()),
-            "video_enabled": bool(self.video_enabled.get()),
-            # Global negative per-stage toggles
-            "apply_global_negative_txt2img": bool(self.global_neg_txt2img.get()),
-            "apply_global_negative_img2img": bool(self.global_neg_img2img.get()),
-            "apply_global_negative_upscale": bool(self.global_neg_upscale.get()),
-            "apply_global_negative_adetailer": bool(self.global_neg_adetailer.get()),
-            "loop_type": self.loop_type_var.get(),
-            "loop_count": loop_count,
-            "pack_mode": self.pack_mode_var.get(),
-            "images_per_prompt": images_per_prompt,
-            "model_matrix": self._parse_model_matrix(self.model_matrix_var.get()),
-            "hypernetworks": self._parse_hypernetworks(self.hypernetworks_var.get()),
-            "variant_mode": str(self.variant_mode_var.get()).strip().lower() or "fanout",
-        }
-
-    def get_state(self) -> dict:
-        """
-        Return the current state of the panel as a dictionary.
-        Includes stage toggles, loop config, and batch config.
-        """
-        return {
-            "txt2img_enabled": bool(self.txt2img_enabled.get()),
-            "img2img_enabled": bool(self.img2img_enabled.get()),
-            "adetailer_enabled": bool(self.adetailer_enabled.get()),
-            "upscale_enabled": bool(self.upscale_enabled.get()),
-            "video_enabled": bool(self.video_enabled.get()),
-            "apply_global_negative_txt2img": bool(self.global_neg_txt2img.get()),
-            "apply_global_negative_img2img": bool(self.global_neg_img2img.get()),
-            "apply_global_negative_upscale": bool(self.global_neg_upscale.get()),
-            "apply_global_negative_adetailer": bool(self.global_neg_adetailer.get()),
-            "loop_type": self.loop_type_var.get(),
-            "loop_count": int(self.loop_count_var.get()),
-            "pack_mode": self.pack_mode_var.get(),
-            "images_per_prompt": int(self.images_per_prompt_var.get()),
-            "model_matrix": self._parse_model_matrix(self.model_matrix_var.get()),
-            "hypernetworks": self._parse_hypernetworks(self.hypernetworks_var.get()),
-            "variant_mode": str(self.variant_mode_var.get()),
-        }
-
-    def set_state(self, state: dict) -> None:
-        """
-        Restore the panel state from a dictionary.
-        Ignores missing keys and type errors.
-        """
-        self._suspend_callbacks = True
-        try:
-            try:
-                if "txt2img_enabled" in state:
-                    self.txt2img_enabled.set(bool(state["txt2img_enabled"]))
-                if "img2img_enabled" in state:
-                    self.img2img_enabled.set(bool(state["img2img_enabled"]))
-                if "adetailer_enabled" in state:
-                    self.adetailer_enabled.set(bool(state["adetailer_enabled"]))
-                if "upscale_enabled" in state:
-                    self.upscale_enabled.set(bool(state["upscale_enabled"]))
-                if "video_enabled" in state:
-                    self.video_enabled.set(bool(state["video_enabled"]))
-                if "apply_global_negative_txt2img" in state:
-                    self.global_neg_txt2img.set(bool(state["apply_global_negative_txt2img"]))
-                if "apply_global_negative_img2img" in state:
-                    self.global_neg_img2img.set(bool(state["apply_global_negative_img2img"]))
-                if "apply_global_negative_upscale" in state:
-                    self.global_neg_upscale.set(bool(state["apply_global_negative_upscale"]))
-                if "apply_global_negative_adetailer" in state:
-                    self.global_neg_adetailer.set(bool(state["apply_global_negative_adetailer"]))
-                if "loop_type" in state:
-                    self.loop_type_var.set(str(state["loop_type"]))
-                if "loop_count" in state:
-                    self.loop_count_var.set(str(state["loop_count"]))
-                if "pack_mode" in state:
-                    self.pack_mode_var.set(str(state["pack_mode"]))
-                if "images_per_prompt" in state:
-                    self.images_per_prompt_var.set(str(state["images_per_prompt"]))
-                if "model_matrix" in state:
-                    self._set_model_matrix_display(state["model_matrix"])
-                if "hypernetworks" in state:
-                    self._set_hypernetwork_display(state["hypernetworks"])
-                if "variant_mode" in state:
-                    self.variant_mode_var.set(str(state["variant_mode"]))
-            except Exception as e:
-                logger.warning(f"PipelineControlsPanel: Failed to restore state: {e}")
-        finally:
-            self._suspend_callbacks = False
-
-    def refresh_dynamic_lists_from_api(self, client) -> None:
-        """Update cached sampler/upscaler lists from the API client."""
-
-        if client is None:
-            return
-
-        try:
-            sampler_entries = getattr(client, "samplers", []) or []
-            sampler_names = [entry.get("name", "") for entry in sampler_entries if entry.get("name")]
-            self.set_sampler_options(sampler_names)
-        except Exception:
-            logger.exception("PipelineControlsPanel: Failed to refresh sampler options from API")
-
-        try:
-            upscaler_entries = getattr(client, "upscalers", []) or []
-            upscaler_names = [entry.get("name", "") for entry in upscaler_entries if entry.get("name")]
-            self.set_upscaler_options(upscaler_names)
-        except Exception:
-            logger.exception("PipelineControlsPanel: Failed to refresh upscaler options from API")
-
-    def set_sampler_options(self, sampler_names: list[str]) -> None:
-        """Cache sampler names for future pipeline controls."""
-
-        cleaned: list[str] = []
-        for name in sampler_names or []:
-            if not name:
-                continue
-            text = str(name).strip()
-            if text and text not in cleaned:
-                cleaned.append(text)
-        cleaned.sort(key=str.lower)
-        self._sampler_options = cleaned
-
-    def set_upscaler_options(self, upscaler_names: list[str]) -> None:
-        """Cache upscaler names for future pipeline controls."""
-
-        cleaned: list[str] = []
-        for name in upscaler_names or []:
-            if not name:
-                continue
-            text = str(name).strip()
-            if text and text not in cleaned:
-                cleaned.append(text)
-        cleaned.sort(key=str.lower)
-        self._upscaler_options = cleaned
-
-    """
-    A UI panel for pipeline execution controls.
-
-    This panel handles:
-    - Loop configuration (single/stages/pipeline)
-    - Loop count settings
-    - Batch configuration (pack mode selection)
-    - Images per prompt setting
-
-    It exposes a get_settings() method to retrieve current configuration.
-    """
-
-    def __init__(
-        self,
-        parent: tk.Widget,
-        initial_state: dict[str, Any] | None = None,
-        stage_vars: dict[str, tk.BooleanVar] | None = None,
-        show_variant_controls: bool = False,
-        on_change: Callable[[], None] | None = None,
-        **kwargs,
-    ):
-        """
-        Initialize the PipelineControlsPanel.
-
-        Args:
-            parent: Parent widget
-            initial_state: Optional dictionary used to pre-populate control values
-            stage_vars: Optional mapping of existing stage BooleanVars
-            **kwargs: Additional frame options
-        """
-        super().__init__(parent, **kwargs)
-        self.parent = parent
-        self._initial_state = initial_state or {}
-        self._stage_vars = stage_vars or {}
-        self._show_variant_controls = show_variant_controls
-        self._on_change = on_change
-        self._suspend_callbacks = False
-        self._trace_handles: list[tuple[tk.Variable, str]] = []
-        self._sampler_options: list[str] = []
-        self._upscaler_options: list[str] = []
-
-        # Initialize control variables
-        self._init_variables()
-
-        # Build UI
-        self._build_ui()
-        self._bind_change_listeners()
-
-    def _init_variables(self):
-        """Initialize all control variables with defaults."""
-        state = self._initial_state
-
-        # Stage toggles
-        self.txt2img_enabled = self._stage_vars.get("txt2img") or tk.BooleanVar(
-            value=bool(state.get("txt2img_enabled", True))
-        )
-        self.img2img_enabled = self._stage_vars.get("img2img") or tk.BooleanVar(
-            value=bool(state.get("img2img_enabled", True))
-        )
-        self.adetailer_enabled = self._stage_vars.get("adetailer") or tk.BooleanVar(
-            value=bool(state.get("adetailer_enabled", False))
-        )
-        self.upscale_enabled = self._stage_vars.get("upscale") or tk.BooleanVar(
-            value=bool(state.get("upscale_enabled", True))
-        )
-        self.video_enabled = self._stage_vars.get("video") or tk.BooleanVar(
-            value=bool(state.get("video_enabled", False))
-        )
-        # Global negative per-stage toggles (default True for backward compatibility)
-        self.global_neg_txt2img = tk.BooleanVar(
-            value=bool(state.get("apply_global_negative_txt2img", True))
-        )
-        self.global_neg_img2img = tk.BooleanVar(
-            value=bool(state.get("apply_global_negative_img2img", True))
-        )
-        self.global_neg_upscale = tk.BooleanVar(
-            value=bool(state.get("apply_global_negative_upscale", True))
-        )
-        self.global_neg_adetailer = tk.BooleanVar(
-            value=bool(state.get("apply_global_negative_adetailer", True))
-        )
-
-        # Loop configuration
-        self.loop_type_var = tk.StringVar(value=str(state.get("loop_type", "single")))
-        self.loop_count_var = tk.StringVar(value=str(state.get("loop_count", 1)))
-
-        # Batch configuration
-        self.pack_mode_var = tk.StringVar(value=str(state.get("pack_mode", "selected")))
-        self.images_per_prompt_var = tk.StringVar(value=str(state.get("images_per_prompt", 1)))
-        matrix_state = state.get("model_matrix", [])
-        if isinstance(matrix_state, list):
-            matrix_display = ", ".join(matrix_state)
-        else:
-            matrix_display = str(matrix_state)
-        self.model_matrix_var = tk.StringVar(value=matrix_display)
-
-        hyper_state = state.get("hypernetworks", [])
-        if isinstance(hyper_state, list):
-            hyper_display = ", ".join(
-                f"{item.get('name')}:{item.get('strength', 1.0)}" for item in hyper_state if item
-            )
-        else:
-            hyper_display = str(hyper_state)
-        self.hypernetworks_var = tk.StringVar(value=hyper_display)
-        self.variant_mode_var = tk.StringVar(value=str(state.get("variant_mode", "fanout")))
-
-    def _build_ui(self):
-        """Build the panel UI."""
-        # Pipeline controls frame
-        pipeline_frame = ttk.LabelFrame(
-            self, text="🚀 Pipeline Controls", style="Dark.TLabelframe", padding=5
-        )
-        pipeline_frame.pack(fill=tk.BOTH, expand=True)
-
-        # Loop configuration - compact
-        self._build_loop_config(pipeline_frame)
-
-        # Batch configuration - compact
-        self._build_batch_config(pipeline_frame)
-        if self._show_variant_controls:
-            self._build_variant_config(pipeline_frame)
-        self._build_global_negative_toggles(pipeline_frame)
-
-    def _bind_change_listeners(self) -> None:
-        """Attach variable traces to notify the host of user-driven changes."""
-        if not self._on_change:
-            return
-
-        vars_to_watch: list[tk.Variable] = [
-            self.loop_type_var,
-            self.loop_count_var,
-            self.pack_mode_var,
-            self.images_per_prompt_var,
-            self.model_matrix_var,
-            self.hypernetworks_var,
-            self.variant_mode_var,
-            self.txt2img_enabled,
-            self.img2img_enabled,
-            self.adetailer_enabled,
-            self.upscale_enabled,
-            self.video_enabled,
-            self.global_neg_txt2img,
-            self.global_neg_img2img,
-            self.global_neg_upscale,
-            self.global_neg_adetailer,
-        ]
-
-        callback = lambda *_: self._notify_change()
-        for var in vars_to_watch:
-            try:
-                handle = var.trace_add("write", callback)
-                self._trace_handles.append((var, handle))
-            except Exception:
-                continue
-
-    def _notify_change(self) -> None:
-        if self._suspend_callbacks or not self._on_change:
-            return
-        try:
-            self._on_change()
-        except Exception:
-            logger.debug("PipelineControlsPanel: change callback failed", exc_info=True)
-
-    def _build_loop_config(self, parent):
-        """Build loop configuration controls with logging."""
-        loop_frame = ttk.LabelFrame(parent, text="Loop Config", style="Dark.TLabelframe", padding=5)
-        loop_frame.pack(fill=tk.X, pady=(0, 5))
-
-        def log_loop_type():
-            logger.info(f"PipelineControlsPanel: loop_type set to {self.loop_type_var.get()}")
-
-        ttk.Radiobutton(
-            loop_frame,
-            text="Single",
-            variable=self.loop_type_var,
-            value="single",
-            style="Dark.TRadiobutton",
-            command=log_loop_type,
-        ).pack(anchor=tk.W, pady=1)
-
-        ttk.Radiobutton(
-            loop_frame,
-            text="Loop stages",
-            variable=self.loop_type_var,
-            value="stages",
-            style="Dark.TRadiobutton",
-            command=log_loop_type,
-        ).pack(anchor=tk.W, pady=1)
-
-        ttk.Radiobutton(
-            loop_frame,
-            text="Loop pipeline",
-            variable=self.loop_type_var,
-            value="pipeline",
-            style="Dark.TRadiobutton",
-            command=log_loop_type,
-        ).pack(anchor=tk.W, pady=1)
-
-        # Loop count - inline
-        count_frame = ttk.Frame(loop_frame, style="Dark.TFrame")
-        count_frame.pack(fill=tk.X, pady=2)
-
-        ttk.Label(count_frame, text="Count:", style="Dark.TLabel", width=6).pack(side=tk.LEFT)
-
-        def log_loop_count(*_):
-            logger.info(f"PipelineControlsPanel: loop_count set to {self.loop_count_var.get()}")
-
-        self.loop_count_var.trace_add("write", log_loop_count)
-        count_spin = ttk.Spinbox(
-            count_frame,
-            from_=1,
-            to=100,
-            width=4,
-            textvariable=self.loop_count_var,
-            style="Dark.TSpinbox",
-        )
-        count_spin.pack(side=tk.LEFT, padx=2)
-
-    def _build_batch_config(self, parent):
-        """Build batch configuration controls with logging."""
-        batch_frame = ttk.LabelFrame(
-            parent, text="Batch Config", style="Dark.TLabelframe", padding=5
-        )
-        batch_frame.pack(fill=tk.X, pady=(0, 5))
-
-        def log_pack_mode():
-            logger.info(f"PipelineControlsPanel: pack_mode set to {self.pack_mode_var.get()}")
-
-        ttk.Radiobutton(
-            batch_frame,
-            text="Selected packs",
-            variable=self.pack_mode_var,
-            value="selected",
-            style="Dark.TRadiobutton",
-            command=log_pack_mode,
-        ).pack(anchor=tk.W, pady=1)
-
-        ttk.Radiobutton(
-            batch_frame,
-            text="All packs",
-            variable=self.pack_mode_var,
-            value="all",
-            style="Dark.TRadiobutton",
-            command=log_pack_mode,
-        ).pack(anchor=tk.W, pady=1)
-
-        ttk.Radiobutton(
-            batch_frame,
-            text="Custom list",
-            variable=self.pack_mode_var,
-            value="custom",
-            style="Dark.TRadiobutton",
-            command=log_pack_mode,
-        ).pack(anchor=tk.W, pady=1)
-
-        # Images per prompt - inline
-        images_frame = ttk.Frame(batch_frame, style="Dark.TFrame")
-        images_frame.pack(fill=tk.X, pady=2)
-
-        ttk.Label(images_frame, text="Images:", style="Dark.TLabel", width=6).pack(side=tk.LEFT)
-
-        def log_images_per_prompt(*_):
-            logger.info(
-                f"PipelineControlsPanel: images_per_prompt set to {self.images_per_prompt_var.get()}"
-            )
-
-        self.images_per_prompt_var.trace_add("write", log_images_per_prompt)
-        images_spin = ttk.Spinbox(
-            images_frame,
-            from_=1,
-            to=10,
-            width=4,
-            textvariable=self.images_per_prompt_var,
-            style="Dark.TSpinbox",
-        )
-        images_spin.pack(side=tk.LEFT, padx=2)
-
-    def _build_variant_config(self, parent):
-        """Build controls for model/hypernetwork combinations."""
-        variant_frame = ttk.LabelFrame(
-            parent, text="Model Matrix & Hypernets", style="Dark.TLabelframe", padding=5
-        )
-        variant_frame.pack(fill=tk.X, pady=(0, 5))
-
-        ttk.Label(
-            variant_frame,
-            text="Model checkpoints (comma/newline separated):",
-            style="Dark.TLabel",
-        ).pack(anchor=tk.W, pady=(0, 2))
-        ttk.Entry(variant_frame, textvariable=self.model_matrix_var, width=40).pack(
-            fill=tk.X, pady=(0, 4)
-        )
-
-        ttk.Label(
-            variant_frame,
-            text="Hypernetworks (name:strength, separated by commas):",
-            style="Dark.TLabel",
-        ).pack(anchor=tk.W, pady=(4, 2))
-        ttk.Entry(variant_frame, textvariable=self.hypernetworks_var, width=40).pack(fill=tk.X)
-
-        mode_frame = ttk.Frame(variant_frame, style="Dark.TFrame")
-        mode_frame.pack(fill=tk.X, pady=(6, 0))
-        ttk.Label(mode_frame, text="Variant strategy:", style="Dark.TLabel").pack(anchor=tk.W)
-        ttk.Radiobutton(
-            mode_frame,
-            text="Fan-out (run every combo)",
-            variable=self.variant_mode_var,
-            value="fanout",
-            style="Dark.TRadiobutton",
-        ).pack(anchor=tk.W, pady=(2, 0))
-        ttk.Radiobutton(
-            mode_frame,
-            text="Rotate per prompt",
-            variable=self.variant_mode_var,
-            value="rotate",
-            style="Dark.TRadiobutton",
-        ).pack(anchor=tk.W, pady=(2, 0))
-
-    def _build_global_negative_toggles(self, parent):
-        """Build per-stage Global Negative enable toggles."""
-        frame = ttk.LabelFrame(
-            parent, text="Global Negative (per stage)", style="Dark.TLabelframe", padding=5
-        )
-        frame.pack(fill=tk.X, pady=(0, 5))
-
-        def _mk(cb_text, var, key):
-            def _log():
-                logger.info(f"PipelineControlsPanel: {key} set to {var.get()}")
-
-            ttk.Checkbutton(
-                frame, text=cb_text, variable=var, style="Dark.TCheckbutton", command=_log
-            ).pack(anchor=tk.W)
-
-        _mk("Apply to txt2img", self.global_neg_txt2img, "apply_global_negative_txt2img")
-        _mk("Apply to img2img", self.global_neg_img2img, "apply_global_negative_img2img")
-        _mk("Apply to upscale", self.global_neg_upscale, "apply_global_negative_upscale")
-        _mk("Apply to ADetailer", self.global_neg_adetailer, "apply_global_negative_adetailer")
-
-    def set_settings(self, settings: dict[str, Any]):
-        """
-        Set pipeline control settings from a dictionary.
-
-        Args:
-            settings: Dictionary containing pipeline settings
-        """
-        if "txt2img_enabled" in settings:
-            self.txt2img_enabled.set(settings["txt2img_enabled"])
-        if "img2img_enabled" in settings:
-            self.img2img_enabled.set(settings["img2img_enabled"])
-        if "adetailer_enabled" in settings:
-            self.adetailer_enabled.set(settings["adetailer_enabled"])
-        if "upscale_enabled" in settings:
-            self.upscale_enabled.set(settings["upscale_enabled"])
-        if "video_enabled" in settings:
-            self.video_enabled.set(settings["video_enabled"])
-
-        if "loop_type" in settings:
-            self.loop_type_var.set(settings["loop_type"])
-        if "loop_count" in settings:
-            self.loop_count_var.set(str(settings["loop_count"]))
-
-        if "pack_mode" in settings:
-            self.pack_mode_var.set(settings["pack_mode"])
-        if "images_per_prompt" in settings:
-            self.images_per_prompt_var.set(str(settings["images_per_prompt"]))
-        if "model_matrix" in settings:
-            self._set_model_matrix_display(settings["model_matrix"])
-        if "hypernetworks" in settings:
-            self._set_hypernetwork_display(settings["hypernetworks"])
-        if "variant_mode" in settings:
-            self.variant_mode_var.set(str(settings["variant_mode"]))
-
-    def apply_config(self, cfg: dict[str, Any]) -> None:
-        """Apply a configuration payload (e.g., from packs/presets) to the controls."""
-        if not cfg:
-            return
-
-        target = cfg.get("pipeline") if isinstance(cfg.get("pipeline"), dict) else cfg
-        if not isinstance(target, dict):
-            return
-
-        self._suspend_callbacks = True
-        try:
-            self.set_settings(target)
-        finally:
-            self._suspend_callbacks = False
-
-    # ------------------------------------------------------------------
-    # Parsing helpers
-    # ------------------------------------------------------------------
-
-    def _parse_model_matrix(self, raw: str) -> list[str]:
-        if not raw:
-            return []
-        values: list[str] = []
-        for chunk in re.split(r"[\n,]+", raw):
-            sanitized = chunk.strip()
-            if sanitized:
-                values.append(sanitized)
-        return values
-
-    def _parse_hypernetworks(self, raw: str) -> list[dict[str, Any]]:
-        if not raw:
-            return []
-        entries: list[dict[str, Any]] = []
-        for chunk in re.split(r"[\n,]+", raw):
-            sanitized = chunk.strip()
-            if not sanitized:
-                continue
-            if ":" in sanitized:
-                name, strength = sanitized.split(":", 1)
-                try:
-                    weight = float(strength.strip())
-                except ValueError:
-                    weight = 1.0
-                entries.append({"name": name.strip(), "strength": weight})
-            else:
-                entries.append({"name": sanitized, "strength": 1.0})
-        return entries
-
-    def _set_model_matrix_display(self, value):
-        if isinstance(value, list):
-            self.model_matrix_var.set(", ".join(value))
-        else:
-            self.model_matrix_var.set(str(value))
-
-    def _set_hypernetwork_display(self, value):
-        if isinstance(value, list):
-            self.hypernetworks_var.set(
-                ", ".join(
-                    f"{item.get('name')}:{item.get('strength', 1.0)}"
-                    for item in value
-                    if item and item.get("name")
-                )
-            )
-        else:
-            self.hypernetworks_var.set(str(value))
+# This legacy pipeline controls panel has been archived to archive/gui_v1/pipeline_controls_panel.py
+# It is kept as a stub to prevent new code from depending on it.

```

---

## Patch: stub out `src/gui/img2img_stage_card.py`

```diff
--- a/src/gui/img2img_stage_card.py
+++ b/src/gui/img2img_stage_card.py
@@ -1,125 +1,2 @@
-"""img2img stage card for PipelinePanelV2."""
-
-from __future__ import annotations
-
-import tkinter as tk
-from tkinter import ttk
-
-from . import theme as theme_mod
-
-
-class Img2ImgStageCard(ttk.Frame):
-    """Stage card managing img2img fields."""
-
-    FIELD_NAMES = [
-        "model",
-        "vae",
-        "sampler_name",
-        "denoising_strength",
-        "cfg_scale",
-        "steps",
-    ]
-
-    def __init__(self, master: tk.Misc, *, controller=None, theme=None, **kwargs) -> None:
-        style_name = getattr(theme, "SURFACE_FRAME_STYLE", theme_mod.SURFACE_FRAME_STYLE)
-        super().__init__(master, style=style_name, padding=theme_mod.PADDING_MD, **kwargs)
-        self.controller = controller
-        self.theme = theme
-
-        header_style = getattr(theme, "STATUS_STRONG_LABEL_STYLE", theme_mod.STATUS_STRONG_LABEL_STYLE)
-        self.header_label = ttk.Label(self, text="img2img Settings", style=header_style)
-        self.header_label.pack(anchor=tk.W, pady=(0, 4))
-
-        body_style = getattr(theme, "SURFACE_FRAME_STYLE", theme_mod.SURFACE_FRAME_STYLE)
-        self.body = ttk.Frame(self, style=body_style)
-        self.body.pack(fill=tk.BOTH, expand=True)
-
-        self._vars: dict[str, tk.StringVar] = {}
-
-        for idx, field in enumerate(self.FIELD_NAMES):
-            var = tk.StringVar()
-            self._vars[field] = var
-            if field == "steps":
-                self._add_spinbox(self.body, field, var, idx, from_=1, to=200)
-            elif field in {"denoising_strength", "cfg_scale"}:
-                increment = 0.05 if field == "denoising_strength" else 0.5
-                to_value = 1.0 if field == "denoising_strength" else 30.0
-                self._add_spinbox(self.body, field, var, idx, from_=0.0, to=to_value, increment=increment)
-            else:
-                self._add_entry(self.body, field, var, idx)
-
-    def _add_entry(self, parent, label, variable, row):
-        ttk.Label(parent, text=label.replace("_", " ").title(), style="Dark.TLabel").grid(
-            row=row, column=0, sticky=tk.W, pady=2
-        )
-        entry = ttk.Entry(parent, textvariable=variable, width=28)
-        entry.grid(row=row, column=1, sticky="ew", pady=2)
-        parent.columnconfigure(1, weight=1)
-        return entry
-
-    def _add_spinbox(self, parent, label, variable, row, *, from_, to, increment=1.0):
-        ttk.Label(parent, text=label.replace("_", " ").title(), style="Dark.TLabel").grid(
-            row=row, column=0, sticky=tk.W, pady=2
-        )
-        spin = ttk.Spinbox(
-            parent,
-            textvariable=variable,
-            from_=from_,
-            to=to,
-            increment=increment,
-            width=10,
-        )
-        spin.grid(row=row, column=1, sticky="ew", pady=2)
-        return spin
-
-    def load_from_config(self, config: dict | None) -> None:
-        section = self._get_section(config)
-        for field in self.FIELD_NAMES:
-            self._vars[field].set(self._coerce_str(section.get(field)))
-
-    def to_config_dict(self) -> dict:
-        section: dict[str, object] = {}
-        for field in self.FIELD_NAMES:
-            value = self._vars[field].get()
-            if field == "steps":
-                converted = self._coerce_int(value)
-            elif field in {"denoising_strength", "cfg_scale"}:
-                converted = self._coerce_float(value)
-            else:
-                converted = value.strip() if isinstance(value, str) else ""
-                if not converted:
-                    converted = None
-            if converted not in (None, ""):
-                section[field] = converted
-        return {"img2img": section} if section else {}
-
-    @staticmethod
-    def _get_section(config: dict | None) -> dict:
-        if isinstance(config, dict):
-            section = config.get("img2img") or {}
-            return section if isinstance(section, dict) else {}
-        return {}
-
-    @staticmethod
-    def _coerce_str(value: object) -> str:
-        if value is None:
-            return ""
-        return str(value)
-
-    @staticmethod
-    def _coerce_int(value: object) -> int | None:
-        try:
-            if value is None or str(value).strip() == "":
-                return None
-            return int(float(value))
-        except (ValueError, TypeError):
-            return None
-
-    @staticmethod
-    def _coerce_float(value: object) -> float | None:
-        try:
-            if value is None or str(value).strip() == "":
-                return None
-            return float(value)
-        except (ValueError, TypeError):
-            return None
+# This legacy Img2Img stage card has been archived to archive/gui_v1/img2img_stage_card.py
+# It is kept as a stub to prevent new code from depending on it.

```

---

## Patch: add `archive/gui_v1/config_panel.py` with archived implementation

```diff
--- /dev/null
+++ b/archive/gui_v1/config_panel.py
@@ -0,0 +1,310 @@
+# Archived legacy config panel (ConfigPanel)
+# No longer used by Phase-1 V2 GUI.
+# Retained only for reference during migration.
+
+"""ConfigPanel for Center Zone core settings."""
+
+from __future__ import annotations
+
+import tkinter as tk
+from tkinter import ttk
+from typing import Any, Callable
+
+from . import theme
+
+MAX_DIMENSION = 2260
+
+
+class ConfigPanel(ttk.Frame):
+    """Basic configuration controls for model/sampler/resolution/steps/CFG."""
+
+    def __init__(
+        self,
+        master: tk.Misc,
+        on_change: Callable[[str, Any], None] | None = None,
+        *,
+        coordinator: Any | None = None,
+        style: str | None = None,
+        **kwargs: Any,
+    ) -> None:
+        frame_style = style or theme.SURFACE_FRAME_STYLE
+        super().__init__(master, padding=theme.PADDING_MD, style=frame_style, **kwargs)
+        self.on_change = on_change
+        self.coordinator = coordinator
+
+        self.columnconfigure(0, weight=1)
+        self.columnconfigure(1, weight=1)
+
+        self.model_var = tk.StringVar()
+        self.sampler_var = tk.StringVar()
+        self.width_var = tk.IntVar(value=512)
+        self.height_var = tk.IntVar(value=512)
+        self.steps_var = tk.IntVar(value=30)
+        self.cfg_var = tk.DoubleVar(value=7.0)
+        self.hires_steps_var = tk.IntVar(value=0)
+        self.face_restoration_enabled = tk.BooleanVar(value=False)
+        self.face_restoration_model = tk.StringVar(value="GFPGAN")
+        self.face_restoration_weight = tk.DoubleVar(value=0.5)
+        self.refiner_switch_at = tk.DoubleVar(value=0.5)
+        self.refiner_switch_steps = tk.IntVar(value=0)
+
+        # Legacy compatibility dictionaries expected by StableNewGUI
+        self.txt2img_vars: dict[str, tk.StringVar] = {
+            "model": self.model_var,
+            "sampler_name": self.sampler_var,
+            "width": self.width_var,
+            "height": self.height_var,
+            "steps": self.steps_var,
+            "cfg_scale": self.cfg_var,
+            "hires_steps": self.hires_steps_var,
+            "face_restoration_enabled": self.face_restoration_enabled,
+            "face_restoration_model": self.face_restoration_model,
+            "face_restoration_weight": self.face_restoration_weight,
+            "refiner_switch_at": self.refiner_switch_at,
+            "refiner_switch_steps": self.refiner_switch_steps,
+        }
+        self.img2img_vars: dict[str, tk.StringVar] = {
+            "model": tk.StringVar(),
+            "sampler_name": tk.StringVar(),
+        }
+        self.upscale_vars: dict[str, tk.StringVar] = {
+            "upscaler": tk.StringVar(),
+        }
+        self.api_vars: dict[str, tk.StringVar] = {"base_url": tk.StringVar()}
+        self.txt2img_widgets: dict[str, tk.Widget] = {}
+        self.upscale_widgets: dict[str, tk.Widget] = {}
+
+        ttk.Label(self, text="Model", style=theme.STATUS_STRONG_LABEL_STYLE).grid(
+            row=0, column=0, sticky="w", columnspan=2
+        )
+        self.model_combo = ttk.Combobox(
+            self,
+            textvariable=self.model_var,
+            state="readonly",
+        )
+        self.model_combo.grid(row=1, column=0, columnspan=2, sticky="ew", pady=(0, theme.PADDING_MD))
+        self.model_combo.bind("<<ComboboxSelected>>", self._handle_model_change)
+        self.txt2img_widgets["model"] = self.model_combo
+
+        ttk.Label(self, text="Sampler", style=theme.STATUS_STRONG_LABEL_STYLE).grid(
+            row=2, column=0, sticky="w", columnspan=2
+        )
+        self.sampler_combo = ttk.Combobox(
+            self,
+            textvariable=self.sampler_var,
+            state="readonly",
+        )
+        self.sampler_combo.grid(row=3, column=0, columnspan=2, sticky="ew", pady=(0, theme.PADDING_MD))
+        self.sampler_combo.bind("<<ComboboxSelected>>", self._handle_sampler_change)
+        self.txt2img_widgets["sampler_name"] = self.sampler_combo
+
+        ttk.Label(self, text="Resolution", style=theme.STATUS_STRONG_LABEL_STYLE).grid(
+            row=4, column=0, sticky="w", columnspan=2
+        )
+        width_entry = ttk.Spinbox(self, from_=64, to=MAX_DIMENSION, textvariable=self.width_var, width=8, wrap=True)
+        height_entry = ttk.Spinbox(self, from_=64, to=MAX_DIMENSION, textvariable=self.height_var, width=8, wrap=True)
+        width_entry.grid(row=5, column=0, sticky="ew", pady=(0, theme.PADDING_SM))
+        height_entry.grid(row=5, column=1, sticky="ew", pady=(0, theme.PADDING_SM))
+        width_entry.bind("<FocusOut>", self._handle_resolution_change)
+        height_entry.bind("<FocusOut>", self._handle_resolution_change)
+        self.txt2img_widgets["width"] = width_entry
+        self.txt2img_widgets["height"] = height_entry
+        self.dim_warning_label = ttk.Label(
+            self,
+            text=f"⚠️ Maximum recommended: {MAX_DIMENSION}x{MAX_DIMENSION}",
+            style=theme.STATUS_LABEL_STYLE,
+        )
+        self.dim_warning_label.grid(row=6, column=0, columnspan=2, sticky="w", pady=(0, theme.PADDING_SM))
+
+        ttk.Label(self, text="Steps", style=theme.STATUS_STRONG_LABEL_STYLE).grid(
+            row=7, column=0, sticky="w"
+        )
+        ttk.Label(self, text="CFG", style=theme.STATUS_STRONG_LABEL_STYLE).grid(
+            row=7, column=1, sticky="w"
+        )
+
+        steps_spin = ttk.Spinbox(
+            self,
+            from_=1,
+            to=200,
+            textvariable=self.steps_var,
+            width=10,
+            wrap=True,
+        )
+        cfg_spin = ttk.Spinbox(
+            self,
+            from_=1.0,
+            to=30.0,
+            increment=0.5,
+            textvariable=self.cfg_var,
+            width=10,
+        )
+        steps_spin.grid(row=8, column=0, sticky="ew", pady=(0, theme.PADDING_SM))
+        cfg_spin.grid(row=8, column=1, sticky="ew", pady=(0, theme.PADDING_SM))
+        steps_spin.bind("<FocusOut>", self._handle_steps_change)
+        cfg_spin.bind("<FocusOut>", self._handle_cfg_change)
+        self.txt2img_widgets["steps"] = steps_spin
+        self.txt2img_widgets["cfg_scale"] = cfg_spin
+
+        ttk.Label(self, text="Hires Fix Steps", style=theme.STATUS_STRONG_LABEL_STYLE).grid(
+            row=9, column=0, sticky="w", columnspan=2
+        )
+        hires_spin = ttk.Spinbox(
+            self,
+            from_=0,
+            to=200,
+            textvariable=self.hires_steps_var,
+            width=10,
+            wrap=True,
+        )
+        hires_spin.grid(row=10, column=0, sticky="ew", pady=(0, theme.PADDING_SM))
+        self.txt2img_widgets["hires_steps"] = hires_spin
+
+        # Face restoration controls
+        ttk.Label(self, text="Face Restoration", style=theme.STATUS_STRONG_LABEL_STYLE).grid(
+            row=11, column=0, sticky="w", columnspan=2
+        )
+        self.face_restoration_widgets: list[tk.Widget] = []
+        face_toggle = ttk.Checkbutton(
+            self,
+            text="Enable",
+            variable=self.face_restoration_enabled,
+            command=self._toggle_face_restoration,
+        )
+        face_toggle.grid(row=12, column=0, sticky="w")
+        self.face_restoration_widgets.append(face_toggle)
+
+        face_model = ttk.Combobox(self, textvariable=self.face_restoration_model, state="readonly")
+        face_model["values"] = ["GFPGAN", "CodeFormer"]
+        face_model.grid(row=13, column=0, columnspan=2, sticky="ew", pady=(0, theme.PADDING_SM))
+        self.face_restoration_widgets.append(face_model)
+
+        face_weight = ttk.Spinbox(
+            self,
+            from_=0.0,
+            to=1.0,
+            increment=0.05,
+            textvariable=self.face_restoration_weight,
+            width=10,
+        )
+        face_weight.grid(row=14, column=0, sticky="ew", pady=(0, theme.PADDING_MD))
+        self.face_restoration_widgets.append(face_weight)
+
+        # Refiner switch controls
+        ttk.Label(self, text="Refiner Switch", style=theme.STATUS_STRONG_LABEL_STYLE).grid(
+            row=15, column=0, sticky="w", columnspan=2
+        )
+        refiner_ratio = ttk.Spinbox(
+            self,
+            from_=0.0,
+            to=1.0,
+            increment=0.05,
+            textvariable=self.refiner_switch_at,
+            width=10,
+            wrap=True,
+            command=self._update_refiner_mapping_label,
+        )
+        refiner_ratio.grid(row=16, column=0, sticky="ew", pady=(0, theme.PADDING_SM))
+        self.txt2img_widgets["refiner_switch_at"] = refiner_ratio
+
+        refiner_steps_spin = ttk.Spinbox(
+            self,
+            from_=0,
+            to=200,
+            textvariable=self.refiner_switch_steps,
+            width=10,
+            wrap=True,
+            command=self._update_refiner_mapping_label,
+        )
+        refiner_steps_spin.grid(row=16, column=1, sticky="ew", pady=(0, theme.PADDING_SM))
+        self.txt2img_widgets["refiner_switch_steps"] = refiner_steps_spin
+
+        self.refiner_mapping_label = ttk.Label(self, text="", style=theme.STATUS_LABEL_STYLE)
+        self.refiner_mapping_label.grid(row=17, column=0, columnspan=2, sticky="w")
+
+        self.config_status_label = ttk.Label(self, text="", style=theme.STATUS_LABEL_STYLE)
+        self.config_status_label.grid(row=18, column=0, columnspan=2, sticky="w")
+
+        self._toggle_face_restoration()
+        self._update_refiner_mapping_label()
+
+    def refresh_from_controller(
+        self,
+        config: dict[str, Any],
+        model_options: list[str],
+        sampler_options: list[str],
+    ) -> None:
+        """Sync widget values with controller state and available options."""
+        if model_options:
+            self.model_combo["values"] = model_options
+        if sampler_options:
+            self.sampler_combo["values"] = sampler_options
+
+        self.model_var.set(config.get("model", ""))
+        self.sampler_var.set(config.get("sampler_name", ""))
+        self.width_var.set(str(config.get("width", "")))
+        self.height_var.set(str(config.get("height", "")))
+        self.steps_var.set(str(config.get("steps", "")))
+        self.cfg_var.set(str(config.get("cfg_scale", "")))
+
+    def _handle_model_change(self, _event: tk.Event | None) -> None:
+        self._notify_change("model", self.model_var.get())
+
+    def _handle_sampler_change(self, _event: tk.Event | None) -> None:
+        self._notify_change("sampler_name", self.sampler_var.get())
+
+    def _handle_resolution_change(self, _event: tk.Event | None) -> None:
+        self._notify_change("width", self.width_var.get())
+        self._notify_change("height", self.height_var.get())
+
+    def _handle_steps_change(self, _event: tk.Event | None) -> None:
+        self._notify_change("steps", self.steps_var.get())
+
+    def _handle_cfg_change(self, _event: tk.Event | None) -> None:
+        self._notify_change("cfg_scale", self.cfg_var.get())
+
+    def _toggle_face_restoration(self) -> None:
+        """Show/hide face restoration widgets based on toggle."""
+        show = bool(self.face_restoration_enabled.get())
+        for widget in self.face_restoration_widgets[1:]:
+            if show:
+                widget.grid()
+            else:
+                widget.grid_remove()
+
+    def _update_refiner_mapping_label(self) -> None:
+        """Update label showing refiner switch mapping."""
+        total_steps = max(int(self.steps_var.get() or 0), 1)
+        ratio = float(self.refiner_switch_at.get() or 0)
+        switch_steps = int(self.refiner_switch_steps.get() or 0)
+        if switch_steps > 0:
+            ratio = min(max(switch_steps / total_steps, 0.0), 1.0)
+        else:
+            switch_steps = int(total_steps * ratio)
+        self.refiner_mapping_label.config(
+            text=f"Refiner starts at step {switch_steps}/{total_steps} (ratio={ratio:.3f})"
+        )
+
+    def _notify_change(self, field: str, value: Any) -> None:
+        if self.on_change:
+            self.on_change(field, value)
+
+    def get_config(self) -> dict[str, Any]:
+        """Return a minimal config dict for tests/legacy callers."""
+        cfg = {
+            "txt2img": {
+                "model": self.model_var.get(),
+                "sampler_name": self.sampler_var.get(),
+                "width": int(self.width_var.get() or 0),
+                "height": int(self.height_var.get() or 0),
+                "steps": int(self.steps_var.get() or 0),
+                "cfg_scale": float(self.cfg_var.get() or 0),
+                "hires_steps": int(self.hires_steps_var.get() or 0),
+                "face_restoration_enabled": bool(self.face_restoration_enabled.get()),
+                "face_restoration_model": self.face_restoration_model.get(),
+                "face_restoration_weight": float(self.face_restoration_weight.get() or 0),
+                "refiner_switch_at": float(self.refiner_switch_at.get() or 0),
+                "refiner_switch_steps": int(self.refiner_switch_steps.get() or 0),
+            }
+        }
+        return cfg

```

---

## Patch: add `archive/gui_v1/pipeline_controls_panel.py` with archived implementation

```diff
--- /dev/null
+++ b/archive/gui_v1/pipeline_controls_panel.py
@@ -0,0 +1,604 @@
+# Archived legacy pipeline controls panel (PipelineControlsPanel)
+# No longer used by Phase-1 V2 GUI.
+# Retained only for reference during migration.
+
+"""
+Pipeline Controls Panel - UI component for configuring pipeline execution.
+"""
+
+import logging
+import re
+import tkinter as tk
+from tkinter import ttk
+from typing import Any, Callable
+
+logger = logging.getLogger(__name__)
+
+
+class PipelineControlsPanel(ttk.Frame):
+    def get_settings(self) -> dict[str, Any]:
+        """
+        Return current toggles and loop/batch settings as a dictionary.
+        """
+        try:
+            loop_count = int(self.loop_count_var.get())
+        except ValueError:
+            loop_count = 1
+
+        try:
+            images_per_prompt = int(self.images_per_prompt_var.get())
+        except ValueError:
+            images_per_prompt = 1
+
+        return {
+            "txt2img_enabled": bool(self.txt2img_enabled.get()),
+            "img2img_enabled": bool(self.img2img_enabled.get()),
+            "adetailer_enabled": bool(self.adetailer_enabled.get()),
+            "upscale_enabled": bool(self.upscale_enabled.get()),
+            "video_enabled": bool(self.video_enabled.get()),
+            # Global negative per-stage toggles
+            "apply_global_negative_txt2img": bool(self.global_neg_txt2img.get()),
+            "apply_global_negative_img2img": bool(self.global_neg_img2img.get()),
+            "apply_global_negative_upscale": bool(self.global_neg_upscale.get()),
+            "apply_global_negative_adetailer": bool(self.global_neg_adetailer.get()),
+            "loop_type": self.loop_type_var.get(),
+            "loop_count": loop_count,
+            "pack_mode": self.pack_mode_var.get(),
+            "images_per_prompt": images_per_prompt,
+            "model_matrix": self._parse_model_matrix(self.model_matrix_var.get()),
+            "hypernetworks": self._parse_hypernetworks(self.hypernetworks_var.get()),
+            "variant_mode": str(self.variant_mode_var.get()).strip().lower() or "fanout",
+        }
+
+    def get_state(self) -> dict:
+        """
+        Return the current state of the panel as a dictionary.
+        Includes stage toggles, loop config, and batch config.
+        """
+        return {
+            "txt2img_enabled": bool(self.txt2img_enabled.get()),
+            "img2img_enabled": bool(self.img2img_enabled.get()),
+            "adetailer_enabled": bool(self.adetailer_enabled.get()),
+            "upscale_enabled": bool(self.upscale_enabled.get()),
+            "video_enabled": bool(self.video_enabled.get()),
+            "apply_global_negative_txt2img": bool(self.global_neg_txt2img.get()),
+            "apply_global_negative_img2img": bool(self.global_neg_img2img.get()),
+            "apply_global_negative_upscale": bool(self.global_neg_upscale.get()),
+            "apply_global_negative_adetailer": bool(self.global_neg_adetailer.get()),
+            "loop_type": self.loop_type_var.get(),
+            "loop_count": int(self.loop_count_var.get()),
+            "pack_mode": self.pack_mode_var.get(),
+            "images_per_prompt": int(self.images_per_prompt_var.get()),
+            "model_matrix": self._parse_model_matrix(self.model_matrix_var.get()),
+            "hypernetworks": self._parse_hypernetworks(self.hypernetworks_var.get()),
+            "variant_mode": str(self.variant_mode_var.get()),
+        }
+
+    def set_state(self, state: dict) -> None:
+        """
+        Restore the panel state from a dictionary.
+        Ignores missing keys and type errors.
+        """
+        self._suspend_callbacks = True
+        try:
+            try:
+                if "txt2img_enabled" in state:
+                    self.txt2img_enabled.set(bool(state["txt2img_enabled"]))
+                if "img2img_enabled" in state:
+                    self.img2img_enabled.set(bool(state["img2img_enabled"]))
+                if "adetailer_enabled" in state:
+                    self.adetailer_enabled.set(bool(state["adetailer_enabled"]))
+                if "upscale_enabled" in state:
+                    self.upscale_enabled.set(bool(state["upscale_enabled"]))
+                if "video_enabled" in state:
+                    self.video_enabled.set(bool(state["video_enabled"]))
+                if "apply_global_negative_txt2img" in state:
+                    self.global_neg_txt2img.set(bool(state["apply_global_negative_txt2img"]))
+                if "apply_global_negative_img2img" in state:
+                    self.global_neg_img2img.set(bool(state["apply_global_negative_img2img"]))
+                if "apply_global_negative_upscale" in state:
+                    self.global_neg_upscale.set(bool(state["apply_global_negative_upscale"]))
+                if "apply_global_negative_adetailer" in state:
+                    self.global_neg_adetailer.set(bool(state["apply_global_negative_adetailer"]))
+                if "loop_type" in state:
+                    self.loop_type_var.set(str(state["loop_type"]))
+                if "loop_count" in state:
+                    self.loop_count_var.set(str(state["loop_count"]))
+                if "pack_mode" in state:
+                    self.pack_mode_var.set(str(state["pack_mode"]))
+                if "images_per_prompt" in state:
+                    self.images_per_prompt_var.set(str(state["images_per_prompt"]))
+                if "model_matrix" in state:
+                    self._set_model_matrix_display(state["model_matrix"])
+                if "hypernetworks" in state:
+                    self._set_hypernetwork_display(state["hypernetworks"])
+                if "variant_mode" in state:
+                    self.variant_mode_var.set(str(state["variant_mode"]))
+            except Exception as e:
+                logger.warning(f"PipelineControlsPanel: Failed to restore state: {e}")
+        finally:
+            self._suspend_callbacks = False
+
+    def refresh_dynamic_lists_from_api(self, client) -> None:
+        """Update cached sampler/upscaler lists from the API client."""
+
+        if client is None:
+            return
+
+        try:
+            sampler_entries = getattr(client, "samplers", []) or []
+            sampler_names = [entry.get("name", "") for entry in sampler_entries if entry.get("name")]
+            self.set_sampler_options(sampler_names)
+        except Exception:
+            logger.exception("PipelineControlsPanel: Failed to refresh sampler options from API")
+
+        try:
+            upscaler_entries = getattr(client, "upscalers", []) or []
+            upscaler_names = [entry.get("name", "") for entry in upscaler_entries if entry.get("name")]
+            self.set_upscaler_options(upscaler_names)
+        except Exception:
+            logger.exception("PipelineControlsPanel: Failed to refresh upscaler options from API")
+
+    def set_sampler_options(self, sampler_names: list[str]) -> None:
+        """Cache sampler names for future pipeline controls."""
+
+        cleaned: list[str] = []
+        for name in sampler_names or []:
+            if not name:
+                continue
+            text = str(name).strip()
+            if text and text not in cleaned:
+                cleaned.append(text)
+        cleaned.sort(key=str.lower)
+        self._sampler_options = cleaned
+
+    def set_upscaler_options(self, upscaler_names: list[str]) -> None:
+        """Cache upscaler names for future pipeline controls."""
+
+        cleaned: list[str] = []
+        for name in upscaler_names or []:
+            if not name:
+                continue
+            text = str(name).strip()
+            if text and text not in cleaned:
+                cleaned.append(text)
+        cleaned.sort(key=str.lower)
+        self._upscaler_options = cleaned
+
+    """
+    A UI panel for pipeline execution controls.
+
+    This panel handles:
+    - Loop configuration (single/stages/pipeline)
+    - Loop count settings
+    - Batch configuration (pack mode selection)
+    - Images per prompt setting
+
+    It exposes a get_settings() method to retrieve current configuration.
+    """
+
+    def __init__(
+        self,
+        parent: tk.Widget,
+        initial_state: dict[str, Any] | None = None,
+        stage_vars: dict[str, tk.BooleanVar] | None = None,
+        show_variant_controls: bool = False,
+        on_change: Callable[[], None] | None = None,
+        **kwargs,
+    ):
+        """
+        Initialize the PipelineControlsPanel.
+
+        Args:
+            parent: Parent widget
+            initial_state: Optional dictionary used to pre-populate control values
+            stage_vars: Optional mapping of existing stage BooleanVars
+            **kwargs: Additional frame options
+        """
+        super().__init__(parent, **kwargs)
+        self.parent = parent
+        self._initial_state = initial_state or {}
+        self._stage_vars = stage_vars or {}
+        self._show_variant_controls = show_variant_controls
+        self._on_change = on_change
+        self._suspend_callbacks = False
+        self._trace_handles: list[tuple[tk.Variable, str]] = []
+        self._sampler_options: list[str] = []
+        self._upscaler_options: list[str] = []
+
+        # Initialize control variables
+        self._init_variables()
+
+        # Build UI
+        self._build_ui()
+        self._bind_change_listeners()
+
+    def _init_variables(self):
+        """Initialize all control variables with defaults."""
+        state = self._initial_state
+
+        # Stage toggles
+        self.txt2img_enabled = self._stage_vars.get("txt2img") or tk.BooleanVar(
+            value=bool(state.get("txt2img_enabled", True))
+        )
+        self.img2img_enabled = self._stage_vars.get("img2img") or tk.BooleanVar(
+            value=bool(state.get("img2img_enabled", True))
+        )
+        self.adetailer_enabled = self._stage_vars.get("adetailer") or tk.BooleanVar(
+            value=bool(state.get("adetailer_enabled", False))
+        )
+        self.upscale_enabled = self._stage_vars.get("upscale") or tk.BooleanVar(
+            value=bool(state.get("upscale_enabled", True))
+        )
+        self.video_enabled = self._stage_vars.get("video") or tk.BooleanVar(
+            value=bool(state.get("video_enabled", False))
+        )
+        # Global negative per-stage toggles (default True for backward compatibility)
+        self.global_neg_txt2img = tk.BooleanVar(
+            value=bool(state.get("apply_global_negative_txt2img", True))
+        )
+        self.global_neg_img2img = tk.BooleanVar(
+            value=bool(state.get("apply_global_negative_img2img", True))
+        )
+        self.global_neg_upscale = tk.BooleanVar(
+            value=bool(state.get("apply_global_negative_upscale", True))
+        )
+        self.global_neg_adetailer = tk.BooleanVar(
+            value=bool(state.get("apply_global_negative_adetailer", True))
+        )
+
+        # Loop configuration
+        self.loop_type_var = tk.StringVar(value=str(state.get("loop_type", "single")))
+        self.loop_count_var = tk.StringVar(value=str(state.get("loop_count", 1)))
+
+        # Batch configuration
+        self.pack_mode_var = tk.StringVar(value=str(state.get("pack_mode", "selected")))
+        self.images_per_prompt_var = tk.StringVar(value=str(state.get("images_per_prompt", 1)))
+        matrix_state = state.get("model_matrix", [])
+        if isinstance(matrix_state, list):
+            matrix_display = ", ".join(matrix_state)
+        else:
+            matrix_display = str(matrix_state)
+        self.model_matrix_var = tk.StringVar(value=matrix_display)
+
+        hyper_state = state.get("hypernetworks", [])
+        if isinstance(hyper_state, list):
+            hyper_display = ", ".join(
+                f"{item.get('name')}:{item.get('strength', 1.0)}" for item in hyper_state if item
+            )
+        else:
+            hyper_display = str(hyper_state)
+        self.hypernetworks_var = tk.StringVar(value=hyper_display)
+        self.variant_mode_var = tk.StringVar(value=str(state.get("variant_mode", "fanout")))
+
+    def _build_ui(self):
+        """Build the panel UI."""
+        # Pipeline controls frame
+        pipeline_frame = ttk.LabelFrame(
+            self, text="🚀 Pipeline Controls", style="Dark.TLabelframe", padding=5
+        )
+        pipeline_frame.pack(fill=tk.BOTH, expand=True)
+
+        # Loop configuration - compact
+        self._build_loop_config(pipeline_frame)
+
+        # Batch configuration - compact
+        self._build_batch_config(pipeline_frame)
+        if self._show_variant_controls:
+            self._build_variant_config(pipeline_frame)
+        self._build_global_negative_toggles(pipeline_frame)
+
+    def _bind_change_listeners(self) -> None:
+        """Attach variable traces to notify the host of user-driven changes."""
+        if not self._on_change:
+            return
+
+        vars_to_watch: list[tk.Variable] = [
+            self.loop_type_var,
+            self.loop_count_var,
+            self.pack_mode_var,
+            self.images_per_prompt_var,
+            self.model_matrix_var,
+            self.hypernetworks_var,
+            self.variant_mode_var,
+            self.txt2img_enabled,
+            self.img2img_enabled,
+            self.adetailer_enabled,
+            self.upscale_enabled,
+            self.video_enabled,
+            self.global_neg_txt2img,
+            self.global_neg_img2img,
+            self.global_neg_upscale,
+            self.global_neg_adetailer,
+        ]
+
+        callback = lambda *_: self._notify_change()
+        for var in vars_to_watch:
+            try:
+                handle = var.trace_add("write", callback)
+                self._trace_handles.append((var, handle))
+            except Exception:
+                continue
+
+    def _notify_change(self) -> None:
+        if self._suspend_callbacks or not self._on_change:
+            return
+        try:
+            self._on_change()
+        except Exception:
+            logger.debug("PipelineControlsPanel: change callback failed", exc_info=True)
+
+    def _build_loop_config(self, parent):
+        """Build loop configuration controls with logging."""
+        loop_frame = ttk.LabelFrame(parent, text="Loop Config", style="Dark.TLabelframe", padding=5)
+        loop_frame.pack(fill=tk.X, pady=(0, 5))
+
+        def log_loop_type():
+            logger.info(f"PipelineControlsPanel: loop_type set to {self.loop_type_var.get()}")
+
+        ttk.Radiobutton(
+            loop_frame,
+            text="Single",
+            variable=self.loop_type_var,
+            value="single",
+            style="Dark.TRadiobutton",
+            command=log_loop_type,
+        ).pack(anchor=tk.W, pady=1)
+
+        ttk.Radiobutton(
+            loop_frame,
+            text="Loop stages",
+            variable=self.loop_type_var,
+            value="stages",
+            style="Dark.TRadiobutton",
+            command=log_loop_type,
+        ).pack(anchor=tk.W, pady=1)
+
+        ttk.Radiobutton(
+            loop_frame,
+            text="Loop pipeline",
+            variable=self.loop_type_var,
+            value="pipeline",
+            style="Dark.TRadiobutton",
+            command=log_loop_type,
+        ).pack(anchor=tk.W, pady=1)
+
+        # Loop count - inline
+        count_frame = ttk.Frame(loop_frame, style="Dark.TFrame")
+        count_frame.pack(fill=tk.X, pady=2)
+
+        ttk.Label(count_frame, text="Count:", style="Dark.TLabel", width=6).pack(side=tk.LEFT)
+
+        def log_loop_count(*_):
+            logger.info(f"PipelineControlsPanel: loop_count set to {self.loop_count_var.get()}")
+
+        self.loop_count_var.trace_add("write", log_loop_count)
+        count_spin = ttk.Spinbox(
+            count_frame,
+            from_=1,
+            to=100,
+            width=4,
+            textvariable=self.loop_count_var,
+            style="Dark.TSpinbox",
+        )
+        count_spin.pack(side=tk.LEFT, padx=2)
+
+    def _build_batch_config(self, parent):
+        """Build batch configuration controls with logging."""
+        batch_frame = ttk.LabelFrame(
+            parent, text="Batch Config", style="Dark.TLabelframe", padding=5
+        )
+        batch_frame.pack(fill=tk.X, pady=(0, 5))
+
+        def log_pack_mode():
+            logger.info(f"PipelineControlsPanel: pack_mode set to {self.pack_mode_var.get()}")
+
+        ttk.Radiobutton(
+            batch_frame,
+            text="Selected packs",
+            variable=self.pack_mode_var,
+            value="selected",
+            style="Dark.TRadiobutton",
+            command=log_pack_mode,
+        ).pack(anchor=tk.W, pady=1)
+
+        ttk.Radiobutton(
+            batch_frame,
+            text="All packs",
+            variable=self.pack_mode_var,
+            value="all",
+            style="Dark.TRadiobutton",
+            command=log_pack_mode,
+        ).pack(anchor=tk.W, pady=1)
+
+        ttk.Radiobutton(
+            batch_frame,
+            text="Custom list",
+            variable=self.pack_mode_var,
+            value="custom",
+            style="Dark.TRadiobutton",
+            command=log_pack_mode,
+        ).pack(anchor=tk.W, pady=1)
+
+        # Images per prompt - inline
+        images_frame = ttk.Frame(batch_frame, style="Dark.TFrame")
+        images_frame.pack(fill=tk.X, pady=2)
+
+        ttk.Label(images_frame, text="Images:", style="Dark.TLabel", width=6).pack(side=tk.LEFT)
+
+        def log_images_per_prompt(*_):
+            logger.info(
+                f"PipelineControlsPanel: images_per_prompt set to {self.images_per_prompt_var.get()}"
+            )
+
+        self.images_per_prompt_var.trace_add("write", log_images_per_prompt)
+        images_spin = ttk.Spinbox(
+            images_frame,
+            from_=1,
+            to=10,
+            width=4,
+            textvariable=self.images_per_prompt_var,
+            style="Dark.TSpinbox",
+        )
+        images_spin.pack(side=tk.LEFT, padx=2)
+
+    def _build_variant_config(self, parent):
+        """Build controls for model/hypernetwork combinations."""
+        variant_frame = ttk.LabelFrame(
+            parent, text="Model Matrix & Hypernets", style="Dark.TLabelframe", padding=5
+        )
+        variant_frame.pack(fill=tk.X, pady=(0, 5))
+
+        ttk.Label(
+            variant_frame,
+            text="Model checkpoints (comma/newline separated):",
+            style="Dark.TLabel",
+        ).pack(anchor=tk.W, pady=(0, 2))
+        ttk.Entry(variant_frame, textvariable=self.model_matrix_var, width=40).pack(
+            fill=tk.X, pady=(0, 4)
+        )
+
+        ttk.Label(
+            variant_frame,
+            text="Hypernetworks (name:strength, separated by commas):",
+            style="Dark.TLabel",
+        ).pack(anchor=tk.W, pady=(4, 2))
+        ttk.Entry(variant_frame, textvariable=self.hypernetworks_var, width=40).pack(fill=tk.X)
+
+        mode_frame = ttk.Frame(variant_frame, style="Dark.TFrame")
+        mode_frame.pack(fill=tk.X, pady=(6, 0))
+        ttk.Label(mode_frame, text="Variant strategy:", style="Dark.TLabel").pack(anchor=tk.W)
+        ttk.Radiobutton(
+            mode_frame,
+            text="Fan-out (run every combo)",
+            variable=self.variant_mode_var,
+            value="fanout",
+            style="Dark.TRadiobutton",
+        ).pack(anchor=tk.W, pady=(2, 0))
+        ttk.Radiobutton(
+            mode_frame,
+            text="Rotate per prompt",
+            variable=self.variant_mode_var,
+            value="rotate",
+            style="Dark.TRadiobutton",
+        ).pack(anchor=tk.W, pady=(2, 0))
+
+    def _build_global_negative_toggles(self, parent):
+        """Build per-stage Global Negative enable toggles."""
+        frame = ttk.LabelFrame(
+            parent, text="Global Negative (per stage)", style="Dark.TLabelframe", padding=5
+        )
+        frame.pack(fill=tk.X, pady=(0, 5))
+
+        def _mk(cb_text, var, key):
+            def _log():
+                logger.info(f"PipelineControlsPanel: {key} set to {var.get()}")
+
+            ttk.Checkbutton(
+                frame, text=cb_text, variable=var, style="Dark.TCheckbutton", command=_log
+            ).pack(anchor=tk.W)
+
+        _mk("Apply to txt2img", self.global_neg_txt2img, "apply_global_negative_txt2img")
+        _mk("Apply to img2img", self.global_neg_img2img, "apply_global_negative_img2img")
+        _mk("Apply to upscale", self.global_neg_upscale, "apply_global_negative_upscale")
+        _mk("Apply to ADetailer", self.global_neg_adetailer, "apply_global_negative_adetailer")
+
+    def set_settings(self, settings: dict[str, Any]):
+        """
+        Set pipeline control settings from a dictionary.
+
+        Args:
+            settings: Dictionary containing pipeline settings
+        """
+        if "txt2img_enabled" in settings:
+            self.txt2img_enabled.set(settings["txt2img_enabled"])
+        if "img2img_enabled" in settings:
+            self.img2img_enabled.set(settings["img2img_enabled"])
+        if "adetailer_enabled" in settings:
+            self.adetailer_enabled.set(settings["adetailer_enabled"])
+        if "upscale_enabled" in settings:
+            self.upscale_enabled.set(settings["upscale_enabled"])
+        if "video_enabled" in settings:
+            self.video_enabled.set(settings["video_enabled"])
+
+        if "loop_type" in settings:
+            self.loop_type_var.set(settings["loop_type"])
+        if "loop_count" in settings:
+            self.loop_count_var.set(str(settings["loop_count"]))
+
+        if "pack_mode" in settings:
+            self.pack_mode_var.set(settings["pack_mode"])
+        if "images_per_prompt" in settings:
+            self.images_per_prompt_var.set(str(settings["images_per_prompt"]))
+        if "model_matrix" in settings:
+            self._set_model_matrix_display(settings["model_matrix"])
+        if "hypernetworks" in settings:
+            self._set_hypernetwork_display(settings["hypernetworks"])
+        if "variant_mode" in settings:
+            self.variant_mode_var.set(str(settings["variant_mode"]))
+
+    def apply_config(self, cfg: dict[str, Any]) -> None:
+        """Apply a configuration payload (e.g., from packs/presets) to the controls."""
+        if not cfg:
+            return
+
+        target = cfg.get("pipeline") if isinstance(cfg.get("pipeline"), dict) else cfg
+        if not isinstance(target, dict):
+            return
+
+        self._suspend_callbacks = True
+        try:
+            self.set_settings(target)
+        finally:
+            self._suspend_callbacks = False
+
+    # ------------------------------------------------------------------
+    # Parsing helpers
+    # ------------------------------------------------------------------
+
+    def _parse_model_matrix(self, raw: str) -> list[str]:
+        if not raw:
+            return []
+        values: list[str] = []
+        for chunk in re.split(r"[\n,]+", raw):
+            sanitized = chunk.strip()
+            if sanitized:
+                values.append(sanitized)
+        return values
+
+    def _parse_hypernetworks(self, raw: str) -> list[dict[str, Any]]:
+        if not raw:
+            return []
+        entries: list[dict[str, Any]] = []
+        for chunk in re.split(r"[\n,]+", raw):
+            sanitized = chunk.strip()
+            if not sanitized:
+                continue
+            if ":" in sanitized:
+                name, strength = sanitized.split(":", 1)
+                try:
+                    weight = float(strength.strip())
+                except ValueError:
+                    weight = 1.0
+                entries.append({"name": name.strip(), "strength": weight})
+            else:
+                entries.append({"name": sanitized, "strength": 1.0})
+        return entries
+
+    def _set_model_matrix_display(self, value):
+        if isinstance(value, list):
+            self.model_matrix_var.set(", ".join(value))
+        else:
+            self.model_matrix_var.set(str(value))
+
+    def _set_hypernetwork_display(self, value):
+        if isinstance(value, list):
+            self.hypernetworks_var.set(
+                ", ".join(
+                    f"{item.get('name')}:{item.get('strength', 1.0)}"
+                    for item in value
+                    if item and item.get("name")
+                )
+            )
+        else:
+            self.hypernetworks_var.set(str(value))

```

---

## Patch: add `archive/gui_v1/img2img_stage_card.py` with archived implementation

```diff
--- /dev/null
+++ b/archive/gui_v1/img2img_stage_card.py
@@ -0,0 +1,129 @@
+# Archived legacy Img2Img stage card (Img2ImgStageCard)
+# No longer used by Phase-1 V2 GUI.
+# Retained only for reference during migration.
+
+"""img2img stage card for PipelinePanelV2."""
+
+from __future__ import annotations
+
+import tkinter as tk
+from tkinter import ttk
+
+from . import theme as theme_mod
+
+
+class Img2ImgStageCard(ttk.Frame):
+    """Stage card managing img2img fields."""
+
+    FIELD_NAMES = [
+        "model",
+        "vae",
+        "sampler_name",
+        "denoising_strength",
+        "cfg_scale",
+        "steps",
+    ]
+
+    def __init__(self, master: tk.Misc, *, controller=None, theme=None, **kwargs) -> None:
+        style_name = getattr(theme, "SURFACE_FRAME_STYLE", theme_mod.SURFACE_FRAME_STYLE)
+        super().__init__(master, style=style_name, padding=theme_mod.PADDING_MD, **kwargs)
+        self.controller = controller
+        self.theme = theme
+
+        header_style = getattr(theme, "STATUS_STRONG_LABEL_STYLE", theme_mod.STATUS_STRONG_LABEL_STYLE)
+        self.header_label = ttk.Label(self, text="img2img Settings", style=header_style)
+        self.header_label.pack(anchor=tk.W, pady=(0, 4))
+
+        body_style = getattr(theme, "SURFACE_FRAME_STYLE", theme_mod.SURFACE_FRAME_STYLE)
+        self.body = ttk.Frame(self, style=body_style)
+        self.body.pack(fill=tk.BOTH, expand=True)
+
+        self._vars: dict[str, tk.StringVar] = {}
+
+        for idx, field in enumerate(self.FIELD_NAMES):
+            var = tk.StringVar()
+            self._vars[field] = var
+            if field == "steps":
+                self._add_spinbox(self.body, field, var, idx, from_=1, to=200)
+            elif field in {"denoising_strength", "cfg_scale"}:
+                increment = 0.05 if field == "denoising_strength" else 0.5
+                to_value = 1.0 if field == "denoising_strength" else 30.0
+                self._add_spinbox(self.body, field, var, idx, from_=0.0, to=to_value, increment=increment)
+            else:
+                self._add_entry(self.body, field, var, idx)
+
+    def _add_entry(self, parent, label, variable, row):
+        ttk.Label(parent, text=label.replace("_", " ").title(), style="Dark.TLabel").grid(
+            row=row, column=0, sticky=tk.W, pady=2
+        )
+        entry = ttk.Entry(parent, textvariable=variable, width=28)
+        entry.grid(row=row, column=1, sticky="ew", pady=2)
+        parent.columnconfigure(1, weight=1)
+        return entry
+
+    def _add_spinbox(self, parent, label, variable, row, *, from_, to, increment=1.0):
+        ttk.Label(parent, text=label.replace("_", " ").title(), style="Dark.TLabel").grid(
+            row=row, column=0, sticky=tk.W, pady=2
+        )
+        spin = ttk.Spinbox(
+            parent,
+            textvariable=variable,
+            from_=from_,
+            to=to,
+            increment=increment,
+            width=10,
+        )
+        spin.grid(row=row, column=1, sticky="ew", pady=2)
+        return spin
+
+    def load_from_config(self, config: dict | None) -> None:
+        section = self._get_section(config)
+        for field in self.FIELD_NAMES:
+            self._vars[field].set(self._coerce_str(section.get(field)))
+
+    def to_config_dict(self) -> dict:
+        section: dict[str, object] = {}
+        for field in self.FIELD_NAMES:
+            value = self._vars[field].get()
+            if field == "steps":
+                converted = self._coerce_int(value)
+            elif field in {"denoising_strength", "cfg_scale"}:
+                converted = self._coerce_float(value)
+            else:
+                converted = value.strip() if isinstance(value, str) else ""
+                if not converted:
+                    converted = None
+            if converted not in (None, ""):
+                section[field] = converted
+        return {"img2img": section} if section else {}
+
+    @staticmethod
+    def _get_section(config: dict | None) -> dict:
+        if isinstance(config, dict):
+            section = config.get("img2img") or {}
+            return section if isinstance(section, dict) else {}
+        return {}
+
+    @staticmethod
+    def _coerce_str(value: object) -> str:
+        if value is None:
+            return ""
+        return str(value)
+
+    @staticmethod
+    def _coerce_int(value: object) -> int | None:
+        try:
+            if value is None or str(value).strip() == "":
+                return None
+            return int(float(value))
+        except (ValueError, TypeError):
+            return None
+
+    @staticmethod
+    def _coerce_float(value: object) -> float | None:
+        try:
+            if value is None or str(value).strip() == "":
+                return None
+            return float(value)
+        except (ValueError, TypeError):
+            return None

```

---

## Validation

After applying this PR (ideally **after** PR-GUI-V2-SHIM-AND-ARCHIVE-005_V2-P1):

1. There should be **no active imports** of:
   - `src.gui.config_panel.ConfigPanel`
   - `src.gui.pipeline_controls_panel.PipelineControlsPanel`
   - `src.gui.img2img_stage_card.Img2ImgStageCard`
   from any V2 modules or tests.

2. Legacy implementations remain available in the archive:
   - `archive/gui_v1/config_panel.py`
   - `archive/gui_v1/pipeline_controls_panel.py`
   - `archive/gui_v1/img2img_stage_card.py`

3. Core GUI V2 tests should still pass:

   ```bash
   pytest tests/gui_v2/test_gui_v2_layout_skeleton.py -q
   pytest tests/gui_v2/test_entrypoint_uses_v2_gui.py -q
   pytest tests/gui_v2 -q
   ```

4. Running `python -m src.main` still launches the V2 GUI (which now depends only on the `*_v2` components and the canonical `MainWindowV2`).

This completes the migration of these three legacy modules out of the active V2 code path.
