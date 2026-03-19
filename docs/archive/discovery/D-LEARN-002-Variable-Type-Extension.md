# D-LEARN-002: Variable Type Extension for Learning Pipeline

**Discovery Date**: 2026-01-10  
**Architecture Version**: v2.6  
**Status**: DISCOVERY  
**Related Documents**: 
- LEARNING_ROADMAP_v2.6.md
- PR-LEARN-010 (Direct NJR Construction)
- ARCHITECTURE_v2.6.md

---

## Executive Summary

The current learning pipeline only supports **quantitative/numeric variables** (CFG Scale, Steps, Denoise Strength, etc.) with start/stop/step range specification. This discovery analyzes requirements for supporting **discrete choice variables** (samplers, schedulers, models, VAEs) and **composite variables** (LoRAs with strength).

### Critical Gaps Identified

1. **No discrete choice support**: Cannot iterate through sampler/scheduler lists
2. **No resource selection**: Cannot select model or VAE as variable under test
3. **No composite variables**: LoRAs require both selection AND strength sweeping
4. **No LoRA state visibility**: Cannot identify which LoRA is currently selected for testing
5. **UI constraints**: Only numeric spinboxes (start/stop/step) for value specification

---

## 1. Current State Analysis

### 1.1 Current Variable Implementation

**File**: `src/gui/views/experiment_design_panel.py`

```python
self.variable_combo = ttk.Combobox(
    self,
    textvariable=self.variable_var,
    values=[
        "CFG Scale",        # Numeric: 1.0 - 30.0
        "Steps",            # Numeric: 1 - 150
        "Sampler",          # DISCRETE (broken)
        "Scheduler",        # DISCRETE (broken)
        "LoRA Strength",    # Numeric + Selection (broken)
        "Denoise Strength", # Numeric: 0.0 - 1.0
        "Upscale Factor",   # Numeric: 1.0 - 4.0
    ],
    state="readonly",
)

# Value Specification - NUMERIC ONLY
self.start_spin = tk.Spinbox(value_frame, from_=0.1, to=100.0, increment=0.1, textvariable=self.start_var)
self.end_spin = tk.Spinbox(value_frame, from_=0.1, to=100.0, increment=0.1, textvariable=self.end_var)
self.step_spin = tk.Spinbox(value_frame, from_=0.1, to=10.0, increment=0.1, textvariable=self.step_var)
```

**Problems**:
- "Sampler" and "Scheduler" in dropdown but no way to specify which samplers to test
- "LoRA Strength" has no LoRA selector - which LoRA is being varied?
- No access to available resource lists (samplers, schedulers, models, VAEs)

### 1.2 Value Generation Logic

**File**: `src/gui/controllers/learning_controller.py`

```python
def _generate_values_from_range(self, start: float, end: float, step: float) -> list[float]:
    """Generate list of values from start to end with given step."""
    values = []
    current = start
    while current <= end:
        values.append(round(current, 2))
        current += step
    return values
```

**Limitation**: Only generates numeric values. Cannot handle discrete choices.

### 1.3 Variant Override Application

**File**: `src/gui/controllers/learning_controller.py` (lines 700-750)

```python
def _apply_overrides_to_config(
    self, baseline_config: dict[str, Any], overrides: dict[str, Any], experiment: LearningExperiment
) -> dict[str, Any]:
    """Apply variant overrides to baseline config."""
    config = copy.deepcopy(baseline_config)
    
    variable = experiment.variable_under_test
    
    # Current handling - NUMERIC ONLY
    if variable == "CFG Scale":
        config["txt2img"]["cfg_scale"] = overrides["cfg_scale"]
    elif variable == "Steps":
        config["txt2img"]["steps"] = overrides["steps"]
    elif variable == "Sampler":  # BROKEN - no override applied
        pass
    # ... etc
```

**Problem**: No path to apply discrete choices (sampler names, model names, etc.)

### 1.4 Available Resources

Resources are stored in `AppStateV2.resources`:

```python
resources: dict[str, list[Any]] = field(
    default_factory=lambda: {
        "models": [],
        "vaes": [],
        "samplers": [],
        "schedulers": [],
        "upscalers": [],
    }
)
```

**Access Path**: `app_state.resources["samplers"]` → `["Euler a", "DPM++ 2M Karras", ...]`

---

## 2. Variable Type Requirements

### 2.1 Variable Type Taxonomy

| Variable Type | Examples | Value Specification | Override Application |
|---------------|----------|---------------------|----------------------|
| **Numeric Range** | CFG Scale, Steps, Denoise | start, stop, step | Direct numeric override |
| **Discrete Choice** | Sampler, Scheduler | Multi-select from list | String override |
| **Resource Selection** | Model, VAE | Single-select from resources | String override (filename) |
| **Composite** | LoRA + Strength | LoRA selector + strength range | Dict override {name, weight} |
| **Boolean** | Enable HiRes, Enable ADetailer | [True, False] | Boolean override |

