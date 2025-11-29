from __future__ import annotations

import tkinter as tk
from tkinter import ttk
from typing import Any, Callable

from src.gui.state import PipelineState


class PipelineConfigPanel(ttk.Frame):
    """Left-column pipeline config scaffold bound to PipelineState."""

    def __init__(self, master: tk.Misc, pipeline_state: PipelineState, app_state: Any = None, on_change: Callable[[], None] | None = None, *args, **kwargs) -> None:
        super().__init__(master, *args, **kwargs)
        self.pipeline_state = pipeline_state
        self.app_state = app_state
        self._on_change = on_change
        self._lora_controls: dict[str, tuple[ttk.Checkbutton, ttk.Scale]] = {}

        ttk.Label(self, text="Run Mode").pack(anchor="w")
        mode_frame = ttk.Frame(self)
        mode_frame.pack(anchor="w", pady=(0, 6))
        self.run_mode_var = tk.StringVar(value=self.pipeline_state.run_mode)
        ttk.Radiobutton(mode_frame, text="Direct", value="direct", variable=self.run_mode_var, command=self._on_mode_change).pack(side="left")
        ttk.Radiobutton(mode_frame, text="Queue", value="queue", variable=self.run_mode_var, command=self._on_mode_change).pack(side="left", padx=(6, 0))

        ttk.Label(self, text="Batch Runs").pack(anchor="w")
        self.batch_var = tk.IntVar(value=self.pipeline_state.batch_runs)
        batch_spin = ttk.Spinbox(self, from_=1, to=999, textvariable=self.batch_var, width=6, command=self._on_batch_change)
        batch_spin.pack(anchor="w", pady=(0, 6))
        batch_spin.bind("<FocusOut>", lambda _e: self._on_batch_change())

        ttk.Label(self, text="Randomizer").pack(anchor="w")
        self.randomizer_var = tk.StringVar(value=self.pipeline_state.randomizer_mode)
        rand_combo = ttk.Combobox(
            self,
            values=["off", "sequential", "rotate", "random"],
            state="readonly",
            textvariable=self.randomizer_var,
        )
        rand_combo.pack(anchor="w", pady=(0, 4))
        rand_combo.bind("<<ComboboxSelected>>", lambda _e: self._on_randomizer_change())

        ttk.Label(self, text="Max Variants").pack(anchor="w")
        self.max_variants_var = tk.IntVar(value=self.pipeline_state.max_variants)
        max_spin = ttk.Spinbox(
            self, from_=1, to=50, textvariable=self.max_variants_var, width=6, command=self._on_max_variants_change
        )
        max_spin.pack(anchor="w", pady=(0, 6))
        max_spin.bind("<FocusOut>", lambda _e: self._on_max_variants_change())

        ttk.Label(self, text="Stages").pack(anchor="w")
        self.txt2img_var = tk.BooleanVar(value=self.pipeline_state.stage_txt2img_enabled)
        self.img2img_var = tk.BooleanVar(value=self.pipeline_state.stage_img2img_enabled)
        self.upscale_var = tk.BooleanVar(value=self.pipeline_state.stage_upscale_enabled)
        ttk.Checkbutton(self, text="Enable txt2img", variable=self.txt2img_var, command=self._on_stage_change).pack(anchor="w")
        ttk.Checkbutton(self, text="Enable img2img/adetailer", variable=self.img2img_var, command=self._on_stage_change).pack(anchor="w")
        ttk.Checkbutton(self, text="Enable upscale", variable=self.upscale_var, command=self._on_stage_change).pack(anchor="w", pady=(0, 6))

        self.queue_label_var = tk.StringVar()
        ttk.Label(self, textvariable=self.queue_label_var).pack(anchor="w", pady=(4, 0))
        self._refresh_queue_label()

        # LoRA Runtime Controls section
        ttk.Label(self, text="LoRA Runtime Controls").pack(anchor="w", pady=(10, 4))
        self._lora_frame = ttk.Frame(self)
        self._lora_frame.pack(anchor="w", fill="x", pady=(0, 6))
        self._refresh_lora_controls()

    def _refresh_queue_label(self) -> None:
        self.queue_label_var.set(f"Pending jobs: {self.pipeline_state.pending_jobs}")

    def _on_mode_change(self) -> None:
        self.pipeline_state.run_mode = self.run_mode_var.get()
        if callable(self._on_change):
            self._on_change()

    def _on_batch_change(self) -> None:
        try:
            value = int(self.batch_var.get())
        except Exception:
            value = 1
        value = max(1, value)
        self.batch_var.set(value)
        self.pipeline_state.batch_runs = value
        if callable(self._on_change):
            self._on_change()

    def _on_randomizer_change(self) -> None:
        self.pipeline_state.randomizer_mode = self.randomizer_var.get()
        if callable(self._on_change):
            self._on_change()

    def _on_max_variants_change(self) -> None:
        try:
            value = int(self.max_variants_var.get())
        except Exception:
            value = 1
        value = max(1, value)
        self.max_variants_var.set(value)
        self.pipeline_state.max_variants = value
        if callable(self._on_change):
            self._on_change()

    def _on_stage_change(self) -> None:
        self.pipeline_state.stage_txt2img_enabled = bool(self.txt2img_var.get())
        self.pipeline_state.stage_img2img_enabled = bool(self.img2img_var.get())
        self.pipeline_state.stage_upscale_enabled = bool(self.upscale_var.get())
        if callable(self._on_change):
            self._on_change()

    def _refresh_lora_controls(self) -> None:
        """Refresh LoRA controls based on current prompt metadata."""
        # Clear existing controls
        for widget in self._lora_frame.winfo_children():
            widget.destroy()
        self._lora_controls.clear()

        # Get current LoRAs from prompt metadata
        if not self.app_state or not hasattr(self.app_state, 'prompt_workspace_state'):
            return

        metadata = self.app_state.prompt_workspace_state.get_current_prompt_metadata()
        if not metadata.loras:
            # Show "No LoRAs detected" message
            ttk.Label(self._lora_frame, text="No LoRAs detected", foreground="gray").pack(anchor="w")
            return

        # Create controls for each LoRA
        for lora_ref in metadata.loras:
            lora_name = lora_ref.name
            settings = self.pipeline_state.get_lora_setting(lora_name)

            # Create frame for this LoRA
            lora_frame = ttk.Frame(self._lora_frame)
            lora_frame.pack(anchor="w", fill="x", pady=(2, 0))

            # Checkbox for enabled/disabled
            enabled_var = tk.BooleanVar(value=settings.enabled)
            checkbox = ttk.Checkbutton(
                lora_frame,
                text=lora_name,
                variable=enabled_var,
                command=lambda name=lora_name, var=enabled_var: self._on_lora_enabled_change(name, var.get())
            )
            checkbox.pack(side="left")

            # Scale for strength
            strength_var = tk.DoubleVar(value=settings.strength)
            scale = ttk.Scale(
                lora_frame,
                from_=0.0,
                to=1.5,
                variable=strength_var,
                orient="horizontal",
                command=lambda val, name=lora_name: self._on_lora_strength_change(name, float(val))
            )
            scale.pack(side="left", fill="x", expand=True, padx=(10, 0))

            # Store references
            self._lora_controls[lora_name] = (checkbox, scale)

    def _on_lora_enabled_change(self, lora_name: str, enabled: bool) -> None:
        """Handle LoRA enabled/disabled change."""
        current_settings = self.pipeline_state.get_lora_setting(lora_name)
        self.pipeline_state.set_lora_setting(lora_name, enabled, current_settings.strength)
        if callable(self._on_change):
            self._on_change()

    def _on_lora_strength_change(self, lora_name: str, strength: float) -> None:
        """Handle LoRA strength change."""
        current_settings = self.pipeline_state.get_lora_setting(lora_name)
        self.pipeline_state.set_lora_setting(lora_name, current_settings.enabled, strength)
        if callable(self._on_change):
            self._on_change()

    def refresh_lora_controls(self) -> None:
        """Public method to refresh LoRA controls (can be called when prompt changes)."""
        self._refresh_lora_controls()
