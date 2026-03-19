# PR-LEARN-021: Resource Variable Support (Model, VAE)

**Related Discovery**: D-LEARN-002  
**Architecture Version**: v2.6  
**PR Date**: 2026-01-10  
**Dependencies**: PR-LEARN-020 (Discrete Variable Support)  
**Sequence**: Phase 2 of 3 (PR-LEARN-020 → PR-LEARN-021 → PR-LEARN-022)

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
   - Variable metadata system (established in PR-LEARN-020)
   - Resource variable handling

3. This PR **MUST**:
   - Extend variable metadata registry with Model and VAE resource types
   - Implement filterable checklist UI for large resource lists
   - Support model and VAE comparison experiments
   - Maintain compatibility with numeric and discrete variables

---

## ABSOLUTE EXECUTION RULES (NON‑NEGOTIABLE)

### 1. Scope Completion
- You MUST implement **100% of the PR scope**
- You MUST extend **every file listed**
- Partial implementation is **explicitly forbidden**

### 2. Resource Variable System Enforcement
You MUST:
- Add model and VAE metadata entries to registry
- Implement search/filter UI for large resource lists
- Apply resource overrides to NJR (model/VAE filenames)
- Validate selected resources exist in WebUI

### 3. Proof Is Mandatory
For **every MUST**, you MUST provide:
- Full `git diff`
- pytest commands **with captured output**
- Grep output for resource variable usage
- Exact file + line references

### 4. Tests Are Not Optional
You MUST:
- Run all tests specified in TEST PLAN
- Show command + full output
- Fix failures before proceeding

---

## ACKNOWLEDGEMENT STATEMENT (REQUIRED)

By continuing execution, you acknowledge:

> "I will extend the variable metadata registry with Model and VAE resource types, implement  
> filterable checklist UI for large model lists, and ensure resource variables work end-to-end  
> for model comparison experiments. I will provide verifiable proof of all changes."

---

# PR METADATA

## PR ID
`PR-LEARN-021-Resource-Variable-Support`

## Related Canonical Sections
- **D-LEARN-002 §2.2.2**: Resource selection variable requirements
- **D-LEARN-002 §6.2**: Phase 2 implementation roadmap
- **PR-LEARN-020**: Discrete variable foundation
- **Architecture v2.6 §3.2**: NJR-only execution

---

# INTENT (MANDATORY)

## What This PR Does

This PR implements **Phase 2** of the variable type extension, adding support for **resource selection variables** (Model, VAE) in the learning pipeline. It extends the metadata registry established in PR-LEARN-020 and enhances the checklist UI with search/filter capabilities for large resource lists.

**Key Capabilities Added**:
1. Model and VAE metadata entries in `LEARNING_VARIABLES`
2. Enhanced checklist UI with search/filter box
3. Model/VAE selection for comparison experiments
4. Resource validation (selected resources exist in WebUI)
5. Model metadata display (SD version, file size) - optional enhancement

**Backward Compatibility**: Numeric and discrete variables from PR-LEARN-020 continue to work unchanged.

## What This PR Does NOT Do

- Does NOT implement composite LoRA variables - deferred to PR-LEARN-022
- Does NOT add model auto-detection or recommendations
- Does NOT modify model loading or caching mechanisms
- Does NOT change PromptPack or stage card core logic

---

# SCOPE OF CHANGE (EXPLICIT)

## Files TO BE MODIFIED (REQUIRED)

### `src/learning/variable_metadata.py`
**Purpose**: Add Model and VAE resource variable metadata

**Specific Changes**:

#### Change 1: Add model metadata entry
**Location**: Inside `LEARNING_VARIABLES` dict (after "scheduler" entry)

**Add**:
```python
"model": VariableMetadata(
    name="model",
    display_name="Model",
    value_type="resource",
    config_path="txt2img.model",
    ui_component="checklist",
    resource_key="models",
    constraints={"supports_filter": True, "display_metadata": True}
),
```