### 2.2 Detailed Requirements

#### 2.2.1 Discrete Choice Variables (Sampler, Scheduler)

**Use Case**: "Test which sampler produces best results"

**Requirements**:
- Display available samplers from `app_state.resources["samplers"]`
- Allow multi-select (Euler a, DPM++ 2M Karras, DDIM)
- Generate one variant per selected sampler
- Apply sampler name to `txt2img.sampler_name` in NJR

**UI Needs**:
- Checklistbox or multi-select widget
- "Select All" / "Deselect All" buttons
- Display count: "3 samplers selected"

#### 2.2.2 Resource Selection Variables (Model, VAE)

**Use Case**: "Compare model A vs model B on same prompt"

**Requirements**:
- Display available models from `app_state.resources["models"]`
- Allow multi-select (model1.safetensors, model2.safetensors)
- Generate one variant per selected model
- Apply model filename to `txt2img.model` in NJR

**UI Needs**:
- Same as discrete choice
- Filter/search for large model lists
- Display model metadata (SD version, size)

#### 2.2.3 Composite Variables (LoRA + Strength)

**Use Case**: "Find optimal strength for LoRA X"

**Requirements**:
- **Phase 1**: Select which LoRA to test
  - Display currently selected LoRAs from stage card state
  - Allow single-select (only one LoRA varies at a time)
- **Phase 2**: Specify strength range
  - Start: 0.0, Stop: 1.5, Step: 0.1
- Generate variants with {lora_name, strength} pairs
- Apply to `lora_tags` in NJR

**UI Needs**:
- LoRA selector dropdown (from current stage card state)
- Numeric range spinboxes for strength
- Display: "Testing: CharacterLoRA (0.5 → 1.5, step 0.1)"

**Complex Case**: Testing different LoRAs (not just strength)
- **Use Case**: "Which character LoRA works best?"
- Select multiple LoRAs, test each at fixed strength
- Requires two modes: "Test LoRA Selection" vs "Test LoRA Strength"

---

## 3. Architectural Analysis

### 3.1 Key Constraints

1. **NJR-Only Execution**: PR-LEARN-010 established direct NJR construction path
2. **Stage Card Config Source**: Baseline config comes from stage cards via `_get_baseline_config()`
3. **Resource Discovery**: Resources already available in `AppStateV2.resources`
4. **PromptPack Architecture**: Learning must not violate PromptPack-only input model
5. **Immutable NJR**: Once NJR is built, it cannot be mutated

### 3.2 Extension Points

1. **Value Generation**: `_generate_values_from_range()` → needs variant generators
2. **Override Application**: `_apply_overrides_to_config()` → needs type-aware logic
3. **UI Value Spec**: `ExperimentDesignPanel` value specification frame → needs dynamic widgets
4. **Validation**: `_validate_baseline_config()` → needs variable-specific validation

---

## 4. Proposed Architectural Approaches

### Approach A: Variable Type Registry with Strategy Pattern

**Core Concept**: Define variable types as strategy objects with specialized value generation and override logic.

#### Architecture

