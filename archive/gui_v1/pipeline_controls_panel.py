"""
Pipeline Controls Panel - UI component for configuring pipeline execution.
"""

import logging
import re
import tkinter as tk
from tkinter import ttk
from typing import Any, Callable

logger = logging.getLogger(__name__)


class PipelineControlsPanel(ttk.Frame):
    def get_settings(self) -> dict[str, Any]:
        """
        Return current toggles and loop/batch settings as a dictionary.
        """
        try:
            loop_count = int(self.loop_count_var.get())
        except ValueError:
            loop_count = 1

        try:
            images_per_prompt = int(self.images_per_prompt_var.get())
        except ValueError:
            images_per_prompt = 1

        return {
            "txt2img_enabled": bool(self.txt2img_enabled.get()),
            "img2img_enabled": bool(self.img2img_enabled.get()),
            "adetailer_enabled": bool(self.adetailer_enabled.get()),
            "upscale_enabled": bool(self.upscale_enabled.get()),
            "video_enabled": bool(self.video_enabled.get()),
            # Global negative per-stage toggles
            "apply_global_negative_txt2img": bool(self.global_neg_txt2img.get()),
            "apply_global_negative_img2img": bool(self.global_neg_img2img.get()),
            "apply_global_negative_upscale": bool(self.global_neg_upscale.get()),
            "apply_global_negative_adetailer": bool(self.global_neg_adetailer.get()),
            "loop_type": self.loop_type_var.get(),
            "loop_count": loop_count,
            "pack_mode": self.pack_mode_var.get(),
            "images_per_prompt": images_per_prompt,
            "model_matrix": self._parse_model_matrix(self.model_matrix_var.get()),
            "hypernetworks": self._parse_hypernetworks(self.hypernetworks_var.get()),
            "variant_mode": str(self.variant_mode_var.get()).strip().lower() or "fanout",
        }

    def get_state(self) -> dict:
        """
        Return the current state of the panel as a dictionary.
        Includes stage toggles, loop config, and batch config.
        """
        return {
            "txt2img_enabled": bool(self.txt2img_enabled.get()),
            "img2img_enabled": bool(self.img2img_enabled.get()),
            "adetailer_enabled": bool(self.adetailer_enabled.get()),
            "upscale_enabled": bool(self.upscale_enabled.get()),
            "video_enabled": bool(self.video_enabled.get()),
            "apply_global_negative_txt2img": bool(self.global_neg_txt2img.get()),
            "apply_global_negative_img2img": bool(self.global_neg_img2img.get()),
            "apply_global_negative_upscale": bool(self.global_neg_upscale.get()),
            "apply_global_negative_adetailer": bool(self.global_neg_adetailer.get()),
            "loop_type": self.loop_type_var.get(),
            "loop_count": int(self.loop_count_var.get()),
            "pack_mode": self.pack_mode_var.get(),
            "images_per_prompt": int(self.images_per_prompt_var.get()),
            "model_matrix": self._parse_model_matrix(self.model_matrix_var.get()),
            "hypernetworks": self._parse_hypernetworks(self.hypernetworks_var.get()),
            "variant_mode": str(self.variant_mode_var.get()),
        }

    def set_state(self, state: dict) -> None:
        """
        Restore the panel state from a dictionary.
        Ignores missing keys and type errors.
        """
        self._suspend_callbacks = True
        try:
            try:
                if "txt2img_enabled" in state:
                    self.txt2img_enabled.set(bool(state["txt2img_enabled"]))
                if "img2img_enabled" in state:
                    self.img2img_enabled.set(bool(state["img2img_enabled"]))
                if "adetailer_enabled" in state:
                    self.adetailer_enabled.set(bool(state["adetailer_enabled"]))
                if "upscale_enabled" in state:
                    self.upscale_enabled.set(bool(state["upscale_enabled"]))
                if "video_enabled" in state:
                    self.video_enabled.set(bool(state["video_enabled"]))
                if "apply_global_negative_txt2img" in state:
                    self.global_neg_txt2img.set(bool(state["apply_global_negative_txt2img"]))
                if "apply_global_negative_img2img" in state:
                    self.global_neg_img2img.set(bool(state["apply_global_negative_img2img"]))
                if "apply_global_negative_upscale" in state:
                    self.global_neg_upscale.set(bool(state["apply_global_negative_upscale"]))
                if "apply_global_negative_adetailer" in state:
                    self.global_neg_adetailer.set(bool(state["apply_global_negative_adetailer"]))
                if "loop_type" in state:
                    self.loop_type_var.set(str(state["loop_type"]))
                if "loop_count" in state:
                    self.loop_count_var.set(str(state["loop_count"]))
                if "pack_mode" in state:
                    self.pack_mode_var.set(str(state["pack_mode"]))
                if "images_per_prompt" in state:
                    self.images_per_prompt_var.set(str(state["images_per_prompt"]))
                if "model_matrix" in state:
                    self._set_model_matrix_display(state["model_matrix"])
                if "hypernetworks" in state:
                    self._set_hypernetwork_display(state["hypernetworks"])
                if "variant_mode" in state:
                    self.variant_mode_var.set(str(state["variant_mode"]))
            except Exception as e:
                logger.warning(f"PipelineControlsPanel: Failed to restore state: {e}")
        finally:
            self._suspend_callbacks = False

    def refresh_dynamic_lists_from_api(self, client) -> None:
        """Update cached sampler/upscaler lists from the API client."""

        if client is None:
            return

        try:
            sampler_entries = getattr(client, "samplers", []) or []
            sampler_names = [entry.get("name", "") for entry in sampler_entries if entry.get("name")]
            self.set_sampler_options(sampler_names)
        except Exception:
            logger.exception("PipelineControlsPanel: Failed to refresh sampler options from API")

        try:
            upscaler_entries = getattr(client, "upscalers", []) or []
            upscaler_names = [entry.get("name", "") for entry in upscaler_entries if entry.get("name")]
            self.set_upscaler_options(upscaler_names)
        except Exception:
            logger.exception("PipelineControlsPanel: Failed to refresh upscaler options from API")

    def set_sampler_options(self, sampler_names: list[str]) -> None:
        """Cache sampler names for future pipeline controls."""

        cleaned: list[str] = []
        for name in sampler_names or []:
            if not name:
                continue
            text = str(name).strip()
            if text and text not in cleaned:
                cleaned.append(text)
        cleaned.sort(key=str.lower)
        self._sampler_options = cleaned

    def set_upscaler_options(self, upscaler_names: list[str]) -> None:
        """Cache upscaler names for future pipeline controls."""

        cleaned: list[str] = []
        for name in upscaler_names or []:
            if not name:
                continue
            text = str(name).strip()
            if text and text not in cleaned:
                cleaned.append(text)
        cleaned.sort(key=str.lower)
        self._upscaler_options = cleaned

    """
    A UI panel for pipeline execution controls.

    This panel handles:
    - Loop configuration (single/stages/pipeline)
    - Loop count settings
    - Batch configuration (pack mode selection)
    - Images per prompt setting

    It exposes a get_settings() method to retrieve current configuration.
    """

    def __init__(
        self,
        parent: tk.Widget,
        initial_state: dict[str, Any] | None = None,
        stage_vars: dict[str, tk.BooleanVar] | None = None,
        show_variant_controls: bool = False,
        on_change: Callable[[], None] | None = None,
        **kwargs,
    ):
        """
        Initialize the PipelineControlsPanel.

        Args:
            parent: Parent widget
            initial_state: Optional dictionary used to pre-populate control values
            stage_vars: Optional mapping of existing stage BooleanVars
            **kwargs: Additional frame options
        """
        super().__init__(parent, **kwargs)
        self.parent = parent
        self._initial_state = initial_state or {}
        self._stage_vars = stage_vars or {}
        self._show_variant_controls = show_variant_controls
        self._on_change = on_change
        self._suspend_callbacks = False
        self._trace_handles: list[tuple[tk.Variable, str]] = []
        self._sampler_options: list[str] = []
        self._upscaler_options: list[str] = []

        # Initialize control variables
        self._init_variables()

        # Build UI
        self._build_ui()
        self._bind_change_listeners()

    def _init_variables(self):
        """Initialize all control variables with defaults."""
        state = self._initial_state

        # Stage toggles
        self.txt2img_enabled = self._stage_vars.get("txt2img") or tk.BooleanVar(
            value=bool(state.get("txt2img_enabled", True))
        )
        self.img2img_enabled = self._stage_vars.get("img2img") or tk.BooleanVar(
            value=bool(state.get("img2img_enabled", True))
        )
        self.adetailer_enabled = self._stage_vars.get("adetailer") or tk.BooleanVar(
            value=bool(state.get("adetailer_enabled", False))
        )
        self.upscale_enabled = self._stage_vars.get("upscale") or tk.BooleanVar(
            value=bool(state.get("upscale_enabled", True))
        )
        self.video_enabled = self._stage_vars.get("video") or tk.BooleanVar(
            value=bool(state.get("video_enabled", False))
        )
        # Global negative per-stage toggles (default True for backward compatibility)
        self.global_neg_txt2img = tk.BooleanVar(
            value=bool(state.get("apply_global_negative_txt2img", True))
        )
        self.global_neg_img2img = tk.BooleanVar(
            value=bool(state.get("apply_global_negative_img2img", True))
        )
        self.global_neg_upscale = tk.BooleanVar(
            value=bool(state.get("apply_global_negative_upscale", True))
        )
        self.global_neg_adetailer = tk.BooleanVar(
            value=bool(state.get("apply_global_negative_adetailer", True))
        )

        # Loop configuration
        self.loop_type_var = tk.StringVar(value=str(state.get("loop_type", "single")))
        self.loop_count_var = tk.StringVar(value=str(state.get("loop_count", 1)))

        # Batch configuration
        self.pack_mode_var = tk.StringVar(value=str(state.get("pack_mode", "selected")))
        self.images_per_prompt_var = tk.StringVar(value=str(state.get("images_per_prompt", 1)))
        matrix_state = state.get("model_matrix", [])
        if isinstance(matrix_state, list):
            matrix_display = ", ".join(matrix_state)
        else:
            matrix_display = str(matrix_state)
        self.model_matrix_var = tk.StringVar(value=matrix_display)

        hyper_state = state.get("hypernetworks", [])
        if isinstance(hyper_state, list):
            hyper_display = ", ".join(
                f"{item.get('name')}:{item.get('strength', 1.0)}" for item in hyper_state if item
            )
        else:
            hyper_display = str(hyper_state)
        self.hypernetworks_var = tk.StringVar(value=hyper_display)
        self.variant_mode_var = tk.StringVar(value=str(state.get("variant_mode", "fanout")))

    def _build_ui(self):
        """Build the panel UI."""
        # Pipeline controls frame
        pipeline_frame = ttk.LabelFrame(
            self, text="🚀 Pipeline Controls", style="Dark.TLabelframe", padding=5
        )
        pipeline_frame.pack(fill=tk.BOTH, expand=True)

        # Loop configuration - compact
        self._build_loop_config(pipeline_frame)

        # Batch configuration - compact
        self._build_batch_config(pipeline_frame)
        if self._show_variant_controls:
            self._build_variant_config(pipeline_frame)
        self._build_global_negative_toggles(pipeline_frame)

    def _bind_change_listeners(self) -> None:
        """Attach variable traces to notify the host of user-driven changes."""
        if not self._on_change:
            return

        vars_to_watch: list[tk.Variable] = [
            self.loop_type_var,
            self.loop_count_var,
            self.pack_mode_var,
            self.images_per_prompt_var,
            self.model_matrix_var,
            self.hypernetworks_var,
            self.variant_mode_var,
            self.txt2img_enabled,
            self.img2img_enabled,
            self.adetailer_enabled,
            self.upscale_enabled,
            self.video_enabled,
            self.global_neg_txt2img,
            self.global_neg_img2img,
            self.global_neg_upscale,
            self.global_neg_adetailer,
        ]

        callback = lambda *_: self._notify_change()
        for var in vars_to_watch:
            try:
                handle = var.trace_add("write", callback)
                self._trace_handles.append((var, handle))
            except Exception:
                continue

    def _notify_change(self) -> None:
        if self._suspend_callbacks or not self._on_change:
            return
        try:
            self._on_change()
        except Exception:
            logger.debug("PipelineControlsPanel: change callback failed", exc_info=True)

    def _build_loop_config(self, parent):
        """Build loop configuration controls with logging."""
        loop_frame = ttk.LabelFrame(parent, text="Loop Config", style="Dark.TLabelframe", padding=5)
        loop_frame.pack(fill=tk.X, pady=(0, 5))

        def log_loop_type():
            logger.info(f"PipelineControlsPanel: loop_type set to {self.loop_type_var.get()}")

        ttk.Radiobutton(
            loop_frame,
            text="Single",
            variable=self.loop_type_var,
            value="single",
            style="Dark.TRadiobutton",
            command=log_loop_type,
        ).pack(anchor=tk.W, pady=1)

        ttk.Radiobutton(
            loop_frame,
            text="Loop stages",
            variable=self.loop_type_var,
            value="stages",
            style="Dark.TRadiobutton",
            command=log_loop_type,
        ).pack(anchor=tk.W, pady=1)

        ttk.Radiobutton(
            loop_frame,
            text="Loop pipeline",
            variable=self.loop_type_var,
            value="pipeline",
            style="Dark.TRadiobutton",
            command=log_loop_type,
        ).pack(anchor=tk.W, pady=1)

        # Loop count - inline
        count_frame = ttk.Frame(loop_frame, style="Dark.TFrame")
        count_frame.pack(fill=tk.X, pady=2)

        ttk.Label(count_frame, text="Count:", style="Dark.TLabel", width=6).pack(side=tk.LEFT)

        def log_loop_count(*_):
            logger.info(f"PipelineControlsPanel: loop_count set to {self.loop_count_var.get()}")

        self.loop_count_var.trace_add("write", log_loop_count)
        count_spin = ttk.Spinbox(
            count_frame,
            from_=1,
            to=100,
            width=4,
            textvariable=self.loop_count_var,
            style="Dark.TSpinbox",
        )
        count_spin.pack(side=tk.LEFT, padx=2)

    def _build_batch_config(self, parent):
        """Build batch configuration controls with logging."""
        batch_frame = ttk.LabelFrame(
            parent, text="Batch Config", style="Dark.TLabelframe", padding=5
        )
        batch_frame.pack(fill=tk.X, pady=(0, 5))

        def log_pack_mode():
            logger.info(f"PipelineControlsPanel: pack_mode set to {self.pack_mode_var.get()}")

        ttk.Radiobutton(
            batch_frame,
            text="Selected packs",
            variable=self.pack_mode_var,
            value="selected",
            style="Dark.TRadiobutton",
            command=log_pack_mode,
        ).pack(anchor=tk.W, pady=1)

        ttk.Radiobutton(
            batch_frame,
            text="All packs",
            variable=self.pack_mode_var,
            value="all",
            style="Dark.TRadiobutton",
            command=log_pack_mode,
        ).pack(anchor=tk.W, pady=1)

        ttk.Radiobutton(
            batch_frame,
            text="Custom list",
            variable=self.pack_mode_var,
            value="custom",
            style="Dark.TRadiobutton",
            command=log_pack_mode,
        ).pack(anchor=tk.W, pady=1)

        # Images per prompt - inline
        images_frame = ttk.Frame(batch_frame, style="Dark.TFrame")
        images_frame.pack(fill=tk.X, pady=2)

        ttk.Label(images_frame, text="Images:", style="Dark.TLabel", width=6).pack(side=tk.LEFT)

        def log_images_per_prompt(*_):
            logger.info(
                f"PipelineControlsPanel: images_per_prompt set to {self.images_per_prompt_var.get()}"
            )

        self.images_per_prompt_var.trace_add("write", log_images_per_prompt)
        images_spin = ttk.Spinbox(
            images_frame,
            from_=1,
            to=10,
            width=4,
            textvariable=self.images_per_prompt_var,
            style="Dark.TSpinbox",
        )
        images_spin.pack(side=tk.LEFT, padx=2)

    def _build_variant_config(self, parent):
        """Build controls for model/hypernetwork combinations."""
        variant_frame = ttk.LabelFrame(
            parent, text="Model Matrix & Hypernets", style="Dark.TLabelframe", padding=5
        )
        variant_frame.pack(fill=tk.X, pady=(0, 5))

        ttk.Label(
            variant_frame,
            text="Model checkpoints (comma/newline separated):",
            style="Dark.TLabel",
        ).pack(anchor=tk.W, pady=(0, 2))
        ttk.Entry(variant_frame, textvariable=self.model_matrix_var, width=40).pack(
            fill=tk.X, pady=(0, 4)
        )

        ttk.Label(
            variant_frame,
            text="Hypernetworks (name:strength, separated by commas):",
            style="Dark.TLabel",
        ).pack(anchor=tk.W, pady=(4, 2))
        ttk.Entry(variant_frame, textvariable=self.hypernetworks_var, width=40).pack(fill=tk.X)

        mode_frame = ttk.Frame(variant_frame, style="Dark.TFrame")
        mode_frame.pack(fill=tk.X, pady=(6, 0))
        ttk.Label(mode_frame, text="Variant strategy:", style="Dark.TLabel").pack(anchor=tk.W)
        ttk.Radiobutton(
            mode_frame,
            text="Fan-out (run every combo)",
            variable=self.variant_mode_var,
            value="fanout",
            style="Dark.TRadiobutton",
        ).pack(anchor=tk.W, pady=(2, 0))
        ttk.Radiobutton(
            mode_frame,
            text="Rotate per prompt",
            variable=self.variant_mode_var,
            value="rotate",
            style="Dark.TRadiobutton",
        ).pack(anchor=tk.W, pady=(2, 0))

    def _build_global_negative_toggles(self, parent):
        """Build per-stage Global Negative enable toggles."""
        frame = ttk.LabelFrame(
            parent, text="Global Negative (per stage)", style="Dark.TLabelframe", padding=5
        )
        frame.pack(fill=tk.X, pady=(0, 5))

        def _mk(cb_text, var, key):
            def _log():
                logger.info(f"PipelineControlsPanel: {key} set to {var.get()}")

            ttk.Checkbutton(
                frame, text=cb_text, variable=var, style="Dark.TCheckbutton", command=_log
            ).pack(anchor=tk.W)

        _mk("Apply to txt2img", self.global_neg_txt2img, "apply_global_negative_txt2img")
        _mk("Apply to img2img", self.global_neg_img2img, "apply_global_negative_img2img")
        _mk("Apply to upscale", self.global_neg_upscale, "apply_global_negative_upscale")
        _mk("Apply to ADetailer", self.global_neg_adetailer, "apply_global_negative_adetailer")

    def set_settings(self, settings: dict[str, Any]):
        """
        Set pipeline control settings from a dictionary.

        Args:
            settings: Dictionary containing pipeline settings
        """
        if "txt2img_enabled" in settings:
            self.txt2img_enabled.set(settings["txt2img_enabled"])
        if "img2img_enabled" in settings:
            self.img2img_enabled.set(settings["img2img_enabled"])
        if "adetailer_enabled" in settings:
            self.adetailer_enabled.set(settings["adetailer_enabled"])
        if "upscale_enabled" in settings:
            self.upscale_enabled.set(settings["upscale_enabled"])
        if "video_enabled" in settings:
            self.video_enabled.set(settings["video_enabled"])

        if "loop_type" in settings:
            self.loop_type_var.set(settings["loop_type"])
        if "loop_count" in settings:
            self.loop_count_var.set(str(settings["loop_count"]))

        if "pack_mode" in settings:
            self.pack_mode_var.set(settings["pack_mode"])
        if "images_per_prompt" in settings:
            self.images_per_prompt_var.set(str(settings["images_per_prompt"]))
        if "model_matrix" in settings:
            self._set_model_matrix_display(settings["model_matrix"])
        if "hypernetworks" in settings:
            self._set_hypernetwork_display(settings["hypernetworks"])
        if "variant_mode" in settings:
            self.variant_mode_var.set(str(settings["variant_mode"]))

    def apply_config(self, cfg: dict[str, Any]) -> None:
        """Apply a configuration payload (e.g., from packs/presets) to the controls."""
        if not cfg:
            return

        target = cfg.get("pipeline") if isinstance(cfg.get("pipeline"), dict) else cfg
        if not isinstance(target, dict):
            return

        self._suspend_callbacks = True
        try:
            self.set_settings(target)
        finally:
            self._suspend_callbacks = False

    # ------------------------------------------------------------------
    # Parsing helpers
    # ------------------------------------------------------------------

    def _parse_model_matrix(self, raw: str) -> list[str]:
        if not raw:
            return []
        values: list[str] = []
        for chunk in re.split(r"[\n,]+", raw):
            sanitized = chunk.strip()
            if sanitized:
                values.append(sanitized)
        return values

    def _parse_hypernetworks(self, raw: str) -> list[dict[str, Any]]:
        if not raw:
            return []
        entries: list[dict[str, Any]] = []
        for chunk in re.split(r"[\n,]+", raw):
            sanitized = chunk.strip()
            if not sanitized:
                continue
            if ":" in sanitized:
                name, strength = sanitized.split(":", 1)
                try:
                    weight = float(strength.strip())
                except ValueError:
                    weight = 1.0
                entries.append({"name": name.strip(), "strength": weight})
            else:
                entries.append({"name": sanitized, "strength": 1.0})
        return entries

    def _set_model_matrix_display(self, value):
        if isinstance(value, list):
            self.model_matrix_var.set(", ".join(value))
        else:
            self.model_matrix_var.set(str(value))

    def _set_hypernetwork_display(self, value):
        if isinstance(value, list):
            self.hypernetworks_var.set(
                ", ".join(
                    f"{item.get('name')}:{item.get('strength', 1.0)}"
                    for item in value
                    if item and item.get("name")
                )
            )
        else:
            self.hypernetworks_var.set(str(value))