#### Change 2: Add VAE metadata entry
**Location**: Inside `LEARNING_VARIABLES` dict (after "model" entry)

**Add**:
```python
"vae": VariableMetadata(
    name="vae",
    display_name="VAE",
    value_type="resource",
    config_path="txt2img.vae",
    ui_component="checklist",
    resource_key="vaes",
    constraints={"supports_filter": True, "display_metadata": False}
),
```

**Verification**:
- Registry now has 8 variables (4 numeric, 2 discrete, 2 resource)
- Resource variables have `value_type="resource"` and `resource_key` set
- Both use checklist UI component
- Constraints indicate filter support

---

### `src/gui/views/experiment_design_panel.py`
**Purpose**: Enhance checklist UI with search/filter capabilities

**Specific Changes**:

#### Change 1: Add search box to checklist frame
**Location**: In `_populate_checklist()` method, before checkbutton creation (~line 450)

**Add**:
```python
# PR-LEARN-021: Add search/filter box for large resource lists
if meta.constraints.get("supports_filter", False):
    search_frame = ttk.Frame(self.checklist_inner_frame)
    search_frame.pack(fill="x", pady=(0, 5))
    
    ttk.Label(search_frame, text="Filter:").pack(side="left", padx=(0, 5))
    
    self.search_var = tk.StringVar()
    self.search_var.trace_add("write", lambda *args: self._filter_checklist_items(meta))
    
    search_entry = ttk.Entry(search_frame, textvariable=self.search_var)
    search_entry.pack(side="left", fill="x", expand=True)
    
    # Clear button
    clear_btn = ttk.Button(
        search_frame,
        text="✕",
        width=3,
        command=lambda: self.search_var.set("")
    )
    clear_btn.pack(side="left", padx=(5, 0))
```

#### Change 2: Add `_filter_checklist_items()` method
**Location**: After `_populate_checklist()` method (~line 520)

**Implementation**:
```python
def _filter_checklist_items(self, meta) -> None:
    """Filter checklist items based on search text.
    
    PR-LEARN-021: Filters visible checkboxes based on search query.
    """
    search_text = self.search_var.get().lower()
    
    # Show/hide checkbuttons based on filter
    for widget in self.checklist_inner_frame.winfo_children():
        if isinstance(widget, ttk.Checkbutton):
            text = widget.cget("text").lower()
            if search_text in text:
                widget.pack(anchor="w", pady=2)
            else:
                widget.pack_forget()
    
    # Update count to reflect visible items
    self._update_choice_count()
```

#### Change 3: Add model metadata display (optional)
**Location**: In `_populate_checklist()` method, when creating checkbuttons for models

**Add (if display_metadata is True)**:
```python
# PR-LEARN-021: Display model metadata if available
if meta.constraints.get("display_metadata", False) and meta.resource_key == "models":
    # Create frame for checkbox + metadata
    item_frame = ttk.Frame(self.checklist_inner_frame)
    item_frame.pack(fill="x", anchor="w", pady=2)
    
    # Checkbox
    var = tk.BooleanVar(value=False)
    cb = ttk.Checkbutton(item_frame, text=choice, variable=var)
    cb.pack(side="left")
    
    # Metadata label (SD version, file size, etc.)
    metadata_text = self._get_model_metadata(choice)
    if metadata_text:
        metadata_label = ttk.Label(
            item_frame,
            text=metadata_text,
            foreground="gray",
            font=("TkDefaultFont", 8)
        )
        metadata_label.pack(side="left", padx=(10, 0))
    
    self.choice_vars[choice] = var
else:
    # Standard checkbox (for VAE or non-metadata models)
    var = tk.BooleanVar(value=False)
    cb = ttk.Checkbutton(self.checklist_inner_frame, text=choice, variable=var)
    cb.pack(anchor="w", pady=2)
    self.choice_vars[choice] = var
```

#### Change 4: Add `_get_model_metadata()` helper method
**Location**: After `_filter_checklist_items()` method