```python
# New file: src/learning/variable_types.py

from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Any

@dataclass
class VariableDefinition:
    """Defines a variable that can be tested in learning experiments."""
    name: str                    # Display name: "CFG Scale"
    var_type: str                # Type: "numeric", "discrete", "resource", "composite"
    config_path: str             # Where to apply: "txt2img.cfg_scale"
    ui_widget: str               # UI widget: "range", "checklist", "dropdown"
    constraints: dict[str, Any]  # Type-specific constraints

class VariableStrategy(ABC):
    """Base strategy for variable value generation and application."""
    
    @abstractmethod
    def generate_values(self, spec: dict[str, Any], resources: dict[str, list[Any]]) -> list[Any]:
        """Generate list of values to test."""
        pass
    
    @abstractmethod
    def apply_override(self, config: dict[str, Any], value: Any, definition: VariableDefinition) -> None:
        """Apply value to config dict."""
        pass
    
    @abstractmethod
    def validate_spec(self, spec: dict[str, Any]) -> tuple[bool, str]:
        """Validate value specification from UI."""
        pass

class NumericRangeStrategy(VariableStrategy):
    """Strategy for numeric range variables (CFG, Steps, etc.)."""
    
    def generate_values(self, spec: dict[str, Any], resources: dict[str, list[Any]]) -> list[float]:
        start = float(spec["start"])
        end = float(spec["end"])
        step = float(spec["step"])
        
        values = []
        current = start
        while current <= end:
            values.append(round(current, 2))
            current += step
        return values
    
    def apply_override(self, config: dict[str, Any], value: Any, definition: VariableDefinition) -> None:
        # Parse config_path: "txt2img.cfg_scale"
        keys = definition.config_path.split(".")
        target = config
        for key in keys[:-1]:
            target = target.setdefault(key, {})
        target[keys[-1]] = value

class DiscreteChoiceStrategy(VariableStrategy):
    """Strategy for discrete choice variables (Sampler, Scheduler)."""
    
    def generate_values(self, spec: dict[str, Any], resources: dict[str, list[Any]]) -> list[str]:
        # spec["selected_items"] contains user-selected choices
        return spec.get("selected_items", [])
    
    def apply_override(self, config: dict[str, Any], value: Any, definition: VariableDefinition) -> None:
        keys = definition.config_path.split(".")
        target = config
        for key in keys[:-1]:
            target = target.setdefault(key, {})
        target[keys[-1]] = value

class CompositeLoRAStrategy(VariableStrategy):
    """Strategy for LoRA + Strength composite variable."""
    
    def generate_values(self, spec: dict[str, Any], resources: dict[str, list[Any]]) -> list[dict[str, Any]]:
        lora_name = spec["lora_name"]
        start = float(spec["strength_start"])
        end = float(spec["strength_end"])
        step = float(spec["strength_step"])
        
        values = []
        current = start
        while current <= end:
            values.append({"name": lora_name, "weight": round(current, 2)})
            current += step
        return values
    
    def apply_override(self, config: dict[str, Any], value: dict[str, Any], definition: VariableDefinition) -> None:
        # value = {"name": "CharacterLoRA", "weight": 0.8}
        # Apply to lora_tags in NJR (handled in _build_variant_njr)
        config.setdefault("lora_override", {}).update(value)

# Variable Registry
VARIABLE_REGISTRY: dict[str, tuple[VariableDefinition, VariableStrategy]] = {
    "CFG Scale": (
        VariableDefinition(
            name="CFG Scale",
            var_type="numeric",
            config_path="txt2img.cfg_scale",
            ui_widget="range",
            constraints={"min": 1.0, "max": 30.0, "default_step": 0.5}
        ),
        NumericRangeStrategy()
    ),
    "Sampler": (
        VariableDefinition(
            name="Sampler",
            var_type="discrete",
            config_path="txt2img.sampler_name",
            ui_widget="checklist",
            constraints={"resource_key": "samplers"}
        ),
        DiscreteChoiceStrategy()
    ),
    "Model": (
        VariableDefinition(
            name="Model",
            var_type="resource",
            config_path="txt2img.model",
            ui_widget="checklist",
            constraints={"resource_key": "models"}
        ),
        DiscreteChoiceStrategy()
    ),
    "LoRA Strength": (
        VariableDefinition(
            name="LoRA Strength",
            var_type="composite",
            config_path="lora_override",
            ui_widget="lora_range",
            constraints={"lora_source": "stage_card"}
        ),
        CompositeLoRAStrategy()
    ),
}

def get_variable_strategy(variable_name: str) -> tuple[VariableDefinition, VariableStrategy] | None:
    """Get definition and strategy for a variable."""
    return VARIABLE_REGISTRY.get(variable_name)
```

#### Integration with LearningController

```python
# In src/gui/controllers/learning_controller.py

def _generate_variant_values(self, experiment: LearningExperiment) -> list[Any]:
    """Generate values using variable strategy."""
    from src.learning.variable_types import get_variable_strategy
    
    strategy_tuple = get_variable_strategy(experiment.variable_under_test)
    if not strategy_tuple:
        raise ValueError(f"Unknown variable: {experiment.variable_under_test}")
    
    definition, strategy = strategy_tuple
    
    # Get value spec from experiment metadata
    spec = experiment.metadata.get("value_spec", {})
    
    # Get resources from app_state
    resources = {}
    if self.app_controller and hasattr(self.app_controller, "_app_state"):
        resources = self.app_controller._app_state.resources
    
    return strategy.generate_values(spec, resources)

def _apply_variant_override(
    self, 
    config: dict[str, Any], 
    value: Any, 
    experiment: LearningExperiment
) -> None:
    """Apply override using variable strategy."""
    from src.learning.variable_types import get_variable_strategy
    
    strategy_tuple = get_variable_strategy(experiment.variable_under_test)
    if not strategy_tuple:
        return
    
    definition, strategy = strategy_tuple
    strategy.apply_override(config, value, definition)
```

#### UI Changes (ExperimentDesignPanel)

