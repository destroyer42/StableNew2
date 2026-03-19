# PR-LEARN-020: Discrete Variable Support (Sampler, Scheduler)

**Related Discovery**: D-LEARN-002  
**Architecture Version**: v2.6  
**PR Date**: 2026-01-10  
**Dependencies**: PR-LEARN-010 (Direct NJR Construction)  
**Sequence**: Phase 1 of 3 (PR-LEARN-020 → PR-LEARN-021 → PR-LEARN-022)

---

# EXECUTOR ACKNOWLEDGEMENT & COMPLIANCE BLOCK (MANDATORY)

## READ FIRST — EXECUTION CONTRACT ACKNOWLEDGEMENT

You are acting as an **Executor** for the StableNew v2.6 codebase.

By proceeding, you **explicitly acknowledge** that:

1. You have read and understand the attached document  
   **`StableNew_v2.6_Canonical_Execution_Contract.md`** *(via .github/copilot-instructions.md)*

2. You agree that this document is the **single authoritative source of truth** for:
   - Architecture
   - NJR-only execution
   - Variable metadata system design
   - Learning pipeline behavior

3. This PR **MUST**:
   - Create variable metadata registry for numeric and discrete types
   - Implement dynamic UI widget switching (range vs checklist)
   - Support sampler and scheduler discrete variable testing
   - Maintain backward compatibility with numeric variables

---

## ABSOLUTE EXECUTION RULES (NON‑NEGOTIABLE)

### 1. Scope Completion
- You MUST implement **100% of the PR scope**
- You MUST create **every file listed**
- You MUST modify **every file listed**
- Partial implementation is **explicitly forbidden**

### 2. Variable Type System Enforcement
You MUST:
- Create metadata registry with numeric and discrete type definitions
- Implement metadata-driven value generation
- Support checklist UI for discrete variables
- Apply discrete overrides to NJR config via config_path

### 3. Proof Is Mandatory
For **every MUST**, you MUST provide:
- Full `git diff`
- pytest commands **with captured output**
- Grep output for metadata usage
- Exact file + line references

### 4. Tests Are Not Optional
You MUST:
- Run all tests specified in TEST PLAN
- Show command + full output
- Fix failures before proceeding

---

## ACKNOWLEDGEMENT STATEMENT (REQUIRED)

By continuing execution, you acknowledge:

> "I will create the variable metadata registry, implement dynamic UI widgets for discrete  
> variables, extend LearningController value generation and override logic, and ensure full  
> backward compatibility with numeric variables. I will provide verifiable proof of all changes."

---

# PR METADATA

## PR ID
`PR-LEARN-020-Discrete-Variable-Support`

## Related Canonical Sections
- **D-LEARN-002 §4.C**: Hybrid Metadata + Inline Logic approach
- **D-LEARN-002 §6.1**: Phase 1 implementation roadmap
- **Architecture v2.6 §3.2**: NJR-only execution
- **PR-LEARN-010**: Direct NJR construction for learning

---

# INTENT (MANDATORY)

## What This PR Does

This PR implements **Phase 1** of the variable type extension, adding support for **discrete choice variables** (Sampler, Scheduler) in the learning pipeline. It creates a metadata registry to describe variable characteristics and extends the learning controller to handle non-numeric variable types.

**Key Capabilities Added**:
1. Variable metadata registry (`VariableMetadata` dataclass + `LEARNING_VARIABLES` dict)
2. Metadata-driven value generation (numeric ranges + discrete choices)
3. Dynamic UI widget switching (range spinboxes vs checklist)
4. Sampler/Scheduler discrete variable support
5. Config path-based override application

**Backward Compatibility**: Existing numeric variable experiments continue to work unchanged.

## What This PR Does NOT Do

- Does NOT implement resource variables (Model, VAE) - deferred to PR-LEARN-021
- Does NOT implement composite LoRA variables - deferred to PR-LEARN-022
- Does NOT add multi-variable experiments - deferred to Phase 4
- Does NOT modify PromptPack or stage card core logic

---

# SCOPE OF CHANGE (EXPLICIT)

## Files TO BE CREATED (REQUIRED)

### `src/learning/variable_metadata.py`
**Purpose**: Variable metadata registry defining testable variables and their characteristics

**Content Structure**:
```python
from dataclasses import dataclass, field
from typing import Literal

@dataclass
class VariableMetadata:
    """Metadata describing a testable variable."""
    name: str                    # Internal name: "cfg_scale"
    display_name: str            # UI display: "CFG Scale"
    value_type: Literal["numeric", "discrete", "resource", "composite"]
    config_path: str             # Where to apply: "txt2img.cfg_scale"
    ui_component: Literal["range", "checklist", "lora_composite"]
    resource_key: str | None = None  # For discrete/resource types: "samplers"
    constraints: dict[str, any] = field(default_factory=dict)  # Type-specific constraints

LEARNING_VARIABLES: dict[str, VariableMetadata] = {
    "cfg_scale": VariableMetadata(...),
    "steps": VariableMetadata(...),
    "sampler": VariableMetadata(...),
    "scheduler": VariableMetadata(...),
    "denoise_strength": VariableMetadata(...),
    "upscale_factor": VariableMetadata(...),
}

def get_variable_metadata(variable_display_name: str) -> VariableMetadata | None:
    """Look up metadata by display name."""
    ...

def get_all_variable_names() -> list[str]:
    """Get list of all variable display names for UI dropdown."""
    ...
```

**Specific Variables to Define**:
1. **cfg_scale**: numeric, range UI, txt2img.cfg_scale, constraints: {min: 1.0, max: 30.0, step: 0.5}
2. **steps**: numeric, range UI, txt2img.steps, constraints: {min: 1, max: 150, step: 1}
3. **sampler**: discrete, checklist UI, txt2img.sampler_name, resource_key: "samplers"
4. **scheduler**: discrete, checklist UI, txt2img.scheduler, resource_key: "schedulers"
5. **denoise_strength**: numeric, range UI, txt2img.denoising_strength, constraints: {min: 0.0, max: 1.0, step: 0.05}
6. **upscale_factor**: numeric, range UI, upscale.upscale_factor, constraints: {min: 1.0, max: 4.0, step: 0.25}