**Implementation**:
```python
def _get_model_metadata(self, model_name: str) -> str:
    """Get metadata string for model display.
    
    PR-LEARN-021: Extracts SD version and file size from model name/cache.
    Returns empty string if metadata not available.
    """
    # Try to determine SD version from name
    metadata_parts = []
    
    if "xl" in model_name.lower() or "sdxl" in model_name.lower():
        metadata_parts.append("SDXL")
    elif "sd1" in model_name.lower() or "v1-5" in model_name.lower():
        metadata_parts.append("SD 1.5")
    elif "sd2" in model_name.lower():
        metadata_parts.append("SD 2.x")
    
    # Could add file size if available from cache
    # For now, just return version
    
    return " | ".join(metadata_parts) if metadata_parts else ""
```

**Verification**:
- Search box appears for model/VAE variables
- Filtering works in real-time as user types
- Clear button resets search
- Metadata display shows SD version for models (optional)

---

### `src/gui/controllers/learning_controller.py`
**Purpose**: Add resource validation

**Specific Changes**:

#### Change 1: Add `_validate_selected_resources()` method
**Location**: After `_validate_baseline_config()` method (~line 460)

**Implementation**:
```python
def _validate_selected_resources(
    self,
    selected_items: list[str],
    resource_key: str
) -> tuple[bool, str]:
    """Validate that selected resources exist in WebUI.
    
    PR-LEARN-021: Checks selected models/VAEs against available resources.
    
    Args:
        selected_items: List of selected resource names
        resource_key: Resource type ("models", "vaes", etc.)
    
    Returns:
        (is_valid, error_message)
    """
    import logging
    logger = logging.getLogger(__name__)
    
    # Get available resources
    available = []
    if self.app_controller:
        try:
            resources = self.app_controller._app_state.resources
            available = resources.get(resource_key, [])
        except Exception as exc:
            logger.error(f"[LearningController] Failed to get available {resource_key}: {exc}")
            return False, f"Cannot validate {resource_key}: resource lookup failed"
    
    if not available:
        return False, f"No {resource_key} available in WebUI"
    
    # Check each selected item
    missing = []
    for item in selected_items:
        if item not in available:
            missing.append(item)
    
    if missing:
        return False, f"Selected {resource_key} not found: {', '.join(missing)}"
    
    return True, ""
```

#### Change 2: Call validation in `_generate_variant_values()`
**Location**: In `_generate_variant_values()` method, in the resource branch

**Modify**:
```python
elif meta.value_type in ["discrete", "resource"]:  # PR-LEARN-021: Handle resource type
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
    
    # PR-LEARN-021: Validate resource selections
    if meta.value_type == "resource" and selected:
        is_valid, error_msg = self._validate_selected_resources(selected, meta.resource_key)
        if not is_valid:
            logger.error(f"[LearningController]   Resource validation failed: {error_msg}")
            raise ValueError(f"Invalid resource selection: {error_msg}")
    
    logger.info(f"[LearningController]   Generated {len(selected)} {meta.value_type} values: {selected}")
    return selected
```

**Verification**:
- Validation checks selected resources against available list
- Clear error messages for missing resources
- Logging for debugging

---

### `src/gui/views/experiment_design_panel.py` (validation)
**Purpose**: Add resource-specific validation

**Specific Changes**:

**Location**: In `_validate_experiment_data()` method

**Add**:
```python
# PR-LEARN-021: Resource-specific validation
if meta.value_type == "resource":
    selected = data.get("selected_items", [])
    if not selected:
        return f"At least one {meta.display_name} must be selected"
    
    # Optionally validate resources exist (could be expensive)
    # For now, rely on controller-level validation during build
```

---

## Files VERIFIED UNCHANGED
- `src/pipeline/job_models_v2.py` - NJR structure unchanged
- `src/controller/learning_execution_controller.py` - Execution logic unchanged
- `src/learning/learning_plan.py` - Plan structures unchanged

---

# ARCHITECTURAL COMPLIANCE