```python
def _build_value_specification_ui(self) -> None:
    """Build dynamic value specification UI based on selected variable."""
    # Bind to variable selection change
    self.variable_combo.bind("<<ComboboxSelected>>", self._on_variable_changed)
    
    # Container for dynamic widgets
    self.value_spec_container = ttk.Frame(self)
    self.value_spec_container.grid(row=9, column=0, sticky="ew")

def _on_variable_changed(self, event) -> None:
    """Rebuild value specification UI when variable changes."""
    from src.learning.variable_types import get_variable_strategy
    
    variable_name = self.variable_var.get()
    strategy_tuple = get_variable_strategy(variable_name)
    
    if not strategy_tuple:
        return
    
    definition, strategy = strategy_tuple
    
    # Clear existing widgets
    for widget in self.value_spec_container.winfo_children():
        widget.destroy()
    
    # Build appropriate widget based on ui_widget type
    if definition.ui_widget == "range":
        self._build_range_widget(definition)
    elif definition.ui_widget == "checklist":
        self._build_checklist_widget(definition)
    elif definition.ui_widget == "lora_range":
        self._build_lora_range_widget(definition)

def _build_checklist_widget(self, definition: VariableDefinition) -> None:
    """Build multi-select checklist for discrete choices."""
    resource_key = definition.constraints.get("resource_key")
    
    # Get available choices from app_state
    choices = []
    if self.app_state:
        choices = self.app_state.resources.get(resource_key, [])
    
    # Build scrollable checklist
    frame = ttk.Frame(self.value_spec_container)
    frame.pack(fill="both", expand=True)
    
    # Add checkbuttons for each choice
    self.choice_vars = {}
    for choice in choices:
        var = tk.BooleanVar(value=False)
        cb = ttk.Checkbutton(frame, text=choice, variable=var)
        cb.pack(anchor="w")
        self.choice_vars[choice] = var
```

**Pros**:
- ✅ Clean separation of concerns (strategy per variable type)
- ✅ Easy to add new variable types
- ✅ Type-safe value generation and application
- ✅ UI can dynamically adapt to variable type
- ✅ Testable strategies in isolation

**Cons**:
- ❌ Requires new file/module (`variable_types.py`)
- ❌ More complex initial implementation
- ❌ UI changes are substantial

---

### Approach B: Inline Variable Type Handling with Conditional Logic

**Core Concept**: Extend existing `_generate_values_from_range()` and `_apply_overrides_to_config()` with conditional logic for each variable type.

#### Implementation

```python
# In src/gui/controllers/learning_controller.py

def _generate_variant_values(self, experiment: LearningExperiment) -> list[Any]:
    """Generate values based on variable type."""
    variable = experiment.variable_under_test
    
    # Get value specification from experiment
    start = experiment.metadata.get("start_value", 1.0)
    end = experiment.metadata.get("end_value", 10.0)
    step = experiment.metadata.get("step_value", 1.0)
    
    # Numeric variables
    if variable in ["CFG Scale", "Steps", "Denoise Strength", "Upscale Factor"]:
        return self._generate_numeric_range(start, end, step)
    
    # Discrete choice variables
    elif variable in ["Sampler", "Scheduler"]:
        resource_key = "samplers" if variable == "Sampler" else "schedulers"
        selected = experiment.metadata.get("selected_items", [])
        
        # If no selection, use all available
        if not selected and self.app_controller:
            resources = self.app_controller._app_state.resources
            selected = resources.get(resource_key, [])
        
        return selected
    
    # Resource selection variables
    elif variable in ["Model", "VAE"]:
        resource_key = "models" if variable == "Model" else "vaes"
        selected = experiment.metadata.get("selected_items", [])
        
        if not selected and self.app_controller:
            resources = self.app_controller._app_state.resources
            selected = resources.get(resource_key, [])
        
        return selected
    
    # Composite LoRA variable
    elif variable == "LoRA Strength":
        lora_name = experiment.metadata.get("lora_name")
        if not lora_name:
            raise ValueError("LoRA name not specified for LoRA Strength variable")
        
        # Generate strength values
        strengths = self._generate_numeric_range(start, end, step)
        
        # Return composite values
        return [{"name": lora_name, "weight": s} for s in strengths]
    
    else:
        raise ValueError(f"Unsupported variable type: {variable}")

def _apply_variant_override(
    self, 
    config: dict[str, Any], 
    value: Any, 
    experiment: LearningExperiment
) -> None:
    """Apply override based on variable type."""
    variable = experiment.variable_under_test
    
    if variable == "CFG Scale":
        config["txt2img"]["cfg_scale"] = float(value)
    
    elif variable == "Steps":
        config["txt2img"]["steps"] = int(value)
    
    elif variable == "Sampler":
        config["txt2img"]["sampler_name"] = str(value)
    
    elif variable == "Scheduler":
        config["txt2img"]["scheduler"] = str(value)
    
    elif variable == "Model":
        config["txt2img"]["model"] = str(value)
    
    elif variable == "VAE":
        config["txt2img"]["vae"] = str(value)
    
    elif variable == "Denoise Strength":
        config["txt2img"]["denoising_strength"] = float(value)
    
    elif variable == "Upscale Factor":
        config["upscale"]["upscale_factor"] = float(value)
    
    elif variable == "LoRA Strength":
        # value is {"name": "...", "weight": ...}
        config.setdefault("lora_override", {}).update(value)
    
    else:
        raise ValueError(f"Cannot apply override for variable: {variable}")
```