---

## Files TO BE MODIFIED (REQUIRED)

### `src/gui/controllers/learning_controller.py`
**Purpose**: Extend value generation and override application to use metadata

**Specific Changes**:

#### Change 1: Add `_generate_variant_values()` method
**Location**: After `_generate_values_from_range()` method (~line 100)

**Implementation**:
```python
def _generate_variant_values(self, experiment: LearningExperiment) -> list[Any]:
    """Generate values using variable metadata.
    
    PR-LEARN-020: Uses metadata registry to determine how to generate values
    based on variable type (numeric range vs discrete choice).
    """
    import logging
    from src.learning.variable_metadata import get_variable_metadata
    
    logger = logging.getLogger(__name__)
    
    meta = get_variable_metadata(experiment.variable_under_test)
    if not meta:
        raise ValueError(f"Unknown variable: {experiment.variable_under_test}")
    
    logger.info(f"[LearningController] Generating values for {meta.display_name} (type: {meta.value_type})")
    
    # Dispatch based on value_type
    if meta.value_type == "numeric":
        start = experiment.metadata.get("start_value", meta.constraints.get("min", 1.0))
        end = experiment.metadata.get("end_value", meta.constraints.get("max", 10.0))
        step = experiment.metadata.get("step_value", meta.constraints.get("step", 1.0))
        
        values = self._generate_values_from_range(start, end, step)
        logger.info(f"[LearningController]   Generated {len(values)} numeric values: {values}")
        return values
    
    elif meta.value_type == "discrete":
        # Get selected items from experiment metadata
        selected = experiment.metadata.get("selected_items", [])
        
        # If no selection, get all available from resources
        if not selected and self.app_controller:
            try:
                resources = self.app_controller._app_state.resources
                available = resources.get(meta.resource_key, [])
                logger.warning(f"[LearningController]   No items selected, using all {len(available)} available {meta.resource_key}")
                selected = available
            except Exception as exc:
                logger.error(f"[LearningController]   Failed to get resources: {exc}")
                selected = []
        
        logger.info(f"[LearningController]   Generated {len(selected)} discrete values: {selected}")
        return selected
    
    else:
        raise ValueError(f"Unsupported variable type: {meta.value_type} for {meta.display_name}")
```

**Verification**:
- Method handles both numeric and discrete types
- Logs value generation for debugging
- Falls back to available resources if no selection
- Raises clear error for unsupported types

---

#### Change 2: Update `update_experiment_design()` to use metadata
**Location**: Lines 70-95 (current `update_experiment_design` method)

**OLD CODE**:
```python
def update_experiment_design(self, experiment_data: dict[str, Any]) -> None:
    """Update the current experiment design from form data."""
    # ...
    # Create LearningExperiment from form data
    experiment = LearningExperiment(
        name=experiment_data.get("name", ""),
        description=experiment_data.get("description", ""),
        baseline_config={},
        prompt_text=prompt_text,
        stage=experiment_data.get("stage", "txt2img"),
        variable_under_test=experiment_data.get("variable_under_test", ""),
        values=self._generate_values_from_range(
            experiment_data.get("start_value", 1.0),
            experiment_data.get("end_value", 10.0),
            experiment_data.get("step_value", 1.0),
        ),
        images_per_value=experiment_data.get("images_per_value", 1),
    )
```

**NEW CODE**:
```python
def update_experiment_design(self, experiment_data: dict[str, Any]) -> None:
    """Update the current experiment design from form data.
    
    PR-LEARN-020: Enhanced to store metadata and use _generate_variant_values().
    """
    # Determine prompt text based on prompt_source
    prompt_text = ""
    prompt_source = experiment_data.get("prompt_source", "custom")
    
    if prompt_source == "custom":
        prompt_text = experiment_data.get("custom_prompt", "")
    elif prompt_source == "current" and self.prompt_workspace_state:
        prompt_text = self.prompt_workspace_state.get_current_prompt_text() or ""
    
    # Store metadata for value generation
    metadata = {
        "start_value": experiment_data.get("start_value", 1.0),
        "end_value": experiment_data.get("end_value", 10.0),
        "step_value": experiment_data.get("step_value", 1.0),
        "selected_items": experiment_data.get("selected_items", []),  # PR-LEARN-020: Discrete choices
    }
    
    # Create LearningExperiment from form data
    experiment = LearningExperiment(
        name=experiment_data.get("name", ""),
        description=experiment_data.get("description", ""),
        baseline_config={},
        prompt_text=prompt_text,
        stage=experiment_data.get("stage", "txt2img"),
        variable_under_test=experiment_data.get("variable_under_test", ""),
        values=[],  # Will be populated by build_plan()
        images_per_value=experiment_data.get("images_per_value", 1),
    )
    
    # Store metadata in experiment
    experiment.metadata = metadata  # PR-LEARN-020: Store for later value generation
    
    # Store in state
    self.learning_state.current_experiment = experiment
```

**Verification**:
- Metadata dict includes numeric range params + selected_items
- Values list initially empty (populated in build_plan)
- Experiment.metadata field used to store value spec

---

#### Change 3: Update `build_plan()` to use new value generation
**Location**: Lines 110-140 (current `build_plan` method)

**OLD CODE**:
```python
def build_plan(self, experiment: LearningExperiment) -> None:
    """Build a learning plan from experiment definition."""
    from src.gui.learning_state import LearningVariant

    # Store the current experiment
    self.learning_state.current_experiment = experiment

    # Load existing ratings for this experiment
    self.load_existing_ratings()

    # Clear any existing plan
    self.learning_state.plan = []

    # Generate variants for each value in the experiment
    for value in experiment.values:
        variant = LearningVariant(...)
        self.learning_state.plan.append(variant)
```

