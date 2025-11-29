"""ADetailer configuration panel for face and detail enhancement."""
# Phase 3+/4 GUI extras:
# Not required for Phase 1 stability; used by future adetailer/randomizer/job history workflows only.

import logging
import tkinter as tk
from tkinter import ttk
from typing import Any, Iterable

logger = logging.getLogger(__name__)


class ADetailerConfigPanel:
    """Panel for configuring ADetailer settings.

    ADetailer is an extension for automatic face/detail detection and enhancement.
    This panel provides controls for model selection, detection confidence,
    and processing parameters.
    """

    # Available ADetailer models
    AVAILABLE_MODELS = [
        "face_yolov8n.pt",
        "face_yolov8s.pt",
        "hand_yolov8n.pt",
        "person_yolov8n-seg.pt",
        "mediapipe_face_full",
        "mediapipe_face_short",
        "mediapipe_face_mesh",
    ]

    SCHEDULER_OPTIONS = [
        "inherit",
        "Automatic",
        "Karras",
        "Exponential",
        "Polyexponential",
        "SGM Uniform",
    ]

    # Default configuration
    DEFAULT_CONFIG = {
        "adetailer_enabled": False,
        "adetailer_model": "face_yolov8n.pt",
        "adetailer_confidence": 0.3,
        "adetailer_mask_feather": 4,
        "adetailer_sampler": "DPM++ 2M",
        "adetailer_scheduler": "inherit",
        "adetailer_steps": 28,
        "adetailer_denoise": 0.4,
        "adetailer_cfg": 7.0,
        "adetailer_prompt": "",
        "adetailer_negative_prompt": "",
    }

    def __init__(self, parent: tk.Widget):
        """Initialize ADetailer configuration panel.

        Args:
            parent: Parent widget
        """
        self.parent = parent

        # Create main frame
        self.frame = ttk.LabelFrame(parent, text="ADetailer Configuration", padding=10)

        # Initialize variables
        self.enabled_var = tk.BooleanVar(value=self.DEFAULT_CONFIG["adetailer_enabled"])
        self.model_var = tk.StringVar(value=self.DEFAULT_CONFIG["adetailer_model"])
        self.confidence_var = tk.DoubleVar(value=self.DEFAULT_CONFIG["adetailer_confidence"])
        self.mask_feather_var = tk.IntVar(value=self.DEFAULT_CONFIG["adetailer_mask_feather"])
        self.sampler_var = tk.StringVar(value=self.DEFAULT_CONFIG["adetailer_sampler"])
        self.scheduler_var = tk.StringVar(value=self.DEFAULT_CONFIG["adetailer_scheduler"])
        self.steps_var = tk.IntVar(value=self.DEFAULT_CONFIG["adetailer_steps"])
        self.denoise_var = tk.DoubleVar(value=self.DEFAULT_CONFIG["adetailer_denoise"])
        self.cfg_var = tk.DoubleVar(value=self.DEFAULT_CONFIG["adetailer_cfg"])

        # Build UI
        self._build_ui()

        # Setup enable/disable behavior
        self._on_enabled_changed()

    def _build_ui(self):
        """Build the configuration UI."""
        # Enable checkbox
        enable_frame = ttk.Frame(self.frame)
        enable_frame.grid(row=0, column=0, columnspan=2, sticky=tk.W, pady=(0, 10))

        self.enable_check = ttk.Checkbutton(
            enable_frame,
            text="Enable ADetailer (Automatic face/detail enhancement)",
            variable=self.enabled_var,
            command=self._on_enabled_changed,
        )
        self.enable_check.pack(side=tk.LEFT)

        # Model selection
        model_label = ttk.Label(self.frame, text="Model:")
        model_label.grid(row=1, column=0, sticky=tk.W, pady=2)

        self.model_combo = ttk.Combobox(
            self.frame,
            textvariable=self.model_var,
            values=self.AVAILABLE_MODELS,
            state="readonly",
            width=25,
        )
        self.model_combo.grid(row=1, column=1, sticky=tk.W, pady=2, padx=(5, 0))

        # Confidence threshold
        conf_label = ttk.Label(self.frame, text="Detection Confidence:")
        conf_label.grid(row=2, column=0, sticky=tk.W, pady=2)

        conf_frame = ttk.Frame(self.frame)
        conf_frame.grid(row=2, column=1, sticky=tk.W, pady=2, padx=(5, 0))

        self.confidence_scale = ttk.Scale(
            conf_frame,
            from_=0.0,
            to=1.0,
            orient=tk.HORIZONTAL,
            variable=self.confidence_var,
            length=150,
        )
        self.confidence_scale.pack(side=tk.LEFT)

        self.confidence_label = ttk.Label(conf_frame, text="0.30")
        self.confidence_label.pack(side=tk.LEFT, padx=(5, 0))
        self.confidence_scale.configure(command=self._update_confidence_label)

        # Mask feather
        feather_label = ttk.Label(self.frame, text="Mask Feather:")
        feather_label.grid(row=3, column=0, sticky=tk.W, pady=2)

        self.feather_spin = ttk.Spinbox(
            self.frame, from_=0, to=64, textvariable=self.mask_feather_var, width=10
        )
        self.feather_spin.grid(row=3, column=1, sticky=tk.W, pady=2, padx=(5, 0))

        # Sampler
        sampler_label = ttk.Label(self.frame, text="Sampler:")
        sampler_label.grid(row=4, column=0, sticky=tk.W, pady=2)

        self.sampler_combo = ttk.Combobox(
            self.frame,
            textvariable=self.sampler_var,
            values=["DPM++ 2M", "DPM++ SDE", "Euler a", "Euler", "DDIM", "PLMS"],
            width=15,
        )
        self.sampler_combo.grid(row=4, column=1, sticky=tk.W, pady=2, padx=(5, 0))

        # Scheduler
        scheduler_label = ttk.Label(self.frame, text="Scheduler:")
        scheduler_label.grid(row=5, column=0, sticky=tk.W, pady=2)

        self.scheduler_combo = ttk.Combobox(
            self.frame,
            textvariable=self.scheduler_var,
            values=self.SCHEDULER_OPTIONS,
            width=20,
            state="readonly",
        )
        self.scheduler_combo.grid(row=5, column=1, sticky=tk.W, pady=2, padx=(5, 0))

        # Steps
        steps_label = ttk.Label(self.frame, text="Steps:")
        steps_label.grid(row=6, column=0, sticky=tk.W, pady=2)

        self.steps_spin = ttk.Spinbox(
            self.frame, from_=1, to=150, textvariable=self.steps_var, width=10
        )
        self.steps_spin.grid(row=6, column=1, sticky=tk.W, pady=2, padx=(5, 0))

        # Denoise strength
        denoise_label = ttk.Label(self.frame, text="Denoise Strength:")
        denoise_label.grid(row=7, column=0, sticky=tk.W, pady=2)

        denoise_frame = ttk.Frame(self.frame)
        denoise_frame.grid(row=7, column=1, sticky=tk.W, pady=2, padx=(5, 0))

        self.denoise_scale = ttk.Scale(
            denoise_frame,
            from_=0.0,
            to=1.0,
            orient=tk.HORIZONTAL,
            variable=self.denoise_var,
            length=150,
        )
        self.denoise_scale.pack(side=tk.LEFT)

        self.denoise_label = ttk.Label(denoise_frame, text="0.40")
        self.denoise_label.pack(side=tk.LEFT, padx=(5, 0))
        self.denoise_scale.configure(command=self._update_denoise_label)

        # CFG Scale
        cfg_label = ttk.Label(self.frame, text="CFG Scale:")
        cfg_label.grid(row=8, column=0, sticky=tk.W, pady=2)

        self.cfg_spin = ttk.Spinbox(
            self.frame, from_=1.0, to=30.0, textvariable=self.cfg_var, width=10, increment=0.5
        )
        self.cfg_spin.grid(row=8, column=1, sticky=tk.W, pady=2, padx=(5, 0))

        # Prompt
        prompt_label = ttk.Label(self.frame, text="Positive Prompt:")
        prompt_label.grid(row=9, column=0, sticky=tk.NW, pady=2)

        self.prompt_text = tk.Text(self.frame, height=3, width=40)
        self.prompt_text.grid(row=9, column=1, sticky=tk.W, pady=2, padx=(5, 0))

        # Negative prompt
        neg_prompt_label = ttk.Label(self.frame, text="Negative Prompt:")
        neg_prompt_label.grid(row=10, column=0, sticky=tk.NW, pady=2)

        self.neg_prompt_text = tk.Text(self.frame, height=3, width=40)
        self.neg_prompt_text.grid(row=10, column=1, sticky=tk.W, pady=2, padx=(5, 0))

    def _update_confidence_label(self, value):
        """Update confidence label with current value."""
        self.confidence_label.config(text=f"{float(value):.2f}")

    def _update_denoise_label(self, value):
        """Update denoise label with current value."""
        self.denoise_label.config(text=f"{float(value):.2f}")

    def _on_enabled_changed(self):
        """Handle enable/disable toggle."""
        enabled = self.enabled_var.get()
        state = "normal" if enabled else "disabled"

        # Update all controls
        self.model_combo.configure(state="readonly" if enabled else "disabled")
        self.confidence_scale.configure(state=state)
        self.feather_spin.configure(state=state)
        self.sampler_combo.configure(state="readonly" if enabled else "disabled")
        self.scheduler_combo.configure(state="readonly" if enabled else "disabled")
        self.steps_spin.configure(state=state)
        self.denoise_scale.configure(state=state)
        self.cfg_spin.configure(state=state)
        self.prompt_text.configure(state=state)
        self.neg_prompt_text.configure(state=state)

    def get_config(self) -> dict[str, Any]:
        """Get current configuration.

        Returns:
            Dictionary of ADetailer configuration
        """
        scheduler_value = self.scheduler_var.get() or "inherit"
        return {
            "adetailer_enabled": self.enabled_var.get(),
            "adetailer_model": self.model_var.get(),
            "adetailer_confidence": self.confidence_var.get(),
            "adetailer_mask_feather": self.mask_feather_var.get(),
            "adetailer_sampler": self.sampler_var.get(),
            "adetailer_scheduler": scheduler_value,
            "scheduler": scheduler_value,
            "adetailer_steps": self.steps_var.get(),
            "adetailer_denoise": self.denoise_var.get(),
            "adetailer_cfg": self.cfg_var.get(),
            "adetailer_prompt": self.prompt_text.get("1.0", tk.END).strip(),
            "adetailer_negative_prompt": self.neg_prompt_text.get("1.0", tk.END).strip(),
        }

    def set_config(self, config: dict[str, Any]) -> None:
        """Set configuration values.

        Args:
            config: Dictionary of ADetailer configuration
        """
        if "adetailer_enabled" in config:
            self.enabled_var.set(config["adetailer_enabled"])
        if "adetailer_model" in config:
            self.model_var.set(config["adetailer_model"])
        if "adetailer_confidence" in config:
            self.confidence_var.set(config["adetailer_confidence"])
            self._update_confidence_label(config["adetailer_confidence"])
        if "adetailer_mask_feather" in config:
            self.mask_feather_var.set(config["adetailer_mask_feather"])
        if "adetailer_sampler" in config:
            self.sampler_var.set(config["adetailer_sampler"])
        scheduler_value = config.get("adetailer_scheduler", config.get("scheduler"))
        if scheduler_value is not None:
            value = scheduler_value or "inherit"
            if value not in self.SCHEDULER_OPTIONS:
                value = "inherit"
            self.scheduler_var.set(value)
        else:
            self.scheduler_var.set("inherit")
        if "adetailer_steps" in config:
            self.steps_var.set(config["adetailer_steps"])
        if "adetailer_denoise" in config:
            self.denoise_var.set(config["adetailer_denoise"])
            self._update_denoise_label(config["adetailer_denoise"])
        if "adetailer_cfg" in config:
            self.cfg_var.set(config["adetailer_cfg"])
        if "adetailer_prompt" in config:
            self.prompt_text.configure(state=tk.NORMAL)
            self.prompt_text.delete("1.0", tk.END)
            self.prompt_text.insert("1.0", config["adetailer_prompt"])
        if "adetailer_negative_prompt" in config:
            self.neg_prompt_text.configure(state=tk.NORMAL)
            self.neg_prompt_text.delete("1.0", tk.END)
            self.neg_prompt_text.insert("1.0", config["adetailer_negative_prompt"])

        self._on_enabled_changed()

    def validate_config(self, config: dict[str, Any]) -> bool:
        """Validate configuration values.

        Args:
            config: Configuration to validate

        Returns:
            True if valid, False otherwise
        """
        # Check confidence is in valid range
        if "adetailer_confidence" in config:
            conf = config["adetailer_confidence"]
            if not 0.0 <= conf <= 1.0:
                logger.error(f"Invalid confidence: {conf} (must be 0.0-1.0)")
                return False

        # Check denoise is in valid range
        if "adetailer_denoise" in config:
            denoise = config["adetailer_denoise"]
            if not 0.0 <= denoise <= 1.0:
                logger.error(f"Invalid denoise: {denoise} (must be 0.0-1.0)")
                return False

        # Check steps is positive
        if "adetailer_steps" in config:
            steps = config["adetailer_steps"]
            if steps < 1:
                logger.error(f"Invalid steps: {steps} (must be >= 1)")
                return False

        scheduler_value = config.get("adetailer_scheduler", config.get("scheduler"))
        if scheduler_value is not None:
            normalized = scheduler_value or "inherit"
            if normalized not in self.SCHEDULER_OPTIONS:
                logger.error(f"Invalid scheduler: {scheduler_value}")
                return False

        return True

    def get_available_models(self) -> list[str]:
        """Get list of available ADetailer models.

        Returns:
            List of model names
        """
        return self.AVAILABLE_MODELS.copy()

    def generate_api_payload(self) -> dict[str, Any]:
        """Generate API payload for ADetailer.

        Returns:
            Dictionary formatted for SD WebUI API
        """
        config = self.get_config()

        scheduler_value = config.get("adetailer_scheduler", config.get("scheduler", "inherit")) or "inherit"

        payload = {
            "adetailer_model": config["adetailer_model"],
            "adetailer_conf": config["adetailer_confidence"],
            "adetailer_mask_blur": config["adetailer_mask_feather"],
            "adetailer_sampler": config["adetailer_sampler"],
            "adetailer_steps": config["adetailer_steps"],
            "adetailer_denoise": config["adetailer_denoise"],
            "adetailer_cfg_scale": config["adetailer_cfg"],
            "adetailer_prompt": config["adetailer_prompt"],
            "adetailer_negative_prompt": config["adetailer_negative_prompt"],
        }

        if scheduler_value != "inherit":
            payload["adetailer_scheduler"] = scheduler_value

        return payload

    def set_sampler_options(self, samplers: Iterable[str] | None) -> None:
        """Update the sampler dropdown with the provided options."""
        cleaned: list[str] = []
        for sampler in samplers or []:
            if sampler is None:
                continue
            text = str(sampler).strip()
            if text and text not in cleaned:
                cleaned.append(text)

        if not cleaned:
            cleaned = ["Euler a"]

        cleaned.sort(key=str.lower)
        self.sampler_combo.configure(values=cleaned)

        current = self.sampler_var.get()
        if current not in cleaned:
            self.sampler_var.set(cleaned[0])
