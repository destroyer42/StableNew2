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
        self.randomizer_enabled_var = tk.BooleanVar(value=False)
        self.max_variants_var = tk.IntVar(value=1)
        self._max_variants_spinbox: ttk.Spinbox | None = None

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
        batch_spin = ttk.Spinbox(
            self,
            from_=1,
            to=999,
            textvariable=self.batch_var,
            width=6,
            command=self._on_batch_change,
            style="Dark.TSpinbox",
        )
        batch_spin.grid(row=row, column=1, sticky="w", pady=2)
        batch_spin.bind("<FocusOut>", lambda _e: self._on_batch_change())
        row += 1
        
        randomizer_label = ttk.Label(self, text="Randomizer:", style=BODY_LABEL_STYLE)
        randomizer_label.grid(row=row, column=0, sticky="w", pady=2)
        randomizer_frame = ttk.Frame(self, style=CARD_FRAME_STYLE)
        randomizer_frame.grid(row=row, column=1, sticky="w", pady=2)
        enable_cb = ttk.Checkbutton(
            randomizer_frame,
            text="Enable randomization",
            variable=self.randomizer_enabled_var,
            command=self._on_randomizer_toggle,
            style="Dark.TCheckbutton",
        )
        enable_cb.pack(side="left")
        max_spin = ttk.Spinbox(
            randomizer_frame,
            from_=1,
            to=999,
            textvariable=self.max_variants_var,
            width=6,
            command=self._on_max_variants_change,
            style="Dark.TSpinbox",
        )
        max_spin.pack(side="left", padx=(8, 0))
        max_spin.bind("<FocusOut>", lambda _e: self._on_max_variants_change())
        ttk.Label(randomizer_frame, text="Max variants", style=BODY_LABEL_STYLE).pack(side="left", padx=(6, 0))
        self._max_variants_spinbox = max_spin
        self._update_randomizer_spin_state(bool(self.randomizer_enabled_var.get()))

        self._lora_container = ttk.Frame(self, style=CARD_FRAME_STYLE)
        row += 1
        self._lora_container.grid(row=row, column=0, columnspan=2, sticky="ew", pady=(8, 0))
        row += 1
        self._refresh_lora_controls()
        
        # Legacy queue status label - removed for cleaner UI
        # self.queue_label_var = tk.StringVar()
        # ttk.Label(self, textvariable=self.queue_label_var).grid(row=row, column=0, columnspan=2, sticky="w", pady=(4, 0))

    def _setup_callbacks(self) -> None:
        """Setup callbacks for config changes."""
        if self.controller:
            # Connect to controller methods for config changes
            pass  # Will be implemented when controller methods are available

    def apply_run_config(self, config: dict[str, Any]) -> None:
        """Apply run configuration to the panel."""
        # Update other fields if they exist in the config
        if "loop_count" in config.get("pipeline", {}):
            try:
                batch_count = int(config["pipeline"]["loop_count"])
                self.batch_var.set(max(1, batch_count))
            except (ValueError, TypeError):
                pass

        # TODO: Update model/sampler dropdowns when available
        self._apply_randomizer_config(config)
        self._refresh_lora_controls()

    def _apply_randomizer_config(self, config: dict[str, Any]) -> None:
        enabled = bool(config.get("randomization_enabled", False))
        try:
            max_variants = max(1, int(config.get("max_variants", 1)))
        except (TypeError, ValueError):
            max_variants = 1
        self.randomizer_enabled_var.set(enabled)
        self.max_variants_var.set(max_variants)
        self._update_randomizer_spin_state(enabled)

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

    def _on_max_variants_change(self) -> None:
        try:
            value = int(self.max_variants_var.get())
        except Exception:
            value = 1
        value = max(1, value)
        self.max_variants_var.set(value)
        if self.controller and hasattr(self.controller, "on_randomizer_max_variants_changed"):
            try:
                self.controller.on_randomizer_max_variants_changed(value)
            except Exception:
                pass
        if callable(self._on_change):
            self._on_change()

    def _on_randomizer_toggle(self) -> None:
        enabled = bool(self.randomizer_enabled_var.get())
        self._update_randomizer_spin_state(enabled)
        if self.controller and hasattr(self.controller, "on_randomization_toggled"):
            try:
                self.controller.on_randomization_toggled(enabled)
            except Exception:
                pass
        if callable(self._on_change):
            self._on_change()

    def _update_randomizer_spin_state(self, enabled: bool) -> None:
        if self._max_variants_spinbox is not None:
            state = "normal" if enabled else "disabled"
            try:
                self._max_variants_spinbox.configure(state=state)
            except Exception:
                pass

    def _refresh_lora_controls(self) -> None:
        """Render LoRA settings fetched from the controller."""
        for child in self._lora_container.winfo_children():
            child.destroy()
        self._lora_controls.clear()
        entries = self._get_lora_settings()
        if not entries:
            ttk.Label(self._lora_container, text="LoRA strengths not available", style=BODY_LABEL_STYLE).pack(anchor="w", pady=2)
            return
        for entry in entries:
            name = str(entry.get("name") or "Unnamed").strip()
            if not name:
                continue
            enabled = bool(entry.get("enabled", True))
            strength = float(entry.get("strength", 1.0))
            frame = ttk.Frame(self._lora_container)
            frame.pack(fill="x", pady=4)
            ttk.Label(frame, text=name, style=BODY_LABEL_STYLE).pack(anchor="w")
            controls = ttk.Frame(frame)
            controls.pack(fill="x", pady=(2, 0))
            var = tk.DoubleVar(value=strength)
            scale = ttk.Scale(
                controls,
                from_=0.0,
                to=2.0,
                variable=var,
                orient="horizontal",
                command=lambda value, lora=name: self._on_lora_strength_change(lora, value),
            )
            scale.pack(side="left", fill="x", expand=True, padx=(0, 4))
            check_var = tk.BooleanVar(value=enabled)
            chk = ttk.Checkbutton(
                controls,
                text="Enabled",
                variable=check_var,
                command=lambda lora=name, var=check_var: self._on_lora_enabled_change(lora, var.get()),
            )
            chk.pack(side="right")
            self._lora_controls[name] = (check_var, scale)

    def _get_lora_settings(self) -> list[dict[str, Any]]:
        if self.controller and hasattr(self.controller, "get_lora_runtime_settings"):
            try:
                return self.controller.get_lora_runtime_settings()
            except Exception:
                return []
        return []

    def get_randomizer_config(self) -> dict[str, Any]:
        enabled = bool(self.randomizer_enabled_var.get())
        try:
            max_variants = max(1, int(self.max_variants_var.get()))
        except Exception:
            max_variants = 1
        return {"randomization_enabled": enabled, "max_variants": max_variants}

    def _on_lora_strength_change(self, lora_name: str, value: Any) -> None:
        if not self.controller or not hasattr(self.controller, "update_lora_runtime_strength"):
            return
        try:
            strength = float(value)
        except Exception:
            return
        self.controller.update_lora_runtime_strength(lora_name, strength)
        if callable(self._on_change):
            self._on_change()

    def _on_lora_enabled_change(self, lora_name: str, value: Any) -> None:
        if not self.controller or not hasattr(self.controller, "update_lora_runtime_enabled"):
            return
        enabled = bool(value)
        self.controller.update_lora_runtime_enabled(lora_name, enabled)
        if callable(self._on_change):
            self._on_change()