**NEW CODE**:
```python
def build_plan(self, experiment: LearningExperiment) -> None:
    """Build a learning plan from experiment definition.
    
    PR-LEARN-020: Uses _generate_variant_values() for metadata-driven value generation.
    """
    import logging
    from src.gui.learning_state import LearningVariant
    
    logger = logging.getLogger(__name__)
    
    # Store the current experiment
    self.learning_state.current_experiment = experiment

    # Load existing ratings for this experiment
    self.load_existing_ratings()

    # Clear any existing plan
    self.learning_state.plan = []

    # PR-LEARN-020: Generate values using metadata system
    try:
        values = self._generate_variant_values(experiment)
        logger.info(f"[LearningController] Generated {len(values)} variants for {experiment.variable_under_test}")
    except Exception as exc:
        logger.error(f"[LearningController] Failed to generate values: {exc}")
        values = []
    
    # Update experiment values
    experiment.values = values

    # Generate variants for each value
    for value in values:
        variant = LearningVariant(
            experiment_id=experiment.name,
            param_value=value,
            status="pending",
            planned_images=experiment.images_per_value,
            completed_images=0,
            image_refs=[],
        )
        self.learning_state.plan.append(variant)

    # Update the plan table if it exists
    if self._plan_table:
        self._update_plan_table()
```

**Verification**:
- Calls `_generate_variant_values()` instead of using `experiment.values`
- Updates `experiment.values` with generated values
- Comprehensive error handling and logging

---

#### Change 4: Add `_apply_variant_override_with_metadata()` method
**Location**: After `_apply_overrides_to_config()` method (~line 720)

**Implementation**:
```python
def _apply_variant_override_with_metadata(
    self,
    config: dict[str, Any],
    value: Any,
    experiment: LearningExperiment
) -> None:
    """Apply variant override using metadata config_path.
    
    PR-LEARN-020: Metadata-driven override application replaces hardcoded if/elif chains.
    Uses config_path from metadata to determine where to apply the override.
    """
    import logging
    from src.learning.variable_metadata import get_variable_metadata
    
    logger = logging.getLogger(__name__)
    
    meta = get_variable_metadata(experiment.variable_under_test)
    if not meta:
        logger.error(f"[LearningController] No metadata for variable: {experiment.variable_under_test}")
        return
    
    # Parse config_path: "txt2img.cfg_scale" → ["txt2img", "cfg_scale"]
    keys = meta.config_path.split(".")
    
    # Navigate to target location in config dict
    target = config
    for key in keys[:-1]:
        if key not in target:
            target[key] = {}
        target = target[key]
    
    # Apply value
    final_key = keys[-1]
    target[final_key] = value
    
    logger.info(f"[LearningController] Applied override: {meta.config_path} = {value}")
```

**Verification**:
- Parses config_path dynamically
- Creates intermediate dicts if missing
- Logs override application
- Works for both numeric and discrete types

---

#### Change 5: Update `_build_variant_overrides()` to call new method
**Location**: Lines ~680-700 (current `_build_variant_overrides` method)

**Modify to call `_apply_variant_override_with_metadata()` instead of hardcoded logic**

---

### `src/gui/learning_state.py`
**Purpose**: Add metadata field to LearningExperiment

**Specific Changes**:

**Location**: Lines 8-20 (LearningExperiment dataclass)

**OLD CODE**:
```python
@dataclass
class LearningExperiment:
    """Represents a learning experiment definition."""

    name: str = ""
    description: str = ""
    baseline_config: dict[str, Any] = field(default_factory=dict)
    prompt_text: str = ""
    stage: str = "txt2img"
    variable_under_test: str = ""
    values: list[Any] = field(default_factory=list)
    images_per_value: int = 1
```

**NEW CODE**:
```python
@dataclass
class LearningExperiment:
    """Represents a learning experiment definition.
    
    PR-LEARN-020: Added metadata field to store value specification.
    """

    name: str = ""
    description: str = ""
    baseline_config: dict[str, Any] = field(default_factory=dict)
    prompt_text: str = ""
    stage: str = "txt2img"
    variable_under_test: str = ""
    values: list[Any] = field(default_factory=list)
    images_per_value: int = 1
    metadata: dict[str, Any] = field(default_factory=dict)  # PR-LEARN-020: Value spec storage
```

---

### `src/gui/views/experiment_design_panel.py`
**Purpose**: Add dynamic UI widget switching for discrete variables

**Specific Changes**:

#### Change 1: Add checklist frame initialization
**Location**: After `_build_ui()` method, in `__init__` (~line 40)

**Add after existing value_frame creation**:
```python
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
```

#### Change 2: Bind variable combo selection
**Location**: After variable_combo creation (~line 87)

**Add binding**:
```python
# PR-LEARN-020: Bind variable selection to widget switcher
self.variable_combo.bind("<<ComboboxSelected>>", self._on_variable_changed)
```

#### Change 3: Add `_on_variable_changed()` method
**Location**: After `_on_prompt_source_changed()` method (~line 180)

