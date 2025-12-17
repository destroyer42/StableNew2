from __future__ import annotations

import tkinter as tk
from tkinter import ttk
from typing import Any

from src.gui.controllers.learning_controller import LearningController


class ExperimentDesignPanel(ttk.Frame):
    """Left panel for experiment design controls."""

    def __init__(
        self,
        master: tk.Misc,
        learning_controller: LearningController | None = None,
        *args,
        **kwargs,
    ) -> None:
        super().__init__(master, *args, **kwargs)
        self.learning_controller = learning_controller

        # Configure layout
        self.columnconfigure(0, weight=1)
        self.rowconfigure(0, weight=0)  # Title
        self.rowconfigure(1, weight=0)  # Experiment Name
        self.rowconfigure(2, weight=0)  # Description
        self.rowconfigure(3, weight=0)  # Target Stage
        self.rowconfigure(4, weight=0)  # Variable Under Test
        self.rowconfigure(5, weight=0)  # Value Specification
        self.rowconfigure(6, weight=0)  # Images per Variant
        self.rowconfigure(7, weight=0)  # Prompt Source
        self.rowconfigure(8, weight=0)  # Buttons
        self.rowconfigure(9, weight=0)  # Feedback
        self.rowconfigure(10, weight=1)  # Spacer

        self._build_ui()

    def _build_ui(self) -> None:
        """Build the experiment design UI."""
        # Title
        title_label = ttk.Label(self, text="Experiment Design", font=("TkDefaultFont", 12, "bold"))
        title_label.grid(row=0, column=0, pady=(0, 10), sticky="w")

        # Experiment Name
        ttk.Label(self, text="Experiment Name:").grid(row=1, column=0, sticky="w", pady=(0, 2))
        self.name_var = tk.StringVar(value="My Experiment")
        self.name_entry = ttk.Entry(self, textvariable=self.name_var)
        self.name_entry.grid(row=2, column=0, sticky="ew", pady=(0, 10))

        # Description
        ttk.Label(self, text="Description:").grid(row=3, column=0, sticky="w", pady=(0, 2))
        self.desc_var = tk.StringVar(value="")
        self.desc_entry = ttk.Entry(self, textvariable=self.desc_var)
        self.desc_entry.grid(row=4, column=0, sticky="ew", pady=(0, 10))

        # Target Stage
        ttk.Label(self, text="Target Stage:").grid(row=5, column=0, sticky="w", pady=(0, 2))
        self.stage_var = tk.StringVar(value="txt2img")
        self.stage_combo = ttk.Combobox(
            self,
            textvariable=self.stage_var,
            values=["txt2img", "img2img", "upscale"],
            state="readonly",
        )
        self.stage_combo.grid(row=6, column=0, sticky="ew", pady=(0, 10))

        # Variable Under Test
        ttk.Label(self, text="Variable Under Test:").grid(row=7, column=0, sticky="w", pady=(0, 2))
        self.variable_var = tk.StringVar(value="")
        self.variable_combo = ttk.Combobox(
            self,
            textvariable=self.variable_var,
            values=[
                "CFG Scale",
                "Steps",
                "Sampler",
                "Scheduler",
                "LoRA Strength",
                "Denoise Strength",
                "Upscale Factor",
            ],
            state="readonly",
        )
        self.variable_combo.grid(row=8, column=0, sticky="ew", pady=(0, 10))

        # Value Specification Frame
        value_frame = ttk.LabelFrame(self, text="Value Specification", padding=5)
        value_frame.grid(row=9, column=0, sticky="ew", pady=(0, 10))
        value_frame.columnconfigure(0, weight=1)
        value_frame.columnconfigure(1, weight=1)
        value_frame.columnconfigure(2, weight=1)

        # Numeric range inputs
        ttk.Label(value_frame, text="Start:").grid(row=0, column=0, sticky="w", pady=2)
        self.start_var = tk.DoubleVar(value=1.0)
        self.start_spin = tk.Spinbox(
            value_frame, from_=0.1, to=100.0, increment=0.1, textvariable=self.start_var
        )
        self.start_spin.grid(row=1, column=0, sticky="ew", padx=(0, 2))

        ttk.Label(value_frame, text="End:").grid(row=0, column=1, sticky="w", pady=2)
        self.end_var = tk.DoubleVar(value=10.0)
        self.end_spin = tk.Spinbox(
            value_frame, from_=0.1, to=100.0, increment=0.1, textvariable=self.end_var
        )
        self.end_spin.grid(row=1, column=1, sticky="ew", padx=2)

        ttk.Label(value_frame, text="Step:").grid(row=0, column=2, sticky="w", pady=2)
        self.step_var = tk.DoubleVar(value=1.0)
        self.step_spin = tk.Spinbox(
            value_frame, from_=0.1, to=10.0, increment=0.1, textvariable=self.step_var
        )
        self.step_spin.grid(row=1, column=2, sticky="ew", padx=(2, 0))

        # Images per Variant
        ttk.Label(self, text="Images per Variant:").grid(row=10, column=0, sticky="w", pady=(0, 2))
        self.images_var = tk.IntVar(value=1)
        self.images_spin = tk.Spinbox(self, from_=1, to=10, textvariable=self.images_var)
        self.images_spin.grid(row=11, column=0, sticky="ew", pady=(0, 10))

        # Prompt Source
        prompt_frame = ttk.LabelFrame(self, text="Prompt Source", padding=5)
        prompt_frame.grid(row=12, column=0, sticky="ew", pady=(0, 10))
        prompt_frame.columnconfigure(0, weight=1)

        self.prompt_source_var = tk.StringVar(value="workspace")
        ttk.Radiobutton(
            prompt_frame,
            text="Use current Prompt Workspace slot",
            variable=self.prompt_source_var,
            value="workspace",
        ).grid(row=0, column=0, sticky="w", pady=2)

        ttk.Radiobutton(
            prompt_frame,
            text="Custom prompt text:",
            variable=self.prompt_source_var,
            value="custom",
        ).grid(row=1, column=0, sticky="w", pady=2)

        self.custom_prompt_var = tk.StringVar(value="")
        self.custom_prompt_text = tk.Text(prompt_frame, height=3, wrap=tk.WORD)
        self.custom_prompt_text.grid(row=2, column=0, sticky="ew", pady=(2, 0))

        # Buttons
        button_frame = ttk.Frame(self)
        button_frame.grid(row=13, column=0, sticky="ew", pady=(0, 10))
        button_frame.columnconfigure(0, weight=1)
        button_frame.columnconfigure(1, weight=1)

        self.build_button = ttk.Button(
            button_frame, text="Build Preview Only", command=self._on_build_preview
        )
        self.build_button.grid(row=0, column=0, sticky="ew", padx=(0, 5))

        self.run_button = ttk.Button(
            button_frame, text="Run Experiment", command=self._on_run_experiment
        )
        self.run_button.grid(row=0, column=1, sticky="ew", padx=(5, 0))

        # Feedback
        self.feedback_var = tk.StringVar(value="")
        self.feedback_label = ttk.Label(self, textvariable=self.feedback_var, foreground="red")
        self.feedback_label.grid(row=14, column=0, sticky="w", pady=(0, 10))

    def _on_build_preview(self) -> None:
        """Handle build preview button click."""
        if not self.learning_controller:
            self.feedback_var.set("Learning controller not available")
            return

        # Collect form data
        experiment_data = {
            "name": self.name_var.get().strip(),
            "description": self.desc_var.get().strip(),
            "stage": self.stage_var.get(),
            "variable_under_test": self.variable_var.get(),
            "start_value": self.start_var.get(),
            "end_value": self.end_var.get(),
            "step_value": self.step_var.get(),
            "images_per_value": self.images_var.get(),
            "prompt_source": self.prompt_source_var.get(),
            "custom_prompt": self.custom_prompt_text.get("1.0", tk.END).strip()
            if self.prompt_source_var.get() == "custom"
            else "",
        }

        # Validate
        validation_error = self._validate_experiment_data(experiment_data)
        if validation_error:
            self.feedback_var.set(f"Validation Error: {validation_error}")
            return

        # Update controller
        try:
            self.learning_controller.update_experiment_design(experiment_data)

            # Build the learning plan
            if self.learning_controller.learning_state.current_experiment:
                self.learning_controller.build_plan(
                    self.learning_controller.learning_state.current_experiment
                )
                self.feedback_var.set("Experiment definition and plan built successfully")
            else:
                self.feedback_var.set("Experiment definition updated successfully")
        except Exception as e:
            self.feedback_var.set(f"Error updating experiment: {str(e)}")

    def _on_run_experiment(self) -> None:
        """Handle run experiment button click."""
        if not self.learning_controller:
            self.feedback_var.set("Learning controller not available")
            return

        try:
            self.learning_controller.run_plan()
            self.feedback_var.set("Experiment execution started")
        except Exception as e:
            self.feedback_var.set(f"Error running experiment: {str(e)}")

    def _validate_experiment_data(self, data: dict[str, Any]) -> str | None:
        """Validate experiment data and return error message if invalid."""
        if not data["name"]:
            return "Experiment name is required"

        if not data["variable_under_test"]:
            return "Variable under test must be selected"

        if data["start_value"] >= data["end_value"]:
            return "Start value must be less than end value"

        if data["step_value"] <= 0:
            return "Step value must be positive"

        if data["images_per_value"] < 1:
            return "Images per variant must be at least 1"

        if data["prompt_source"] == "custom" and not data["custom_prompt"]:
            return "Custom prompt text is required when using custom prompt source"

        return None