#### UI Changes (Simplified)

```python
# In src/gui/views/experiment_design_panel.py

def _on_variable_changed(self, event=None) -> None:
    """Show/hide appropriate value specification widgets."""
    variable = self.variable_var.get()
    
    # Hide all widgets initially
    self.range_frame.grid_remove()
    self.checklist_frame.grid_remove()
    self.lora_frame.grid_remove()
    
    # Show appropriate widget
    if variable in ["CFG Scale", "Steps", "Denoise Strength", "Upscale Factor"]:
        self.range_frame.grid()  # Show start/stop/step spinboxes
    
    elif variable in ["Sampler", "Scheduler", "Model", "VAE"]:
        self._populate_checklist(variable)
        self.checklist_frame.grid()  # Show checklist
    
    elif variable == "LoRA Strength":
        self._populate_lora_selector()
        self.lora_frame.grid()  # Show LoRA selector + range
```

**Pros**:
- ✅ Simpler implementation (no new files)
- ✅ All logic in one place
- ✅ Easier to debug and trace
- ✅ Faster to implement initially

**Cons**:
- ❌ Large if/elif chains (maintainability concern)
- ❌ Harder to test individual variable types
- ❌ Violates Open/Closed Principle (must modify existing code for new types)
- ❌ UI logic still needs dynamic widget switching

---

### Approach C: Hybrid - Variable Metadata Registry + Inline Logic

**Core Concept**: Use a simple metadata registry to define variable characteristics, but keep generation and application logic inline with conditional branches.

#### Implementation

```python
# New file: src/learning/variable_metadata.py

from dataclasses import dataclass
from typing import Literal

@dataclass
class VariableMetadata:
    """Metadata describing a testable variable."""
    name: str
    display_name: str
    value_type: Literal["numeric", "discrete", "resource", "composite"]
    config_path: str
    ui_component: Literal["range", "checklist", "lora_composite"]
    resource_key: str | None = None  # For discrete/resource types
    constraints: dict[str, any] = None

# Variable registry
LEARNING_VARIABLES: dict[str, VariableMetadata] = {
    "cfg_scale": VariableMetadata(
        name="cfg_scale",
        display_name="CFG Scale",
        value_type="numeric",
        config_path="txt2img.cfg_scale",
        ui_component="range",
        constraints={"min": 1.0, "max": 30.0, "step": 0.5}
    ),
    "sampler": VariableMetadata(
        name="sampler",
        display_name="Sampler",
        value_type="discrete",
        config_path="txt2img.sampler_name",
        ui_component="checklist",
        resource_key="samplers"
    ),
    "model": VariableMetadata(
        name="model",
        display_name="Model",
        value_type="resource",
        config_path="txt2img.model",
        ui_component="checklist",
        resource_key="models"
    ),
    "lora_strength": VariableMetadata(
        name="lora_strength",
        display_name="LoRA Strength",
        value_type="composite",
        config_path="lora_override",
        ui_component="lora_composite",
        constraints={"min": 0.0, "max": 2.0, "step": 0.1}
    ),
}

def get_variable_metadata(variable_display_name: str) -> VariableMetadata | None:
    """Look up metadata by display name."""
    for meta in LEARNING_VARIABLES.values():
        if meta.display_name == variable_display_name:
            return meta
    return None
```

#### LearningController Integration

```python
# In src/gui/controllers/learning_controller.py

def _generate_variant_values(self, experiment: LearningExperiment) -> list[Any]:
    """Generate values using metadata + inline logic."""
    from src.learning.variable_metadata import get_variable_metadata
    
    meta = get_variable_metadata(experiment.variable_under_test)
    if not meta:
        raise ValueError(f"Unknown variable: {experiment.variable_under_test}")
    
    # Dispatch based on value_type
    if meta.value_type == "numeric":
        start = experiment.metadata.get("start_value", meta.constraints["min"])
        end = experiment.metadata.get("end_value", meta.constraints["max"])
        step = experiment.metadata.get("step_value", meta.constraints["step"])
        return self._generate_numeric_range(start, end, step)
    
    elif meta.value_type in ["discrete", "resource"]:
        selected = experiment.metadata.get("selected_items", [])
        if not selected and self.app_controller:
            resources = self.app_controller._app_state.resources
            selected = resources.get(meta.resource_key, [])
        return selected
    
    elif meta.value_type == "composite":
        # Assume LoRA for now
        lora_name = experiment.metadata.get("lora_name")
        if not lora_name:
            raise ValueError("LoRA name required for composite variable")
        
        start = experiment.metadata.get("strength_start", 0.5)
        end = experiment.metadata.get("strength_end", 1.5)
        step = experiment.metadata.get("strength_step", 0.1)
        
        strengths = self._generate_numeric_range(start, end, step)
        return [{"name": lora_name, "weight": s} for s in strengths]

def _apply_variant_override(
    self, 
    config: dict[str, Any], 
    value: Any, 
    experiment: LearningExperiment
) -> None:
    """Apply override using metadata path."""
    from src.learning.variable_metadata import get_variable_metadata
    
    meta = get_variable_metadata(experiment.variable_under_test)
    if not meta:
        return
    
    # Parse config_path: "txt2img.cfg_scale"
    keys = meta.config_path.split(".")
    target = config
    for key in keys[:-1]:
        target = target.setdefault(key, {})
    
    # Special handling for composite types
    if meta.value_type == "composite":
        target[keys[-1]] = value  # value is dict for LoRA
    else:
        target[keys[-1]] = value
```