**Implementation**:
```python
def _on_variable_changed(self, event=None) -> None:
    """Handle variable selection change - show appropriate UI widget.
    
    PR-LEARN-020: Dynamically switches between range and checklist UI based
    on variable metadata.
    """
    from src.learning.variable_metadata import get_variable_metadata
    
    variable_name = self.variable_var.get()
    if not variable_name:
        return
    
    # Get metadata for selected variable
    meta = get_variable_metadata(variable_name)
    if not meta:
        # Default to range for unknown variables
        self._show_range_widget()
        return
    
    # Show appropriate widget based on ui_component
    if meta.ui_component == "range":
        self._show_range_widget()
    elif meta.ui_component == "checklist":
        self._show_checklist_widget(meta)
    else:
        self._show_range_widget()  # Fallback

def _show_range_widget(self) -> None:
    """Show numeric range widget (start/stop/step)."""
    # Show value_frame at row 9
    try:
        self.value_frame = self.nametowidget(".!experimentdesignpanel.!labelframe")
        self.value_frame.grid(row=9, column=0, sticky="ew", pady=(0, 10))
    except Exception:
        pass
    
    # Hide checklist frame
    self.checklist_frame.grid_remove()

def _show_checklist_widget(self, meta) -> None:
    """Show checklist widget for discrete choices.
    
    Args:
        meta: VariableMetadata containing resource_key
    """
    # Hide range widget
    try:
        self.value_frame = self.nametowidget(".!experimentdesignpanel.!labelframe")
        self.value_frame.grid_remove()
    except Exception:
        pass
    
    # Show checklist frame at row 9
    self.checklist_frame.grid(row=9, column=0, sticky="ew", pady=(0, 10))
    
    # Populate checklist with available choices
    self._populate_checklist(meta)

def _populate_checklist(self, meta) -> None:
    """Populate checklist with choices from resources.
    
    Args:
        meta: VariableMetadata containing resource_key
    """
    # Clear existing checkboxes
    for widget in self.checklist_inner_frame.winfo_children():
        widget.destroy()
    self.choice_vars.clear()
    
    # Get available choices from app_state resources
    choices = []
    if hasattr(self, 'learning_controller') and self.learning_controller:
        if self.learning_controller.app_controller:
            try:
                resources = self.learning_controller.app_controller._app_state.resources
                choices = resources.get(meta.resource_key, [])
            except Exception:
                pass
    
    # Create checkbuttons
    if not choices:
        # No choices available
        label = ttk.Label(
            self.checklist_inner_frame,
            text=f"No {meta.display_name} options available",
            foreground="gray"
        )
        label.pack(anchor="w", pady=2)
    else:
        # Add Select All / Clear All buttons
        button_frame = ttk.Frame(self.checklist_inner_frame)
        button_frame.pack(fill="x", pady=(0, 5))
        
        select_all_btn = ttk.Button(
            button_frame,
            text="Select All",
            command=lambda: self._select_all_choices(True)
        )
        select_all_btn.pack(side="left", padx=(0, 5))
        
        clear_all_btn = ttk.Button(
            button_frame,
            text="Clear All",
            command=lambda: self._select_all_choices(False)
        )
        clear_all_btn.pack(side="left")
        
        # Add checkbuttons for each choice
        for choice in choices:
            var = tk.BooleanVar(value=False)
            cb = ttk.Checkbutton(self.checklist_inner_frame, text=choice, variable=var)
            cb.pack(anchor="w", pady=2)
            self.choice_vars[choice] = var
        
        # Add count label
        self.choice_count_var = tk.StringVar(value="0 items selected")
        count_label = ttk.Label(
            self.checklist_inner_frame,
            textvariable=self.choice_count_var,
            foreground="blue"
        )
        count_label.pack(anchor="w", pady=(5, 0))
        
        # Bind checkbox changes to update count
        for var in self.choice_vars.values():
            var.trace_add("write", lambda *args: self._update_choice_count())

def _select_all_choices(self, selected: bool) -> None:
    """Select or deselect all checkboxes."""
    for var in self.choice_vars.values():
        var.set(selected)

def _update_choice_count(self) -> None:
    """Update the count label showing selected items."""
    count = sum(1 for var in self.choice_vars.values() if var.get())
    self.choice_count_var.set(f"{count} items selected")
```

#### Change 4: Update `_on_build_preview()` to include selected items
**Location**: Lines 175-220 (current `_on_build_preview` method)

**Modify experiment_data dict to include**:
```python
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
    # PR-LEARN-020: Add selected items for discrete variables
    "selected_items": [
        choice for choice, var in self.choice_vars.items() if var.get()
    ],
}
```

#### Change 5: Update validation to check discrete selections
**Location**: Lines 250-280 (current `_validate_experiment_data` method)

**Add validation**:
```python
def _validate_experiment_data(self, data: dict[str, Any]) -> str | None:
    """Validate experiment data and return error message if invalid.
    
    PR-LEARN-020: Enhanced with discrete variable validation.
    """
    from src.learning.variable_metadata import get_variable_metadata
    
    if not data["name"]:
        return "Experiment name is required"

    if not data["variable_under_test"]:
        return "Variable under test must be selected"
    
    # PR-LEARN-020: Variable-type-specific validation
    meta = get_variable_metadata(data["variable_under_test"])
    if meta:
        if meta.value_type == "discrete":
            # Discrete variables require at least one selection
            selected = data.get("selected_items", [])
            if not selected:
                return f"At least one {meta.display_name} option must be selected"
        
        elif meta.value_type == "numeric":
            # Numeric variables require valid range
            if data["start_value"] >= data["end_value"]:
                return "Start value must be less than end value"

            if data["step_value"] <= 0:
                return "Step value must be positive"

    if data["images_per_value"] < 1:
        return "Images per variant must be at least 1"

    if data["prompt_source"] == "custom" and not data["custom_prompt"]:
        return "Custom prompt text is required when using custom prompt source"

    return None
```

---

## Files VERIFIED UNCHANGED
- `src/pipeline/job_models_v2.py` - NJR structure unchanged
- `src/controller/learning_execution_controller.py` - Execution logic unchanged
- `src/learning/learning_plan.py` - Plan structures unchanged
- All test files - existing tests continue to pass

---

# ARCHITECTURAL COMPLIANCE

- [x] NJR‑only execution path - learning uses direct NJR from PR-LEARN-010
- [x] No PipelineConfig usage - metadata system is separate
- [x] Metadata-driven design - follows StableNew registry pattern
- [x] Resource discovery via AppStateV2.resources - no direct WebUI calls
- [x] Backward compatible - numeric variables work unchanged
- [x] Stage card config source - baseline config still from `_get_baseline_config()`

---

# IMPLEMENTATION STEPS (ORDERED, NON‑OPTIONAL)

## Step 1: Create Variable Metadata Registry

**File**: `src/learning/variable_metadata.py` (NEW)

