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
        prompt_workspace_state: Any | None = None,
        *args: Any,
        **kwargs: Any,
    ) -> None:
        super().__init__(master, *args, **kwargs)
        self.learning_controller = learning_controller
        self.prompt_workspace_state = prompt_workspace_state

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
                "Model",  # PR-LEARN-021
                "VAE",    # PR-LEARN-021
                "LoRA Strength",
                "Denoise Strength",
                "Upscale Factor",
            ],
            state="readonly",
        )
        self.variable_combo.grid(row=8, column=0, sticky="ew", pady=(0, 10))
        
        # PR-LEARN-020: Bind variable selection to widget switcher
        self.variable_combo.bind("<<ComboboxSelected>>", self._on_variable_changed)

        # Value Specification Frame (numeric range)
        self.value_frame = ttk.LabelFrame(self, text="Value Specification", padding=5)
        self.value_frame.grid(row=9, column=0, sticky="ew", pady=(0, 10))
        self.value_frame.columnconfigure(0, weight=1)
        self.value_frame.columnconfigure(1, weight=1)
        self.value_frame.columnconfigure(2, weight=1)

        # Numeric range inputs
        ttk.Label(self.value_frame, text="Start:").grid(row=0, column=0, sticky="w", pady=2)
        self.start_var = tk.DoubleVar(value=1.0)
        self.start_spin = tk.Spinbox(
            self.value_frame, from_=0.1, to=100.0, increment=0.1, textvariable=self.start_var
        )
        self.start_spin.grid(row=1, column=0, sticky="ew", padx=(0, 2))

        ttk.Label(self.value_frame, text="End:").grid(row=0, column=1, sticky="w", pady=2)
        self.end_var = tk.DoubleVar(value=10.0)
        self.end_spin = tk.Spinbox(
            self.value_frame, from_=0.1, to=100.0, increment=0.1, textvariable=self.end_var
        )
        self.end_spin.grid(row=1, column=1, sticky="ew", padx=2)

        ttk.Label(self.value_frame, text="Step:").grid(row=0, column=2, sticky="w", pady=2)
        self.step_var = tk.DoubleVar(value=1.0)
        self.step_spin = tk.Spinbox(
            self.value_frame, from_=0.1, to=10.0, increment=0.1, textvariable=self.step_var
        )
        self.step_spin.grid(row=1, column=2, sticky="ew", padx=(2, 0))
        
        # PR-LEARN-020: Build checklist frame (hidden by default)
        self.checklist_frame = ttk.LabelFrame(self, text="Select Items to Test", padding=5)
        self.checklist_canvas = tk.Canvas(self.checklist_frame, height=150)
        self.checklist_scrollbar = ttk.Scrollbar(
            self.checklist_frame, orient="vertical", command=self.checklist_canvas.yview
        )
        self.checklist_inner_frame = ttk.Frame(self.checklist_canvas)
        self.checklist_canvas.configure(yscrollcommand=self.checklist_scrollbar.set)
        
        self.checklist_scrollbar.pack(side="right", fill="y")
        self.checklist_canvas.pack(side="left", fill="both", expand=True)
        self.checklist_canvas.create_window((0, 0), window=self.checklist_inner_frame, anchor="nw")
        self.checklist_inner_frame.bind(
            "<Configure>", lambda e: self.checklist_canvas.configure(scrollregion=self.checklist_canvas.bbox("all"))
        )
        
        # Initially hide checklist frame
        self.checklist_frame.grid_remove()
        
        # Store checkbox variables
        self.choice_vars: dict[str, tk.BooleanVar] = {}
        
        # PR-LEARN-022: Build LoRA composite frame (hidden by default)
        self.lora_frame = ttk.LabelFrame(self, text="LoRA Configuration", padding=5)
        self.lora_frame.columnconfigure(0, weight=1)
        
        # Initially hide
        self.lora_frame.grid_remove()

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
            command=self._on_prompt_source_changed,
        ).grid(row=0, column=0, sticky="w", pady=2)

        ttk.Radiobutton(
            prompt_frame,
            text="Custom prompt text:",
            variable=self.prompt_source_var,
            value="custom",
            command=self._on_prompt_source_changed,
        ).grid(row=1, column=0, sticky="w", pady=2)

        self.custom_prompt_var = tk.StringVar(value="")
        self.custom_prompt_text = tk.Text(prompt_frame, height=3, wrap=tk.WORD)
        self.custom_prompt_text.grid(row=2, column=0, sticky="ew", pady=(2, 0))
        
        # Populate text field with workspace prompt initially
        self._on_prompt_source_changed()

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

    def _on_prompt_source_changed(self) -> None:
        """Handle prompt source radio button changes.
        
        When 'workspace' is selected, populate the text field with the current
        workspace prompt so the user can see what will be used.
        """
        if self.prompt_source_var.get() == "workspace" and self.prompt_workspace_state:
            try:
                # Get current prompt from workspace
                current_prompt = self.prompt_workspace_state.get_current_prompt_text()
                if current_prompt:
                    # Update text field to show the workspace prompt
                    self.custom_prompt_text.delete("1.0", tk.END)
                    self.custom_prompt_text.insert("1.0", current_prompt)
                    # Make it read-only when workspace source is selected
                    self.custom_prompt_text.config(state="disabled")
                else:
                    # No prompt available
                    self.custom_prompt_text.delete("1.0", tk.END)
                    self.custom_prompt_text.insert("1.0", "(No prompt in workspace)")
                    self.custom_prompt_text.config(state="disabled")
            except Exception:
                # If there's an error accessing workspace state
                self.custom_prompt_text.delete("1.0", tk.END)
                self.custom_prompt_text.insert("1.0", "(Workspace prompt not available)")
                self.custom_prompt_text.config(state="disabled")
        else:
            # Custom mode - enable text field for editing
            self.custom_prompt_text.config(state="normal")

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
            # PR-LEARN-020: Include selected items for discrete/resource variables
            "selected_items": [
                choice for choice, var in self.choice_vars.items() if var.get()
            ] if hasattr(self, "choice_vars") else [],
            # PR-LEARN-022: LoRA metadata
            "lora_mode": self.lora_mode_var.get() if hasattr(self, "lora_mode_var") else "strength",
            "lora_name": self.lora_selector_var.get() if hasattr(self, "lora_selector_var") else None,
            "strength_start": self.lora_start_var.get() if hasattr(self, "lora_start_var") else 0.5,
            "strength_end": self.lora_end_var.get() if hasattr(self, "lora_end_var") else 1.5,
            "strength_step": self.lora_step_var.get() if hasattr(self, "lora_step_var") else 0.1,
            "comparison_mode": (self.lora_mode_var.get() == "comparison") if hasattr(self, "lora_mode_var") else False,
            "fixed_strength": self.lora_fixed_strength_var.get() if hasattr(self, "lora_fixed_strength_var") else 1.0,
            "selected_loras": [
                lora for lora, var in self.lora_choice_vars.items() if var.get()
            ] if hasattr(self, "lora_choice_vars") else [],
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
        """Validate experiment data and return error message if invalid.
        
        PR-LEARN-020: Enhanced with discrete variable validation.
        """
        from src.learning.variable_metadata import get_variable_metadata
        
        if not data["name"]:
            return "Experiment name is required"

        if not data["variable_under_test"]:
            return "Variable under test must be selected"
        
        # Get metadata for variable
        meta = get_variable_metadata(data["variable_under_test"])
        
        if meta and meta.value_type in ["discrete", "resource"]:
            # Discrete/resource variable - validate selection
            selected = data.get("selected_items", [])
            if not selected:
                return f"At least one {meta.display_name} must be selected"
        elif meta and meta.value_type == "composite":
            # PR-LEARN-022: Composite LoRA validation
            comparison_mode = data.get("comparison_mode", False)
            
            if comparison_mode:
                # Mode 2: Comparison - require at least one LoRA selected
                selected_loras = data.get("selected_loras", [])
                if not selected_loras:
                    return "At least one LoRA must be selected for comparison mode"
            else:
                # Mode 1: Strength sweep - require LoRA selection
                lora_name = data.get("lora_name")
                if not lora_name:
                    return "LoRA must be selected for strength sweep mode"
                
                # Validate strength range
                start = data.get("strength_start", 0.0)
                end = data.get("strength_end", 1.0)
                step = data.get("strength_step", 0.1)
                
                if start >= end:
                    return "Start strength must be less than end strength"
                
                if step <= 0:
                    return "Strength step must be positive"
        else:
            # Numeric variable - validate range
            if data["start_value"] >= data["end_value"]:
                return "Start value must be less than end value"

            if data["step_value"] <= 0:
                return "Step value must be positive"

        if data["images_per_value"] < 1:
            return "Images per variant must be at least 1"

        if data["prompt_source"] == "custom" and not data["custom_prompt"]:
            return "Custom prompt text is required when using custom prompt source"

        return None

    def _on_variable_changed(self, event=None) -> None:
        """Handle variable selection change - show appropriate UI widget.
        
        PR-LEARN-020: Switches between range widget and checklist based on variable type.
        """
        from src.learning.variable_metadata import get_variable_metadata
        
        variable_name = self.variable_var.get()
        if not variable_name:
            return
        
        # Look up metadata
        meta = get_variable_metadata(variable_name)
        if not meta:
            self._show_range_widget()
            return
        
        # Show appropriate widget based on ui_component
        if meta.ui_component == "range":
            self._show_range_widget()
        elif meta.ui_component == "checklist":
            self._show_checklist_widget(meta)
        elif meta.ui_component == "lora_composite":  # PR-LEARN-022
            self._show_lora_composite_widget(meta)
        else:
            self._show_range_widget()
    
    def _show_range_widget(self) -> None:
        """Show numeric range widget (start/stop/step)."""
        # Show value frame
        self.value_frame.grid(row=9, column=0, sticky="ew", pady=(0, 10))
        
        # Hide checklist frame
        self.checklist_frame.grid_remove()
    
    def _show_checklist_widget(self, meta) -> None:
        """Show checklist widget for discrete choices.
        
        PR-LEARN-020: Displays checkboxes for discrete/resource variables.
        """
        # Hide value frame
        self.value_frame.grid_remove()
        
        # Show checklist frame at row 9
        self.checklist_frame.grid(row=9, column=0, sticky="ew", pady=(0, 10))
        
        # Update checklist label
        self.checklist_frame.config(text=f"Select {meta.display_name} to Test")
        
        # Populate checklist with choices
        self._populate_checklist(meta)
    
    def _populate_checklist(self, meta) -> None:
        """Populate checklist with choices from resources.
        
        PR-LEARN-020: Gets available choices from app_state resources.
        PR-LEARN-021: Added search/filter support.
        """
        # Clear existing checkboxes
        for widget in self.checklist_inner_frame.winfo_children():
            widget.destroy()
        
        self.choice_vars.clear()
        
        # Get available choices from app_state
        choices = []
        if meta.resource_key and self.learning_controller:
            app_controller = getattr(self.learning_controller, "app_controller", None)
            if app_controller and hasattr(app_controller, "_app_state"):
                app_state = app_controller._app_state
                if hasattr(app_state, "resources"):
                    choices = app_state.resources.get(meta.resource_key, [])
        
        if not choices:
            # No choices available
            ttk.Label(
                self.checklist_inner_frame,
                text=f"No {meta.display_name} available in WebUI",
                foreground="red"
            ).pack(anchor="w", pady=2)
            return
        
        # PR-LEARN-021: Add search/filter box for large resource lists
        if meta.constraints.get("supports_filter", False):
            search_frame = ttk.Frame(self.checklist_inner_frame)
            search_frame.pack(fill="x", pady=(0, 10))
            
            ttk.Label(search_frame, text="Search:").pack(side="left", padx=(0, 5))
            
            self.search_var = tk.StringVar()
            search_entry = ttk.Entry(search_frame, textvariable=self.search_var)
            search_entry.pack(side="left", fill="x", expand=True, padx=(0, 5))
            
            # Bind search to filter function
            self.search_var.trace_add("write", lambda *args: self._filter_checklist_items(meta))
            
            # Clear button
            clear_btn = ttk.Button(
                search_frame,
                text="Clear",
                width=8,
                command=lambda: self.search_var.set("")
            )
            clear_btn.pack(side="left", padx=(5, 0))
        
        # Add Select All / Clear All buttons
        button_frame = ttk.Frame(self.checklist_inner_frame)
        button_frame.pack(fill="x", pady=(0, 5))
        
        ttk.Button(
            button_frame,
            text="Select All",
            command=lambda: self._select_all_choices(True)
        ).pack(side="left", padx=(0, 5))
        
        ttk.Button(
            button_frame,
            text="Clear All",
            command=lambda: self._select_all_choices(False)
        ).pack(side="left")
        
        # Container for checkboxes (for filtering)
        self.checkbox_container = ttk.Frame(self.checklist_inner_frame)
        self.checkbox_container.pack(fill="both", expand=True)
        
        # Create checkboxes for each choice
        for choice in choices:
            var = tk.BooleanVar(value=False)
            cb = ttk.Checkbutton(self.checkbox_container, text=choice, variable=var)
            cb.pack(anchor="w", pady=2)
            self.choice_vars[choice] = var
            
            # Bind checkbox changes to update count
            var.trace_add("write", lambda *args: self._update_choice_count())
        
        # Add count label
        self.choice_count_var = tk.StringVar(value="0 items selected")
        count_label = ttk.Label(
            self.checklist_inner_frame,
            textvariable=self.choice_count_var,
            foreground="blue"
        )
        count_label.pack(anchor="w", pady=(5, 0))
    
    def _select_all_choices(self, selected: bool) -> None:
        """Select or deselect all checkboxes."""
        for var in self.choice_vars.values():
            var.set(selected)
    
    def _update_choice_count(self) -> None:
        """Update the count label showing selected items."""
        count = sum(1 for var in self.choice_vars.values() if var.get())
        self.choice_count_var.set(f"{count} items selected")

    def _filter_checklist_items(self, meta) -> None:
        """Filter checklist items based on search text.
        
        PR-LEARN-021: Real-time filtering of resource lists.
        """
        if not hasattr(self, "search_var") or not hasattr(self, "checkbox_container"):
            return
        
        search_text = self.search_var.get().lower()
        
        # Show/hide checkboxes based on search
        for widget in self.checkbox_container.winfo_children():
            if isinstance(widget, ttk.Checkbutton):
                text = widget.cget("text").lower()
                if not search_text or search_text in text:
                    widget.pack(anchor="w", pady=2)
                else:
                    widget.pack_forget()
        
        # Update count
        self._update_choice_count()

    def _show_lora_composite_widget(self, meta) -> None:
        """Show LoRA composite widget (LoRA selector + strength range OR LoRA comparison).
        
        PR-LEARN-022: Supports two modes:
        - Mode 1: Single LoRA with strength sweep
        - Mode 2: Multiple LoRAs at fixed strength
        """
        # Hide other widgets
        try:
            self.value_frame.grid_remove()
        except Exception:
            pass
        self.checklist_frame.grid_remove()
        
        # Show LoRA frame at row 9
        self.lora_frame.grid(row=9, column=0, sticky="ew", pady=(0, 10))
        
        # Clear existing content
        for widget in self.lora_frame.winfo_children():
            widget.destroy()
        
        # Mode selector
        mode_frame = ttk.Frame(self.lora_frame)
        mode_frame.pack(fill="x", pady=(0, 10))
        
        ttk.Label(mode_frame, text="Test Mode:", font=("TkDefaultFont", 10, "bold")).pack(anchor="w", pady=(0, 5))
        
        self.lora_mode_var = tk.StringVar(value="strength")
        
        strength_mode_rb = ttk.Radiobutton(
            mode_frame,
            text="Test single LoRA at multiple strengths",
            variable=self.lora_mode_var,
            value="strength",
            command=self._on_lora_mode_changed
        )
        strength_mode_rb.pack(anchor="w", pady=2)
        
        comparison_mode_rb = ttk.Radiobutton(
            mode_frame,
            text="Compare different LoRAs at fixed strength",
            variable=self.lora_mode_var,
            value="comparison",
            command=self._on_lora_mode_changed
        )
        comparison_mode_rb.pack(anchor="w", pady=2)
        
        # Content frame (dynamic based on mode)
        self.lora_content_frame = ttk.Frame(self.lora_frame)
        self.lora_content_frame.pack(fill="both", expand=True)
        
        # Build initial content
        self._build_lora_mode_content()

    def _on_lora_mode_changed(self) -> None:
        """Handle LoRA mode selection change."""
        self._build_lora_mode_content()

    def _build_lora_mode_content(self) -> None:
        """Build content based on selected LoRA mode.
        
        PR-LEARN-022: Switches between strength sweep UI and LoRA comparison UI.
        """
        # Clear existing content
        for widget in self.lora_content_frame.winfo_children():
            widget.destroy()
        
        mode = self.lora_mode_var.get() if hasattr(self, "lora_mode_var") else "strength"
        
        if mode == "strength":
            self._build_strength_sweep_ui()
        else:
            self._build_lora_comparison_ui()

    def _build_strength_sweep_ui(self) -> None:
        """Build UI for single LoRA strength sweep.
        
        Shows: LoRA selector + strength range (start/stop/step)
        """
        # Get available LoRAs from controller
        available_loras = []
        if hasattr(self, 'learning_controller') and self.learning_controller:
            try:
                loras = self.learning_controller._get_current_loras()
                available_loras = [l["name"] for l in loras]
            except Exception:
                pass
        
        # LoRA selector
        lora_select_frame = ttk.Frame(self.lora_content_frame)
        lora_select_frame.pack(fill="x", pady=(0, 10))
        
        ttk.Label(lora_select_frame, text="Select LoRA to test:").pack(anchor="w", pady=(0, 2))
        
        self.lora_selector_var = tk.StringVar()
        if available_loras:
            self.lora_selector_var.set(available_loras[0])
        
        lora_combo = ttk.Combobox(
            lora_select_frame,
            textvariable=self.lora_selector_var,
            values=available_loras,
            state="readonly"
        )
        lora_combo.pack(fill="x")
        
        if not available_loras:
            ttk.Label(
                lora_select_frame,
                text="No enabled LoRAs in stage card",
                foreground="red"
            ).pack(anchor="w", pady=(2, 0))
        
        # Strength range
        range_frame = ttk.LabelFrame(self.lora_content_frame, text="Strength Range", padding=5)
        range_frame.pack(fill="x")
        range_frame.columnconfigure(0, weight=1)
        range_frame.columnconfigure(1, weight=1)
        range_frame.columnconfigure(2, weight=1)
        
        # Start
        ttk.Label(range_frame, text="Start:").grid(row=0, column=0, sticky="w", pady=2)
        self.lora_start_var = tk.DoubleVar(value=0.5)
        start_spin = tk.Spinbox(range_frame, from_=0.0, to=2.0, increment=0.1, textvariable=self.lora_start_var)
        start_spin.grid(row=1, column=0, sticky="ew", padx=(0, 2))
        
        # End
        ttk.Label(range_frame, text="End:").grid(row=0, column=1, sticky="w", pady=2)
        self.lora_end_var = tk.DoubleVar(value=1.5)
        end_spin = tk.Spinbox(range_frame, from_=0.0, to=2.0, increment=0.1, textvariable=self.lora_end_var)
        end_spin.grid(row=1, column=1, sticky="ew", padx=2)
        
        # Step
        ttk.Label(range_frame, text="Step:").grid(row=0, column=2, sticky="w", pady=2)
        self.lora_step_var = tk.DoubleVar(value=0.1)
        step_spin = tk.Spinbox(range_frame, from_=0.05, to=1.0, increment=0.05, textvariable=self.lora_step_var)
        step_spin.grid(row=1, column=2, sticky="ew", padx=(2, 0))
        
        # Variant count estimate
        def update_variant_count(*args):
            try:
                start = self.lora_start_var.get()
                end = self.lora_end_var.get()
                step = self.lora_step_var.get()
                if step > 0 and end >= start:
                    count = int((end - start) / step) + 1
                    count_label.config(text=f"{count} variants will be generated")
                else:
                    count_label.config(text="Invalid range")
            except Exception:
                count_label.config(text="")
        
        self.lora_start_var.trace_add("write", update_variant_count)
        self.lora_end_var.trace_add("write", update_variant_count)
        self.lora_step_var.trace_add("write", update_variant_count)
        
        count_label = ttk.Label(self.lora_content_frame, text="", foreground="blue")
        count_label.pack(anchor="w", pady=(5, 0))
        update_variant_count()

    def _build_lora_comparison_ui(self) -> None:
        """Build UI for comparing different LoRAs at fixed strength.
        
        Shows: LoRA checklist + fixed strength input
        """
        # Get available LoRAs
        available_loras = []
        if hasattr(self, 'learning_controller') and self.learning_controller:
            try:
                loras = self.learning_controller._get_current_loras()
                available_loras = [l["name"] for l in loras]
            except Exception:
                pass
        
        # Fixed strength input
        strength_frame = ttk.Frame(self.lora_content_frame)
        strength_frame.pack(fill="x", pady=(0, 10))
        
        ttk.Label(strength_frame, text="Fixed strength for all LoRAs:").pack(side="left", padx=(0, 5))
        
        self.lora_fixed_strength_var = tk.DoubleVar(value=1.0)
        strength_spin = tk.Spinbox(
            strength_frame,
            from_=0.0,
            to=2.0,
            increment=0.1,
            textvariable=self.lora_fixed_strength_var,
            width=10
        )
        strength_spin.pack(side="left")
        
        # LoRA checklist
        checklist_label = ttk.Label(self.lora_content_frame, text="Select LoRAs to compare:")
        checklist_label.pack(anchor="w", pady=(0, 5))
        
        # Scrollable checklist
        checklist_canvas = tk.Canvas(self.lora_content_frame, height=150)
        checklist_scrollbar = ttk.Scrollbar(self.lora_content_frame, orient="vertical", command=checklist_canvas.yview)
        checklist_inner = ttk.Frame(checklist_canvas)
        checklist_canvas.configure(yscrollcommand=checklist_scrollbar.set)
        
        checklist_scrollbar.pack(side="right", fill="y")
        checklist_canvas.pack(side="left", fill="both", expand=True)
        checklist_canvas.create_window((0, 0), window=checklist_inner, anchor="nw")
        checklist_inner.bind("<Configure>", lambda e: checklist_canvas.configure(scrollregion=checklist_canvas.bbox("all")))
        
        # Create checkboxes
        self.lora_choice_vars = {}
        
        if not available_loras:
            ttk.Label(
                checklist_inner,
                text="No enabled LoRAs in stage card",
                foreground="red"
            ).pack(anchor="w", pady=2)
        else:
            # Select All / Clear All
            button_frame = ttk.Frame(checklist_inner)
            button_frame.pack(fill="x", pady=(0, 5))
            
            ttk.Button(
                button_frame,
                text="Select All",
                command=lambda: self._select_all_lora_choices(True)
            ).pack(side="left", padx=(0, 5))
            
            ttk.Button(
                button_frame,
                text="Clear All",
                command=lambda: self._select_all_lora_choices(False)
            ).pack(side="left")
            
            # Checkboxes
            for lora in available_loras:
                var = tk.BooleanVar(value=False)
                cb = ttk.Checkbutton(checklist_inner, text=lora, variable=var)
                cb.pack(anchor="w", pady=2)
                self.lora_choice_vars[lora] = var
            
            # Count label
            self.lora_count_var = tk.StringVar(value="0 LoRAs selected")
            count_label = ttk.Label(checklist_inner, textvariable=self.lora_count_var, foreground="blue")
            count_label.pack(anchor="w", pady=(5, 0))
            
            # Bind checkbox changes
            for var in self.lora_choice_vars.values():
                var.trace_add("write", lambda *args: self._update_lora_choice_count())

    def _select_all_lora_choices(self, selected: bool) -> None:
        """Select or deselect all LoRA checkboxes."""
        for var in self.lora_choice_vars.values():
            var.set(selected)

    def _update_lora_choice_count(self) -> None:
        """Update LoRA selection count."""
        count = sum(1 for var in self.lora_choice_vars.values() if var.get())
        self.lora_count_var.set(f"{count} LoRAs selected")