**Pros**:
- ✅ Metadata registry provides structure and discoverability
- ✅ UI can query metadata for constraints and widget types
- ✅ Less code duplication than Approach B
- ✅ Easier to extend than pure inline approach
- ✅ Simpler than full Strategy pattern

**Cons**:
- ❌ Still has some inline conditional logic
- ❌ Not as clean as Strategy pattern
- ❌ Metadata registry might become complex for composite types

---

## 5. Recommendation

### Recommended Approach: **Approach C (Hybrid Metadata + Inline)**

**Rationale**:

1. **Balanced Complexity**: Strikes balance between simplicity (Approach B) and extensibility (Approach A)

2. **Incremental Implementation**: Can be implemented in phases:
   - Phase 1: Add metadata registry + basic discrete variables (samplers, schedulers)
   - Phase 2: Add resource variables (models, VAEs)
   - Phase 3: Add composite variables (LoRAs)

3. **UI Integration**: Metadata makes UI dynamic widget generation straightforward

4. **Architecture Alignment**: Follows StableNew's pattern of "simple registries + controller logic" (similar to stage card registration)

5. **Testability**: Metadata is testable, value generation is testable, override application is testable

6. **Maintainability**: New variables only require adding metadata entry + minimal conditional logic

---

## 6. Implementation Roadmap

### Phase 1: Foundation & Discrete Variables (PR-LEARN-020)

**Files Modified**:
- `src/learning/variable_metadata.py` (NEW)
- `src/gui/controllers/learning_controller.py` (MODIFY)
- `src/gui/views/experiment_design_panel.py` (MODIFY)

**Scope**:
1. Create variable metadata registry with numeric, discrete types
2. Extend `_generate_variant_values()` to use metadata
3. Extend `_apply_variant_override()` to use config_path
4. Add UI dynamic widget switching for range vs checklist
5. Implement sampler/scheduler discrete variable support

**Deliverables**:
- User can select "Sampler" as variable under test
- UI shows checklist of available samplers
- Variants are generated for each selected sampler
- Jobs execute with correct sampler applied

**Tests**:
- Unit: Test metadata lookup
- Unit: Test discrete value generation
- Unit: Test override application for sampler/scheduler
- Integration: End-to-end sampler comparison experiment

---

### Phase 2: Resource Variables (PR-LEARN-021)

**Files Modified**:
- `src/learning/variable_metadata.py` (EXTEND)
- `src/gui/views/experiment_design_panel.py` (EXTEND)

**Scope**:
1. Add model and VAE metadata entries
2. Implement resource selection UI (with search/filter for large lists)
3. Test model comparison experiments

**Deliverables**:
- User can select "Model" or "VAE" as variable under test
- UI shows filterable checklist of models/VAEs
- Jobs execute with correct model/VAE applied

**Tests**:
- Unit: Test model/VAE value generation
- Integration: Model comparison experiment with multiple models

---

### Phase 3: Composite LoRA Variables (PR-LEARN-022)

**Files Modified**:
- `src/learning/variable_metadata.py` (EXTEND)
- `src/gui/views/experiment_design_panel.py` (EXTEND)
- `src/gui/controllers/learning_controller.py` (EXTEND)

**Scope**:
1. Add LoRA composite metadata
2. Implement LoRA selector UI
   - Retrieve currently selected LoRAs from stage card state
   - Display LoRA dropdown with current selections
3. Implement strength range UI (like numeric range but LoRA-specific)
4. Handle LoRA override application in `_build_variant_njr()`
5. Support two modes:
   - "LoRA Strength" - vary strength of single LoRA
   - "LoRA Selection" - compare different LoRAs at fixed strength

**Deliverables**:
- User can select "LoRA Strength" as variable
- UI shows LoRA selector (from stage card) + strength range
- Variants generated with LoRA name + strength pairs
- Jobs execute with correct LoRA applied

**Tests**:
- Unit: Test LoRA composite value generation
- Unit: Test LoRA override application
- Integration: LoRA strength sweep experiment

---

### Phase 4: Advanced Features (PR-LEARN-023)