**Implementation**:
```python
"""Variable metadata registry for learning experiments.

PR-LEARN-020: Defines testable variables and their characteristics.
"""

from dataclasses import dataclass, field
from typing import Any, Literal


@dataclass
class VariableMetadata:
    """Metadata describing a testable variable."""
    
    name: str                    # Internal name: "cfg_scale"
    display_name: str            # UI display: "CFG Scale"
    value_type: Literal["numeric", "discrete", "resource", "composite"]
    config_path: str             # Where to apply: "txt2img.cfg_scale"
    ui_component: Literal["range", "checklist", "lora_composite"]
    resource_key: str | None = None  # For discrete/resource types: "samplers"
    constraints: dict[str, Any] = field(default_factory=dict)  # Type-specific constraints


# Variable registry - defines all testable variables
LEARNING_VARIABLES: dict[str, VariableMetadata] = {
    "cfg_scale": VariableMetadata(
        name="cfg_scale",
        display_name="CFG Scale",
        value_type="numeric",
        config_path="txt2img.cfg_scale",
        ui_component="range",
        constraints={"min": 1.0, "max": 30.0, "step": 0.5}
    ),
    "steps": VariableMetadata(
        name="steps",
        display_name="Steps",
        value_type="numeric",
        config_path="txt2img.steps",
        ui_component="range",
        constraints={"min": 1, "max": 150, "step": 1}
    ),
    "sampler": VariableMetadata(
        name="sampler",
        display_name="Sampler",
        value_type="discrete",
        config_path="txt2img.sampler_name",
        ui_component="checklist",
        resource_key="samplers",
        constraints={}
    ),
    "scheduler": VariableMetadata(
        name="scheduler",
        display_name="Scheduler",
        value_type="discrete",
        config_path="txt2img.scheduler",
        ui_component="checklist",
        resource_key="schedulers",
        constraints={}
    ),
    "denoise_strength": VariableMetadata(
        name="denoise_strength",
        display_name="Denoise Strength",
        value_type="numeric",
        config_path="txt2img.denoising_strength",
        ui_component="range",
        constraints={"min": 0.0, "max": 1.0, "step": 0.05}
    ),
    "upscale_factor": VariableMetadata(
        name="upscale_factor",
        display_name="Upscale Factor",
        value_type="numeric",
        config_path="upscale.upscale_factor",
        ui_component="range",
        constraints={"min": 1.0, "max": 4.0, "step": 0.25}
    ),
}


def get_variable_metadata(variable_display_name: str) -> VariableMetadata | None:
    """Look up metadata by display name.
    
    Args:
        variable_display_name: Display name like "CFG Scale" or "Sampler"
    
    Returns:
        VariableMetadata if found, None otherwise
    """
    for meta in LEARNING_VARIABLES.values():
        if meta.display_name == variable_display_name:
            return meta
    return None


def get_all_variable_names() -> list[str]:
    """Get list of all variable display names for UI dropdown.
    
    Returns:
        List of display names sorted alphabetically
    """
    names = [meta.display_name for meta in LEARNING_VARIABLES.values()]
    return sorted(names)


def get_variable_by_internal_name(internal_name: str) -> VariableMetadata | None:
    """Look up metadata by internal name.
    
    Args:
        internal_name: Internal name like "cfg_scale" or "sampler"
    
    Returns:
        VariableMetadata if found, None otherwise
    """
    return LEARNING_VARIABLES.get(internal_name)
```

**Verification**:
- Registry contains 6 variables (4 numeric, 2 discrete)
- Lookup functions work correctly
- Metadata fields match dataclass definition

---

## Step 2: Modify LearningController Value Generation

**File**: `src/gui/controllers/learning_controller.py`

See detailed changes in "Files TO BE MODIFIED" section above.

**Verification**:
- `_generate_variant_values()` method added
- `update_experiment_design()` stores metadata
- `build_plan()` uses new value generation
- `_apply_variant_override_with_metadata()` method added

---

## Step 3: Add Metadata Field to LearningExperiment

**File**: `src/gui/learning_state.py`

See detailed changes in "Files TO BE MODIFIED" section above.

**Verification**:
- `metadata` field added with default empty dict
- Existing code unaffected

---

## Step 4: Implement Dynamic UI Widget Switching

**File**: `src/gui/views/experiment_design_panel.py`

See detailed changes in "Files TO BE MODIFIED" section above.

**Verification**:
- Checklist frame created and hidden by default
- Variable combo bound to `_on_variable_changed()`
- Widget switching works (range ↔ checklist)
- Checklist populated from resources
- Select All / Clear All buttons work
- Choice count updates dynamically
- Validation checks discrete selections

---

## Step 5: Update Imports

**Files**: 
- `src/gui/controllers/learning_controller.py`
- `src/gui/views/experiment_design_panel.py`

**Add imports**:
```python
from src.learning.variable_metadata import get_variable_metadata, get_all_variable_names
```

**Verify**: All imports resolve, no circular dependencies

---

# TEST PLAN (MANDATORY)

## Unit Tests

### Test 1: Metadata Registry Lookup
**File**: `tests/learning/test_variable_metadata.py` (NEW)