- [x] NJR‑only execution - resource variables build NJR directly
- [x] Metadata registry pattern - consistent with PR-LEARN-020
- [x] Resource discovery via AppStateV2.resources - no direct WebUI calls
- [x] Validation before execution - prevents invalid submissions
- [x] Backward compatible - numeric and discrete variables work unchanged

---

# IMPLEMENTATION STEPS (ORDERED, NON‑OPTIONAL)

## Step 1: Extend Variable Metadata Registry

**File**: `src/learning/variable_metadata.py`

**Action**: Add model and VAE entries to `LEARNING_VARIABLES` dict

**Verification**:
```bash
grep -n "\"model\":" src/learning/variable_metadata.py
grep -n "\"vae\":" src/learning/variable_metadata.py
# Expected: 2 matches each
```

---

## Step 2: Enhance Checklist UI with Search/Filter

**File**: `src/gui/views/experiment_design_panel.py`

**Action**:
1. Add search box frame to checklist
2. Implement `_filter_checklist_items()` method
3. Bind search_var to filter function

**Verification**:
- Search box appears for resource variables
- Filtering works as user types
- Clear button resets filter

---

## Step 3: Add Model Metadata Display (Optional)

**File**: `src/gui/views/experiment_design_panel.py`

**Action**:
1. Add `_get_model_metadata()` helper
2. Enhance checkbutton creation with metadata labels

**Verification**:
- SDXL models show "SDXL" tag
- SD 1.5 models show "SD 1.5" tag

---

## Step 4: Add Resource Validation

**File**: `src/gui/controllers/learning_controller.py`

**Action**:
1. Add `_validate_selected_resources()` method
2. Call validation in `_generate_variant_values()`

**Verification**:
- Validation catches missing resources
- Clear error messages logged

---

## Step 5: Update Tests

**Action**: Create test files for resource variables

---

# TEST PLAN (MANDATORY)

## Unit Tests

### Test 1: Resource Metadata Registry
**File**: `tests/learning/test_variable_metadata_resources.py` (NEW)

```python
"""Tests for resource variable metadata.

PR-LEARN-021: Tests Model and VAE metadata entries.
"""

import pytest
from src.learning.variable_metadata import get_variable_metadata, LEARNING_VARIABLES


def test_model_metadata_entry_exists():
    """Verify Model metadata entry."""
    meta = get_variable_metadata("Model")
    
    assert meta is not None
    assert meta.name == "model"
    assert meta.value_type == "resource"
    assert meta.config_path == "txt2img.model"
    assert meta.resource_key == "models"
    assert meta.constraints.get("supports_filter") is True


def test_vae_metadata_entry_exists():
    """Verify VAE metadata entry."""
    meta = get_variable_metadata("VAE")
    
    assert meta is not None
    assert meta.name == "vae"
    assert meta.value_type == "resource"
    assert meta.config_path == "txt2img.vae"
    assert meta.resource_key == "vaes"


def test_registry_has_eight_variables():
    """Verify registry contains 8 variables after PR-LEARN-021."""
    assert len(LEARNING_VARIABLES) == 8
    
    expected = ["cfg_scale", "steps", "sampler", "scheduler", "denoise_strength", "upscale_factor", "model", "vae"]
    for name in expected:
        assert name in LEARNING_VARIABLES
```

**Run**:
```bash
python -m pytest tests/learning/test_variable_metadata_resources.py -v
```

---

### Test 2: Resource Validation
**File**: `tests/controller/test_learning_controller_resource_validation.py` (NEW)