**Scope** (Optional enhancements):
1. **Multi-variable experiments**: Test 2+ variables simultaneously (combinatorial)
2. **Conditional variables**: "If upscale enabled, test upscale factor"
3. **LoRA stacking**: Test combinations of multiple LoRAs
4. **Preset variable groups**: "Test all samplers at 3 CFG values"

---

## 7. UI Mockups

### 7.1 Discrete Variable UI (Sampler Selection)

```
┌─ Experiment Design ────────────────────────────┐
│ Variable Under Test: [Sampler ▼]               │
├─ Value Specification ─────────────────────────┤
│ Select Samplers to Test:                      │
│                                                │
│ [✓] Euler a                                    │
│ [✓] DPM++ 2M Karras                            │
│ [ ] DDIM                                       │
│ [✓] LMS                                        │
│ [ ] Heun                                       │
│                                                │
│ [Select All] [Clear All]                      │
│                                                │
│ 3 samplers selected                            │
└────────────────────────────────────────────────┘
```

### 7.2 Composite LoRA Variable UI

```
┌─ Experiment Design ────────────────────────────┐
│ Variable Under Test: [LoRA Strength ▼]         │
├─ Value Specification ─────────────────────────┤
│ LoRA to Test:                                  │
│ [CharacterLoRA-v2 ▼] ← from stage card         │
│                                                │
│ Strength Range:                                │
│ Start: [0.5]  End: [1.5]  Step: [0.1]         │
│                                                │
│ 11 variants will be generated                  │
└────────────────────────────────────────────────┘
```

### 7.3 Resource Variable UI (Model Selection)

```
┌─ Experiment Design ────────────────────────────┐
│ Variable Under Test: [Model ▼]                 │
├─ Value Specification ─────────────────────────┤
│ Select Models to Test:                         │
│                                                │
│ Search: [SD1.5________] 🔍                     │
│                                                │
│ [✓] sd_xl_base_1.0.safetensors                │
│ [ ] sd-v1-5-pruned-emaonly.safetensors        │
│ [✓] dreamshaper_8.safetensors                 │
│ [ ] realisticVisionV60B1_v51VAE.safetensors   │
│                                                │
│ [Select All] [Clear All] [Filter: SDXL ▼]     │
│                                                │
│ 2 models selected                              │
└────────────────────────────────────────────────┘
```

---

## 8. Technical Considerations

### 8.1 LoRA State Retrieval

**Challenge**: Determining which LoRAs are currently selected in stage cards.

**Solution**:
```python
# In learning_controller.py
def _get_current_loras(self) -> list[dict[str, Any]]:
    """Get currently selected LoRAs from stage card state."""
    if not self.app_controller:
        return []
    
    # Get baseline config from stage cards
    baseline = self._get_baseline_config()
    
    # Extract LoRA info from txt2img config
    txt2img = baseline.get("txt2img", {})
    loras = txt2img.get("lora_strengths", [])
    
    # loras format: [{"name": "CharacterLoRA", "strength": 0.8, "enabled": True}, ...]
    return [l for l in loras if l.get("enabled", False)]
```

### 8.2 NJR LoRA Application

**Challenge**: Applying LoRA overrides to NormalizedJobRecord.

**Current NJR Structure**:
```python
@dataclass
class NormalizedJobRecord:
    # ...
    lora_tags: list[LoRATag] = field(default_factory=list)
```

**Override Application**:
```python
# In _build_variant_njr()
if experiment.variable_under_test == "LoRA Strength":
    # variant.param_value = {"name": "CharacterLoRA", "weight": 0.8}
    lora_override = variant.param_value
    
    # Replace or update LoRA in lora_tags
    new_tag = LoRATag(name=lora_override["name"], weight=lora_override["weight"])
    
    # Remove existing tag with same name, add new one
    record.lora_tags = [t for t in record.lora_tags if t.name != new_tag.name]
    record.lora_tags.append(new_tag)
```

### 8.3 Validation Enhancements

**Required Validations**:
1. **Discrete variables**: At least one item must be selected
2. **Resource variables**: Selected resources must exist in current WebUI
3. **LoRA variables**: Selected LoRA must be enabled in stage card
4. **Range variables**: Start < end, step > 0

```python
def _validate_experiment_data(self, data: dict[str, Any]) -> str | None:
    """Enhanced validation with variable-type awareness."""
    from src.learning.variable_metadata import get_variable_metadata
    
    variable_name = data["variable_under_test"]
    meta = get_variable_metadata(variable_name)
    
    if not meta:
        return f"Unknown variable: {variable_name}"
    
    if meta.value_type in ["discrete", "resource"]:
        selected = data.get("selected_items", [])
        if not selected:
            return f"No {meta.display_name} options selected"
    
    elif meta.value_type == "composite":
        lora_name = data.get("lora_name")
        if not lora_name:
            return "LoRA not selected for LoRA Strength variable"
    
    # ... other validations
    
    return None
```