```python
"""Tests for variable metadata registry.

PR-LEARN-020: Tests metadata lookup and registry functions.
"""

import pytest
from src.learning.variable_metadata import (
    VariableMetadata,
    get_variable_metadata,
    get_all_variable_names,
    get_variable_by_internal_name,
    LEARNING_VARIABLES,
)


def test_metadata_registry_contains_expected_variables():
    """Verify registry contains all expected variables."""
    expected_names = ["cfg_scale", "steps", "sampler", "scheduler", "denoise_strength", "upscale_factor"]
    
    for name in expected_names:
        assert name in LEARNING_VARIABLES, f"Variable {name} missing from registry"


def test_get_variable_metadata_by_display_name():
    """Test lookup by display name."""
    meta = get_variable_metadata("CFG Scale")
    
    assert meta is not None
    assert meta.name == "cfg_scale"
    assert meta.value_type == "numeric"
    assert meta.config_path == "txt2img.cfg_scale"


def test_get_variable_metadata_returns_none_for_unknown():
    """Test lookup returns None for unknown variable."""
    meta = get_variable_metadata("Unknown Variable")
    
    assert meta is None


def test_get_all_variable_names():
    """Test getting all variable display names."""
    names = get_all_variable_names()
    
    assert len(names) == 6
    assert "CFG Scale" in names
    assert "Sampler" in names
    assert names == sorted(names)  # Should be sorted


def test_discrete_variable_has_resource_key():
    """Test discrete variables have resource_key set."""
    sampler_meta = get_variable_metadata("Sampler")
    scheduler_meta = get_variable_metadata("Scheduler")
    
    assert sampler_meta.resource_key == "samplers"
    assert scheduler_meta.resource_key == "schedulers"


def test_numeric_variable_has_constraints():
    """Test numeric variables have min/max/step constraints."""
    cfg_meta = get_variable_metadata("CFG Scale")
    
    assert "min" in cfg_meta.constraints
    assert "max" in cfg_meta.constraints
    assert "step" in cfg_meta.constraints
    assert cfg_meta.constraints["min"] == 1.0
    assert cfg_meta.constraints["max"] == 30.0
```

**Run**:
```bash
python -m pytest tests/learning/test_variable_metadata.py -v
```

---

### Test 2: Value Generation with Metadata
**File**: `tests/controller/test_learning_controller_value_generation.py` (NEW)

```python
"""Tests for learning controller value generation.

PR-LEARN-020: Tests metadata-driven value generation.
"""

import pytest
from src.gui.learning_state import LearningExperiment, LearningState
from src.gui.controllers.learning_controller import LearningController
from src.learning.learning_record import LearningRecordWriter


@pytest.fixture
def learning_controller():
    """Create learning controller with mocked dependencies."""
    state = LearningState()
    record_writer = LearningRecordWriter()
    
    # Mock app_controller with resources
    class MockAppController:
        class MockAppState:
            resources = {
                "samplers": ["Euler a", "DPM++ 2M Karras", "DDIM"],
                "schedulers": ["normal", "karras", "exponential"],
            }
        _app_state = MockAppState()
    
    controller = LearningController(
        learning_state=state,
        learning_record_writer=record_writer,
        pipeline_controller=MockAppController(),  # Minimal mock
        app_controller=MockAppController(),
    )
    
    return controller


def test_generate_numeric_values():
    """Test numeric value generation."""
    controller = learning_controller()
    
    experiment = LearningExperiment(
        name="Test CFG",
        variable_under_test="CFG Scale",
        metadata={
            "start_value": 5.0,
            "end_value": 8.0,
            "step_value": 1.0,
        }
    )
    
    values = controller._generate_variant_values(experiment)
    
    assert len(values) == 4
    assert values == [5.0, 6.0, 7.0, 8.0]


def test_generate_discrete_values_from_selection():
    """Test discrete value generation with user selection."""
    controller = learning_controller()
    
    experiment = LearningExperiment(
        name="Test Sampler",
        variable_under_test="Sampler",
        metadata={
            "selected_items": ["Euler a", "DDIM"],
        }
    )
    
    values = controller._generate_variant_values(experiment)
    
    assert len(values) == 2
    assert values == ["Euler a", "DDIM"]


def test_generate_discrete_values_defaults_to_all():
    """Test discrete value generation defaults to all available."""
    controller = learning_controller()
    
    experiment = LearningExperiment(
        name="Test Sampler",
        variable_under_test="Sampler",
        metadata={
            "selected_items": [],  # No selection
        }
    )
    
    values = controller._generate_variant_values(experiment)
    
    # Should use all available samplers
    assert len(values) == 3
    assert set(values) == {"Euler a", "DPM++ 2M Karras", "DDIM"}


def test_generate_values_raises_for_unknown_variable():
    """Test error handling for unknown variable."""
    controller = learning_controller()
    
    experiment = LearningExperiment(
        name="Test Unknown",
        variable_under_test="Unknown Variable",
        metadata={}
    )
    
    with pytest.raises(ValueError, match="Unknown variable"):
        controller._generate_variant_values(experiment)
```

**Run**:
```bash
python -m pytest tests/controller/test_learning_controller_value_generation.py -v
```

---

### Test 3: Override Application with Metadata
**File**: `tests/controller/test_learning_controller_overrides.py` (NEW)

```python
"""Tests for learning controller override application.

PR-LEARN-020: Tests metadata-driven config override application.
"""

import pytest
from src.gui.learning_state import LearningExperiment
from src.gui.controllers.learning_controller import LearningController
from src.gui.learning_state import LearningState
from src.learning.learning_record import LearningRecordWriter


@pytest.fixture
def learning_controller():
    """Create learning controller."""
    state = LearningState()
    record_writer = LearningRecordWriter()
    
    class MockPipelineController:
        pass
    
    controller = LearningController(
        learning_state=state,
        learning_record_writer=record_writer,
        pipeline_controller=MockPipelineController(),
    )
    
    return controller


def test_apply_numeric_override():
    """Test numeric variable override application."""
    controller = learning_controller()
    
    config = {"txt2img": {}}
    experiment = LearningExperiment(
        name="Test",
        variable_under_test="CFG Scale"
    )
    
    controller._apply_variant_override_with_metadata(config, 7.5, experiment)
    
    assert config["txt2img"]["cfg_scale"] == 7.5


def test_apply_discrete_override():
    """Test discrete variable override application."""
    controller = learning_controller()
    
    config = {"txt2img": {}}
    experiment = LearningExperiment(
        name="Test",
        variable_under_test="Sampler"
    )
    
    controller._apply_variant_override_with_metadata(config, "DPM++ 2M Karras", experiment)
    
    assert config["txt2img"]["sampler_name"] == "DPM++ 2M Karras"


def test_apply_override_creates_missing_sections():
    """Test override creates missing config sections."""
    controller = learning_controller()
    
    config = {}  # Empty config
    experiment = LearningExperiment(
        name="Test",
        variable_under_test="Steps"
    )
    
    controller._apply_variant_override_with_metadata(config, 30, experiment)
    
    assert "txt2img" in config
    assert config["txt2img"]["steps"] == 30
```