```python
"""Tests for resource variable validation.

PR-LEARN-021: Tests validation of selected models/VAEs.
"""

import pytest
from src.gui.learning_state import LearningState
from src.gui.controllers.learning_controller import LearningController
from src.learning.learning_record import LearningRecordWriter


@pytest.fixture
def learning_controller():
    """Create learning controller with mock resources."""
    state = LearningState()
    record_writer = LearningRecordWriter()
    
    class MockAppController:
        class MockAppState:
            resources = {
                "models": ["model_a.safetensors", "model_b.safetensors"],
                "vaes": ["vae_a.pt", "vae_b.pt"],
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
    
    return controller


def test_validate_selected_resources_valid():
    """Test validation passes for valid resources."""
    controller = learning_controller()
    
    is_valid, error = controller._validate_selected_resources(
        ["model_a.safetensors", "model_b.safetensors"],
        "models"
    )
    
    assert is_valid
    assert error == ""


def test_validate_selected_resources_missing():
    """Test validation fails for missing resources."""
    controller = learning_controller()
    
    is_valid, error = controller._validate_selected_resources(
        ["model_a.safetensors", "missing_model.safetensors"],
        "models"
    )
    
    assert not is_valid
    assert "missing_model.safetensors" in error


def test_validate_selected_resources_empty_available():
    """Test validation fails when no resources available."""
    state = LearningState()
    record_writer = LearningRecordWriter()
    
    class MockAppController:
        class MockAppState:
            resources = {"models": []}  # Empty
        _app_state = MockAppState()
    
    class MockPipelineController:
        pass
    
    controller = LearningController(
        learning_state=state,
        learning_record_writer=record_writer,
        pipeline_controller=MockPipelineController(),
        app_controller=MockAppController(),
    )
    
    is_valid, error = controller._validate_selected_resources(
        ["model_a.safetensors"],
        "models"
    )
    
    assert not is_valid
    assert "No models available" in error
```

**Run**:
```bash
python -m pytest tests/controller/test_learning_controller_resource_validation.py -v
```

---

## Integration Tests

### Test 3: End-to-End Model Comparison
**File**: `tests/integration/test_learning_model_comparison.py` (NEW)

```python
"""Integration test for model comparison experiment.

PR-LEARN-021: Tests full model resource variable workflow.
"""

import pytest
from src.gui.learning_state import LearningState, LearningExperiment
from src.gui.controllers.learning_controller import LearningController
from src.learning.learning_record import LearningRecordWriter


def test_model_comparison_end_to_end(tmp_path):
    """Test complete model comparison experiment flow."""
    # Setup
    state = LearningState()
    record_writer = LearningRecordWriter(records_path=tmp_path / "records.jsonl")
    
    class MockAppController:
        class MockAppState:
            resources = {
                "models": [
                    "sd_xl_base_1.0.safetensors",
                    "dreamshaper_8.safetensors",
                    "realisticVision_v51.safetensors",
                ],
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
    
    # Create experiment with model variable
    experiment_data = {
        "name": "Model Comparison",
        "description": "Test SDXL vs Dreamshaper",
        "stage": "txt2img",
        "variable_under_test": "Model",
        "selected_items": ["sd_xl_base_1.0.safetensors", "dreamshaper_8.safetensors"],
        "images_per_value": 1,
        "prompt_source": "custom",
        "custom_prompt": "a beautiful landscape",
    }
    
    # Update experiment design
    controller.update_experiment_design(experiment_data)
    
    # Verify experiment created
    assert controller.learning_state.current_experiment is not None
    assert controller.learning_state.current_experiment.variable_under_test == "Model"
    
    # Build plan
    experiment = controller.learning_state.current_experiment
    controller.build_plan(experiment)
    
    # Verify plan has correct variants
    plan = controller.learning_state.plan
    assert len(plan) == 2
    assert plan[0].param_value == "sd_xl_base_1.0.safetensors"
    assert plan[1].param_value == "dreamshaper_8.safetensors"
    
    # Verify values stored
    assert experiment.values == ["sd_xl_base_1.0.safetensors", "dreamshaper_8.safetensors"]


def test_model_comparison_invalid_model_fails(tmp_path):
    """Test validation fails for non-existent model."""
    state = LearningState()
    record_writer = LearningRecordWriter(records_path=tmp_path / "records.jsonl")
    
    class MockAppController:
        class MockAppState:
            resources = {
                "models": ["model_a.safetensors"],
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
    
    # Try to create experiment with invalid model
    experiment_data = {
        "name": "Invalid Model Test",
        "variable_under_test": "Model",
        "selected_items": ["missing_model.safetensors"],
        "images_per_value": 1,
        "prompt_source": "custom",
        "custom_prompt": "test",
    }
    
    controller.update_experiment_design(experiment_data)
    experiment = controller.learning_state.current_experiment
    
    # Build plan should fail validation
    with pytest.raises(ValueError, match="Invalid resource selection"):
        controller.build_plan(experiment)
```