---

## 9. Testing Strategy

### 9.1 Unit Tests

**File**: `tests/learning/test_variable_metadata.py`
- Test metadata registry lookup
- Test metadata validation
- Test constraints

**File**: `tests/learning/test_variable_generation.py`
- Test numeric value generation
- Test discrete value generation (samplers, schedulers)
- Test resource value generation (models, VAEs)
- Test composite value generation (LoRAs)

**File**: `tests/learning/test_variable_overrides.py`
- Test override application for each variable type
- Test config path parsing
- Test LoRA tag manipulation

### 9.2 Integration Tests

**File**: `tests/integration/test_learning_discrete_variables.py`
- End-to-end sampler comparison experiment
- End-to-end scheduler comparison experiment
- Verify NJR has correct sampler/scheduler applied
- Verify run_metadata.json has correct values

**File**: `tests/integration/test_learning_resource_variables.py`
- End-to-end model comparison experiment
- Verify NJR has correct model applied
- Verify outputs use correct model

**File**: `tests/integration/test_learning_lora_variables.py`
- End-to-end LoRA strength sweep experiment
- Verify NJR has correct LoRA tags
- Verify outputs vary with LoRA strength

### 9.3 GUI Tests

**File**: `tests/gui/test_experiment_design_panel_dynamic_widgets.py`
- Test widget switching when variable changes
- Test checklist population from resources
- Test LoRA selector population from stage card
- Test validation feedback

---

## 10. Migration Path for Existing Experiments

**Backward Compatibility**: Existing experiments with numeric variables will continue to work without changes.

**Data Format**:
```json
// OLD format (still supported)
{
  "variable_under_test": "CFG Scale",
  "start_value": 5.0,
  "end_value": 10.0,
  "step_value": 0.5
}

// NEW format (for discrete variables)
{
  "variable_under_test": "Sampler",
  "value_spec": {
    "selected_items": ["Euler a", "DPM++ 2M Karras", "LMS"]
  }
}

// NEW format (for composite variables)
{
  "variable_under_test": "LoRA Strength",
  "value_spec": {
    "lora_name": "CharacterLoRA-v2",
    "strength_start": 0.5,
    "strength_end": 1.5,
    "strength_step": 0.1
  }
}
```

---

## 11. Architectural Compliance Checklist

- [x] **NJR-Only Execution**: All variants build NJR directly (PR-LEARN-010 path)
- [x] **Stage Card Config Source**: Baseline config from `_get_baseline_config()`
- [x] **No PipelineConfig**: No legacy config objects in execution path
- [x] **Resource Discovery**: Uses `AppStateV2.resources` (no direct WebUI calls)
- [x] **PromptPack Architecture**: Learning experiments don't modify prompt packs
- [x] **Immutable NJR**: Variants create new NJRs, don't mutate existing ones
- [x] **Controller Separation**: LearningController handles UI logic, LearningExecutionController handles execution

---

## 12. Open Questions

1. **Multi-variable experiments**: Should we support testing 2+ variables simultaneously?
   - Example: Test all samplers at 3 CFG values (combinatorial explosion)
   - Recommendation: Defer to Phase 4

2. **LoRA stacking**: Should we support testing combinations of multiple LoRAs?
   - Example: "Test CharacterLoRA + StyleLoRA with varying strengths"
   - Recommendation: Defer to Phase 4

3. **Resource validation**: Should we validate that selected models/VAEs exist before submitting?
   - Recommendation: Yes, add validation in `_validate_experiment_data()`

4. **LoRA selection mode**: Should "LoRA Selection" be a separate variable or a mode of "LoRA Strength"?
   - Recommendation: Single variable "LoRA Strength" with checkbox "Compare different LoRAs"

---

## 13. Conclusion

The learning pipeline currently only supports numeric range variables. Extending to discrete choice, resource selection, and composite variables requires:

1. **Variable type metadata system** to describe each variable's characteristics
2. **Dynamic UI widgets** that adapt to selected variable type
3. **Enhanced value generation** logic for non-numeric variables
4. **Type-aware override application** in NJR construction

**Recommended approach**: Hybrid metadata registry + inline logic (Approach C) provides the best balance of simplicity, extensibility, and architecture alignment.

**Implementation should proceed in 3 phases**:
- Phase 1: Discrete variables (samplers, schedulers)
- Phase 2: Resource variables (models, VAEs)
- Phase 3: Composite variables (LoRAs)

Each phase builds incrementally on the previous, allowing validation and testing at each step.

---

**Next Steps**:
1. Review this discovery with stakeholders
2. Approve recommended approach
3. Generate PR-LEARN-020 spec for Phase 1 implementation
4. Implement, test, and validate Phase 1
5. Proceed to Phase 2 and 3 based on Phase 1 learnings