**Run**:
```bash
python -m pytest tests/controller/test_learning_controller_overrides.py -v
```

---

## Integration Tests

### Test 4: End-to-End Sampler Comparison
**File**: `tests/integration/test_learning_sampler_comparison.py` (NEW)

```python
"""Integration test for sampler comparison experiment.

PR-LEARN-020: Tests full sampler discrete variable workflow.
"""

import pytest
from src.gui.learning_state import LearningState, LearningExperiment
from src.gui.controllers.learning_controller import LearningController
from src.learning.learning_record import LearningRecordWriter


def test_sampler_comparison_end_to_end(tmp_path):
    """Test complete sampler comparison experiment flow."""
    # Setup
    state = LearningState()
    record_writer = LearningRecordWriter(records_path=tmp_path / "records.jsonl")
    
    class MockAppController:
        class MockAppState:
            resources = {
                "samplers": ["Euler a", "DPM++ 2M Karras", "DDIM"],
            }
        _app_state = MockAppState()
    
    class MockPipelineController:
        pass
    
    controller = LearningController(
        learning_state=state,
        learning_record_writer=record_writer,
        pipeline_controller=MockPipelineController(),
        app_controller=MockAppController(),
    )
    
    # Create experiment with sampler variable
    experiment_data = {
        "name": "Sampler Comparison",
        "description": "Test which sampler works best",
        "stage": "txt2img",
        "variable_under_test": "Sampler",
        "selected_items": ["Euler a", "DPM++ 2M Karras"],
        "images_per_value": 1,
        "prompt_source": "custom",
        "custom_prompt": "a cat",
    }
    
    # Update experiment design
    controller.update_experiment_design(experiment_data)
    
    # Verify experiment created
    assert controller.learning_state.current_experiment is not None
    assert controller.learning_state.current_experiment.variable_under_test == "Sampler"
    
    # Build plan
    experiment = controller.learning_state.current_experiment
    controller.build_plan(experiment)
    
    # Verify plan has correct variants
    plan = controller.learning_state.plan
    assert len(plan) == 2  # Two samplers
    assert plan[0].param_value == "Euler a"
    assert plan[1].param_value == "DPM++ 2M Karras"
    assert all(v.status == "pending" for v in plan)
    
    # Verify values stored in experiment
    assert experiment.values == ["Euler a", "DPM++ 2M Karras"]
```

**Run**:
```bash
python -m pytest tests/integration/test_learning_sampler_comparison.py -v
```

---

## GUI Tests

### Test 5: Dynamic Widget Switching
**File**: `tests/gui/test_experiment_design_panel_widgets.py` (NEW)

```python
"""Tests for experiment design panel dynamic widgets.

PR-LEARN-020: Tests widget switching and checklist population.
"""

import tkinter as tk
import pytest
from src.gui.views.experiment_design_panel import ExperimentDesignPanel
from src.gui.learning_state import LearningState
from src.gui.controllers.learning_controller import LearningController


@pytest.fixture
def root():
    """Create Tk root for GUI tests."""
    root = tk.Tk()
    yield root
    root.destroy()


def test_variable_selection_switches_to_checklist(root):
    """Test selecting discrete variable shows checklist."""
    # Setup
    state = LearningState()
    
    class MockAppController:
        class MockAppState:
            resources = {"samplers": ["Euler a", "DDIM"]}
        _app_state = MockAppState()
    
    class MockPipelineController:
        pass
    
    controller = LearningController(
        learning_state=state,
        pipeline_controller=MockPipelineController(),
        app_controller=MockAppController(),
    )
    
    panel = ExperimentDesignPanel(root, learning_controller=controller)
    
    # Select discrete variable
    panel.variable_var.set("Sampler")
    panel._on_variable_changed()
    
    # Verify checklist is visible
    assert panel.checklist_frame.winfo_ismapped()
    
    # Verify checkboxes created
    assert len(panel.choice_vars) == 2
    assert "Euler a" in panel.choice_vars
    assert "DDIM" in panel.choice_vars


def test_variable_selection_switches_to_range(root):
    """Test selecting numeric variable shows range widget."""
    state = LearningState()
    
    class MockPipelineController:
        pass
    
    controller = LearningController(
        learning_state=state,
        pipeline_controller=MockPipelineController(),
    )
    
    panel = ExperimentDesignPanel(root, learning_controller=controller)
    
    # First select discrete to show checklist
    panel.variable_var.set("Sampler")
    panel._on_variable_changed()
    
    # Then select numeric
    panel.variable_var.set("CFG Scale")
    panel._on_variable_changed()
    
    # Verify range widget visible, checklist hidden
    assert not panel.checklist_frame.winfo_ismapped()


def test_select_all_checkboxes(root):
    """Test Select All button."""
    state = LearningState()
    
    class MockAppController:
        class MockAppState:
            resources = {"samplers": ["Euler a", "DDIM", "LMS"]}
        _app_state = MockAppState()
    
    class MockPipelineController:
        pass
    
    controller = LearningController(
        learning_state=state,
        pipeline_controller=MockPipelineController(),
        app_controller=MockAppController(),
    )
    
    panel = ExperimentDesignPanel(root, learning_controller=controller)
    
    # Show checklist
    panel.variable_var.set("Sampler")
    panel._on_variable_changed()
    
    # Click Select All
    panel._select_all_choices(True)
    
    # Verify all checked
    assert all(var.get() for var in panel.choice_vars.values())


def test_validation_requires_discrete_selection(root):
    """Test validation rejects empty discrete selection."""
    state = LearningState()
    
    class MockPipelineController:
        pass
    
    controller = LearningController(
        learning_state=state,
        pipeline_controller=MockPipelineController(),
    )
    
    panel = ExperimentDesignPanel(root, learning_controller=controller)
    
    # Build experiment data with no selection
    data = {
        "name": "Test",
        "variable_under_test": "Sampler",
        "selected_items": [],
        "images_per_value": 1,
        "prompt_source": "custom",
        "custom_prompt": "test",
    }
    
    # Validate
    error = panel._validate_experiment_data(data)
    
    assert error is not None
    assert "at least one" in error.lower()
    assert "sampler" in error.lower()
```