**Run**:
```bash
python -m pytest tests/integration/test_learning_model_comparison.py -v
```

---

## GUI Tests

### Test 4: Search Filter UI
**File**: `tests/gui/test_experiment_design_panel_search.py` (NEW)

```python
"""Tests for checklist search/filter functionality.

PR-LEARN-021: Tests search box and filtering for resource variables.
"""

import tkinter as tk
import pytest
from src.gui.views.experiment_design_panel import ExperimentDesignPanel
from src.gui.learning_state import LearningState
from src.gui.controllers.learning_controller import LearningController


@pytest.fixture
def root():
    """Create Tk root."""
    root = tk.Tk()
    yield root
    root.destroy()


def test_search_box_appears_for_model_variable(root):
    """Test search box appears for Model variable."""
    state = LearningState()
    
    class MockAppController:
        class MockAppState:
            resources = {
                "models": ["sd_xl_base.safetensors", "dreamshaper_8.safetensors"],
            }
        _app_state = MockAppState()
    
    class MockPipelineController:
        pass
    
    controller = LearningController(
        learning_state=state,
        pipeline_controller=MockPipelineController(),
        app_controller=MockAppController(),
    )
    
    panel = ExperimentDesignPanel(root, learning_controller=controller)
    
    # Select Model variable
    panel.variable_var.set("Model")
    panel._on_variable_changed()
    
    # Verify search box exists
    assert hasattr(panel, 'search_var')


def test_search_filters_checklist_items(root):
    """Test search filters checklist."""
    state = LearningState()
    
    class MockAppController:
        class MockAppState:
            resources = {
                "models": [
                    "sd_xl_base_1.0.safetensors",
                    "sd-v1-5-pruned.safetensors",
                    "dreamshaper_8.safetensors",
                ],
            }
        _app_state = MockAppState()
    
    class MockPipelineController:
        pass
    
    controller = LearningController(
        learning_state=state,
        pipeline_controller=MockPipelineController(),
        app_controller=MockAppController(),
    )
    
    panel = ExperimentDesignPanel(root, learning_controller=controller)
    
    # Show model checklist
    panel.variable_var.set("Model")
    panel._on_variable_changed()
    
    # Filter for "sd"
    panel.search_var.set("sd")
    panel._filter_checklist_items(get_variable_metadata("Model"))
    
    # Count visible checkboxes
    visible = 0
    for widget in panel.checklist_inner_frame.winfo_children():
        if isinstance(widget, ttk.Checkbutton) and widget.winfo_ismapped():
            visible += 1
    
    # Should show 2 models (sd_xl and sd-v1-5)
    assert visible == 2


def test_clear_button_resets_search(root):
    """Test clear button resets search filter."""
    state = LearningState()
    
    class MockAppController:
        class MockAppState:
            resources = {"models": ["model_a.safetensors", "model_b.safetensors"]}
        _app_state = MockAppState()
    
    class MockPipelineController:
        pass
    
    controller = LearningController(
        learning_state=state,
        pipeline_controller=MockPipelineController(),
        app_controller=MockAppController(),
    )
    
    panel = ExperimentDesignPanel(root, learning_controller=controller)
    
    # Show checklist and set search
    panel.variable_var.set("Model")
    panel._on_variable_changed()
    
    panel.search_var.set("test")
    assert panel.search_var.get() == "test"
    
    # Clear
    panel.search_var.set("")
    assert panel.search_var.get() == ""
```

**Run**:
```bash
python -m pytest tests/gui/test_experiment_design_panel_search.py -v
```

