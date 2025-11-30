from __future__ import annotations
import tkinter as tk
from tkinter import ttk
from typing import Any, Callable

from src.gui.state import PipelineState
from src.gui.theme_v2 import CARD_FRAME_STYLE, BODY_LABEL_STYLE

class PipelineConfigPanel(ttk.Frame):
    """Left-column pipeline config scaffold bound to AppController/AppStateV2."""

    def __init__(self, master: tk.Misc, controller: Any = None, app_state: Any = None, on_change: Callable[[], None] | None = None, *args: Any, **kwargs: Any) -> None:
        super().__init__(master, style=CARD_FRAME_STYLE, *args, **kwargs)
        self.controller = controller
        self.app_state = app_state
        self._on_change = on_change
        self._lora_controls: dict[str, tuple[ttk.Checkbutton, ttk.Scale]] = {}
        # Legacy validation label - removed for cleaner UI
        # self._validation_message_var = tk.StringVar(value="")
        # self._validation_label = ttk.Label(
        #     self,
        #     textvariable=self._validation_message_var,
        #     background="#3A3A3A",
        #     foreground="#FFD700",
        #     anchor="w",
        #     padding=(4, 2),
        # )
        # self._validation_label.pack(fill="x", pady=(0, 8))

        # Initialize with defaults
        self.run_mode_var = tk.StringVar(value="direct")
        self.batch_var = tk.IntVar(value=1)
        self.randomizer_var = tk.StringVar(value="off")
        self.max_variants_var = tk.IntVar(value=1)
        self.txt2img_var = tk.BooleanVar(value=True)
        self.img2img_var = tk.BooleanVar(value=True)
        self.upscale_var = tk.BooleanVar(value=True)

        self._build_ui()
        self._setup_callbacks()

        # Apply initial config if available
        if self.controller:
            self.apply_run_config(self.controller.get_current_config())

    def _build_ui(self) -> None:
        """Build the configuration UI."""
        # Configure grid layout for compact design
        self.columnconfigure(0, weight=0)  # Labels column
        self.columnconfigure(1, weight=1)  # Inputs column
        
        row = 0
        
        # Run Mode
        ttk.Label(self, text="Run Mode:", style=BODY_LABEL_STYLE).grid(row=row, column=0, sticky="w", pady=2)
        mode_frame = ttk.Frame(self, style=CARD_FRAME_STYLE)
        mode_frame.grid(row=row, column=1, sticky="ew", pady=2)
        ttk.Radiobutton(mode_frame, text="Direct", value="direct", variable=self.run_mode_var, command=self._on_mode_change).pack(side="left")
        ttk.Radiobutton(mode_frame, text="Queue", value="queue", variable=self.run_mode_var, command=self._on_mode_change).pack(side="left", padx=(6, 0))
        row += 1
        
        # Batch Runs
        ttk.Label(self, text="Batch Runs:", style=BODY_LABEL_STYLE).grid(row=row, column=0, sticky="w", pady=2)
        batch_spin = ttk.Spinbox(self, from_=1, to=999, textvariable=self.batch_var, width=6, command=self._on_batch_change)
        batch_spin.grid(row=row, column=1, sticky="w", pady=2)
        batch_spin.bind("<FocusOut>", lambda _e: self._on_batch_change())
        row += 1
        
        # Randomizer
        ttk.Label(self, text="Randomizer:", style=BODY_LABEL_STYLE).grid(row=row, column=0, sticky="w", pady=2)
        rand_combo = ttk.Combobox(
            self,
            values=["off", "sequential", "rotate", "random"],
            state="readonly",
            textvariable=self.randomizer_var,
            width=12
        )
        rand_combo.grid(row=row, column=1, sticky="w", pady=2)
        rand_combo.bind("<<ComboboxSelected>>", lambda _e: self._on_randomizer_change())
        row += 1
        
        # Max Variants
        ttk.Label(self, text="Max Variants:", style=BODY_LABEL_STYLE).grid(row=row, column=0, sticky="w", pady=2)
        max_spin = ttk.Spinbox(
            self, from_=1, to=50, textvariable=self.max_variants_var, width=6, command=self._on_max_variants_change
        )
        max_spin.grid(row=row, column=1, sticky="w", pady=2)
        max_spin.bind("<FocusOut>", lambda _e: self._on_max_variants_change())
        row += 1
        
        # Stages
        ttk.Label(self, text="Stages:", style=BODY_LABEL_STYLE).grid(row=row, column=0, sticky="nw", pady=2)
        stages_frame = ttk.Frame(self, style=CARD_FRAME_STYLE)
        stages_frame.grid(row=row, column=1, sticky="w", pady=2)
        ttk.Checkbutton(stages_frame, text="Enable txt2img", variable=self.txt2img_var, command=self._on_stage_change).pack(anchor="w")
        ttk.Checkbutton(stages_frame, text="Enable img2img/adetailer", variable=self.img2img_var, command=self._on_stage_change).pack(anchor="w")
        ttk.Checkbutton(stages_frame, text="Enable upscale", variable=self.upscale_var, command=self._on_stage_change).pack(anchor="w")
        
        # Legacy queue status label - removed for cleaner UI
        # self.queue_label_var = tk.StringVar()
        # ttk.Label(self, textvariable=self.queue_label_var).grid(row=row+1, column=0, columnspan=2, sticky="w", pady=(4, 0))

    def _setup_callbacks(self) -> None:
        """Setup callbacks for config changes."""
        if self.controller:
            # Connect to controller methods for config changes
            pass  # Will be implemented when controller methods are available

    def apply_run_config(self, config: dict[str, Any]) -> None:
        """Apply run configuration to the panel."""
        # Update stage checkboxes based on pipeline config
        pipeline_config = config.get("pipeline", {})
        if "txt2img_enabled" in pipeline_config:
            self.txt2img_var.set(bool(pipeline_config["txt2img_enabled"]))
        if "img2img_enabled" in pipeline_config:
            self.img2img_var.set(bool(pipeline_config["img2img_enabled"]))
        if "upscale_enabled" in pipeline_config:
            self.upscale_var.set(bool(pipeline_config["upscale_enabled"]))
        
        # Update other fields if they exist in the config
        if "loop_count" in pipeline_config:
            try:
                batch_count = int(pipeline_config["loop_count"])
                self.batch_var.set(max(1, batch_count))
            except (ValueError, TypeError):
                pass
        
        # TODO: Update model/sampler dropdowns when available
        # TODO: Update randomization settings when available

    def apply_resources(self, resources: dict[str, list[Any]]) -> None:
        """Apply resource lists (models, samplers, etc.) to dropdowns."""
        # TODO: Populate model, sampler, scheduler dropdowns
        pass

    def set_validation_message(self, message: str) -> None:
        # Legacy method - validation label removed for cleaner UI
        pass
        # if not message:
        #     self._validation_message_var.set("")
        #     return
        # self._validation_message_var.set(message)
        # self._refresh_queue_label()

    def _refresh_queue_label(self) -> None:
        # Legacy method - queue label removed for cleaner UI
        pass
        # TODO: Connect to actual queue state when available
        # self.queue_label_var.set("Pending jobs: 0")

    def _on_mode_change(self) -> None:
        if callable(self._on_change):
            self._on_change()

    def _on_batch_change(self) -> None:
        try:
            value = int(self.batch_var.get())
        except Exception:
            value = 1
        value = max(1, value)
        self.batch_var.set(value)
        if callable(self._on_change):
            self._on_change()

    def _on_randomizer_change(self) -> None:
        if callable(self._on_change):
            self._on_change()

    def _on_max_variants_change(self) -> None:
        try:
            value = int(self.max_variants_var.get())
        except Exception:
            value = 1
        value = max(1, value)
        self.max_variants_var.set(value)
        if callable(self._on_change):
            self._on_change()

    def _on_stage_change(self) -> None:
        if callable(self._on_change):
            self._on_change()