**Run**:
```bash
python -m pytest tests/gui/test_experiment_design_panel_widgets.py -v
```

---

## Commands Executed

```bash
# Unit tests
python -m pytest tests/learning/test_variable_metadata.py -v
python -m pytest tests/controller/test_learning_controller_value_generation.py -v
python -m pytest tests/controller/test_learning_controller_overrides.py -v

# Integration test
python -m pytest tests/integration/test_learning_sampler_comparison.py -v

# GUI tests (if supported)
python -m pytest tests/gui/test_experiment_design_panel_widgets.py -v

# Verify metadata usage
grep -rn "get_variable_metadata" src/gui/controllers/learning_controller.py
grep -rn "LEARNING_VARIABLES" src/learning/variable_metadata.py

# Verify backward compatibility - existing numeric experiments still work
python -m pytest tests/learning_v2/ -k "test_learning" -v
```

---

# VERIFICATION & PROOF

## git diff
```bash
git diff src/learning/variable_metadata.py
git diff src/gui/controllers/learning_controller.py
git diff src/gui/learning_state.py
git diff src/gui/views/experiment_design_panel.py
```

**Expected changes**:
- NEW: `src/learning/variable_metadata.py` (~150 lines)
- MODIFIED: `src/gui/controllers/learning_controller.py` (~100 lines added)
- MODIFIED: `src/gui/learning_state.py` (1 field added)
- MODIFIED: `src/gui/views/experiment_design_panel.py` (~200 lines added)

## git status
```bash
git status --short
```

**Expected**:
```
A  src/learning/variable_metadata.py
M  src/gui/controllers/learning_controller.py
M  src/gui/learning_state.py
M  src/gui/views/experiment_design_panel.py
A  tests/learning/test_variable_metadata.py
A  tests/controller/test_learning_controller_value_generation.py
A  tests/controller/test_learning_controller_overrides.py
A  tests/integration/test_learning_sampler_comparison.py
A  tests/gui/test_experiment_design_panel_widgets.py
```

## Metadata Usage Verification
```bash
# Verify metadata import and usage
grep -n "from src.learning.variable_metadata import" src/gui/controllers/learning_controller.py
# Expected: Multiple import statements

# Verify registry population
grep -n "LEARNING_VARIABLES" src/learning/variable_metadata.py
# Expected: Registry dict definition with 6 entries

# Verify discrete variable support
grep -n "value_type.*discrete" src/learning/variable_metadata.py
# Expected: Matches for sampler and scheduler
```

## Backward Compatibility Verification
```bash
# Run existing learning tests to ensure no regressions
python -m pytest tests/learning_v2/test_learning_controller.py -v
python -m pytest tests/learning_v2/test_phase2_job_completion_integration.py -v

# Expected: All existing tests pass
```

---

# ARCHITECTURAL COMPLIANCE VERIFICATION

## Metadata System
- [x] Registry defines all variables with clear metadata
- [x] Lookup functions work by display name and internal name
- [x] UI component type specified for each variable
- [x] Resource keys specified for discrete types

## Value Generation
- [x] Numeric range generation preserved
- [x] Discrete choice generation from resources
- [x] Fallback to all available if no selection
- [x] Comprehensive logging

## Override Application
- [x] Config path parsed dynamically
- [x] Missing sections created automatically
- [x] Works for both numeric and discrete
- [x] No hardcoded variable names in core logic

## UI Integration
- [x] Dynamic widget switching based on metadata
- [x] Checklist populated from resources
- [x] Select All / Clear All functionality
- [x] Choice count display
- [x] Variable-specific validation

---

# GOLDEN PATH CONFIRMATION

**User Flow: Create Sampler Comparison Experiment**

1. User opens Learning tab
2. User enters experiment name: "Best Sampler"
3. User selects "Sampler" from variable dropdown
4. UI automatically switches to checklist
5. Checklist shows available samplers from WebUI
6. User checks "Euler a" and "DPM++ 2M Karras"
7. Counter shows "2 items selected"
8. User sets images per variant: 4
9. User enters prompt: "a futuristic city"
10. User clicks "Build Preview Only"
11. Plan table shows 2 variants (Euler a, DPM++ 2M Karras)
12. User clicks "Run Experiment"
13. Jobs submitted with correct sampler in NJR
14. run_metadata.json contains correct sampler for each variant

**Expected Behavior**:
- ✅ UI adapts to variable type automatically
- ✅ Resources discovered from WebUI
- ✅ Validation prevents empty selection
- ✅ Variants generated correctly
- ✅ NJRs have correct sampler applied
- ✅ Config propagates to run_metadata.json

---

# COMPLETION CRITERIA

This PR is complete when:

1. ✅ Variable metadata registry created with 6 variables
2. ✅ LearningController uses metadata for value generation
3. ✅ ExperimentDesignPanel switches widgets dynamically
4. ✅ Discrete variables (Sampler, Scheduler) fully functional
5. ✅ All unit tests pass (12+ tests)
6. ✅ Integration test demonstrates end-to-end sampler comparison
7. ✅ Backward compatibility maintained (existing tests pass)
8. ✅ Documentation updated with metadata system design

---

**Next Steps**:
1. Execute this PR
2. Validate sampler/scheduler experiments work in UI
3. Generate PR-LEARN-021 for resource variables (Model, VAE)
4. Continue to PR-LEARN-022 for composite LoRA variables