---

## Commands Executed

```bash
# Unit tests
python -m pytest tests/learning/test_variable_metadata_resources.py -v
python -m pytest tests/controller/test_learning_controller_resource_validation.py -v

# Integration test
python -m pytest tests/integration/test_learning_model_comparison.py -v

# GUI tests
python -m pytest tests/gui/test_experiment_design_panel_search.py -v

# Verify resource variable support
grep -n "\"model\":" src/learning/variable_metadata.py
grep -n "\"vae\":" src/learning/variable_metadata.py

# Verify backward compatibility
python -m pytest tests/learning/ -v
python -m pytest tests/integration/test_learning_sampler_comparison.py -v
```

---

# VERIFICATION & PROOF

## git diff
```bash
git diff src/learning/variable_metadata.py
git diff src/gui/views/experiment_design_panel.py
git diff src/gui/controllers/learning_controller.py
```

**Expected changes**:
- MODIFIED: `src/learning/variable_metadata.py` (+20 lines for model/VAE)
- MODIFIED: `src/gui/views/experiment_design_panel.py` (+100 lines for search/filter)
- MODIFIED: `src/gui/controllers/learning_controller.py` (+50 lines for validation)

## git status
```bash
git status --short
```

**Expected**:
```
M  src/learning/variable_metadata.py
M  src/gui/views/experiment_design_panel.py
M  src/gui/controllers/learning_controller.py
A  tests/learning/test_variable_metadata_resources.py
A  tests/controller/test_learning_controller_resource_validation.py
A  tests/integration/test_learning_model_comparison.py
A  tests/gui/test_experiment_design_panel_search.py
```

---

# ARCHITECTURAL COMPLIANCE VERIFICATION

## Resource Variable System
- [x] Model and VAE metadata entries added
- [x] Resource type uses same checklist UI as discrete
- [x] Search/filter enhances UX for large lists
- [x] Validation prevents invalid resource selection

## Backward Compatibility
- [x] Numeric variables (CFG, Steps) work unchanged
- [x] Discrete variables (Sampler, Scheduler) work unchanged
- [x] PR-LEARN-020 tests continue to pass

## NJR Execution
- [x] Resource overrides applied to NJR via config_path
- [x] Model/VAE filenames propagate to run_metadata.json
- [x] No legacy config paths

---

# GOLDEN PATH CONFIRMATION

**User Flow: Create Model Comparison Experiment**

1. User opens Learning tab
2. User enters experiment name: "SDXL vs Dreamshaper"
3. User selects "Model" from variable dropdown
4. UI shows checklist with search box
5. User types "sd" in search box
6. Checklist filters to SD models only
7. User checks "sd_xl_base_1.0.safetensors" and "dreamshaper_8.safetensors"
8. Counter shows "2 items selected"
9. User sets images per variant: 3
10. User enters prompt: "a cyberpunk city"
11. User clicks "Build Preview Only"
12. Plan table shows 2 variants
13. User clicks "Run Experiment"
14. Jobs submitted with correct model in NJR
15. run_metadata.json contains correct model for each variant

**Expected Behavior**:
- ✅ Search filter works in real-time
- ✅ Validation catches missing models
- ✅ NJRs have correct model applied
- ✅ Config propagates to run_metadata.json
- ✅ Existing numeric/discrete experiments unaffected

---

# COMPLETION CRITERIA

This PR is complete when:

1. ✅ Model and VAE metadata entries added to registry
2. ✅ Search/filter UI implemented and functional
3. ✅ Resource validation implemented
4. ✅ All unit tests pass (8+ tests)
5. ✅ Integration test demonstrates model comparison
6. ✅ GUI tests verify search functionality
7. ✅ Backward compatibility maintained
8. ✅ Documentation updated

---

**Next Steps**:
1. Execute this PR
2. Validate model/VAE experiments work in UI
3. Generate PR-LEARN-022 for composite LoRA variables
4. Complete Phase 3 implementation
