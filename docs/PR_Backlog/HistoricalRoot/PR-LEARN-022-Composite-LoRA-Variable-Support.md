# PR-LEARN-022: Composite LoRA Variable Support

**Related Discovery**: D-LEARN-002  
**Architecture Version**: v2.6  
**PR Date**: 2026-01-10  
**Dependencies**: PR-LEARN-021 (Resource Variable Support)  
**Sequence**: Phase 3 of 3 (PR-LEARN-020 → PR-LEARN-021 → PR-LEARN-022)

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
   - Variable metadata system (established in PR-LEARN-020/021)
   - Composite variable handling with LoRAs

3. This PR **MUST**:
   - Add LoRA Strength composite variable to metadata registry
   - Implement LoRA selector UI retrieving from stage card state
   - Support both "Test LoRA Strength" and "Test LoRA Selection" modes
   - Apply LoRA overrides to NJR.lora_tags correctly

---

## ABSOLUTE EXECUTION RULES (NON‑NEGOTIABLE)

### 1. Scope Completion
- You MUST implement **100% of the PR scope**
- You MUST create/modify **every file listed**
- Partial implementation is **explicitly forbidden**

### 2. Composite LoRA System Enforcement
You MUST:
- Add lora_strength composite metadata entry
- Retrieve current LoRAs from stage card state
- Support dual modes: strength sweep vs LoRA comparison
- Apply LoRA overrides to NJR.lora_tags field
- Validate selected LoRA exists in stage card

### 3. Proof Is Mandatory
For **every MUST**, you MUST provide:
- Full `git diff`
- pytest commands **with captured output**
- Grep output for LoRA variable usage
- Exact file + line references

### 4. Tests Are Not Optional
You MUST:
- Run all tests specified in TEST PLAN
- Show command + full output
- Fix failures before proceeding

---

## ACKNOWLEDGEMENT STATEMENT (REQUIRED)

By continuing execution, you acknowledge:

> "I will implement composite LoRA variables with strength sweeping and LoRA comparison modes,  
> retrieve LoRAs from stage card state, apply overrides to NJR.lora_tags, and ensure full  
> backward compatibility with all previous variable types. I will provide verifiable proof."

---

# PR METADATA

## PR ID
`PR-LEARN-022-Composite-LoRA-Variable-Support`

## Related Canonical Sections
- **D-LEARN-002 §2.2.3**: Composite variable requirements
- **D-LEARN-002 §6.3**: Phase 3 implementation roadmap
- **D-LEARN-002 §8.1**: LoRA state retrieval
- **D-LEARN-002 §8.2**: NJR LoRA application
- **PR-LEARN-020**: Metadata foundation
- **PR-LEARN-021**: Resource variables

---

# INTENT (MANDATORY)

## What This PR Does

This PR implements **Phase 3** (final phase) of the variable type extension, adding support for **composite LoRA variables** in the learning pipeline. LoRAs are unique because they require both **selection** (which LoRA) and **value** (strength) specification.

**Key Capabilities Added**:
1. LoRA Strength composite variable metadata
2. LoRA selector UI populated from stage card state
3. Two modes:
   - **Mode 1 (Strength Sweep)**: Test single LoRA at multiple strengths
   - **Mode 2 (LoRA Comparison)**: Test multiple LoRAs at fixed strength
4. LoRA override application to NJR.lora_tags
5. Validation that selected LoRA exists in stage card

**Backward Compatibility**: Numeric, discrete, and resource variables continue to work unchanged.

## What This PR Does NOT Do

- Does NOT add LoRA stacking (testing multiple LoRAs simultaneously)
- Does NOT implement multi-variable experiments
- Does NOT modify LoRA loading or caching mechanisms
- Does NOT change stage card LoRA management

---

# SCOPE OF CHANGE (EXPLICIT)

## Files TO BE MODIFIED (REQUIRED)

### `src/learning/variable_metadata.py`
**Purpose**: Add LoRA Strength composite variable metadata

**Specific Changes**:

#### Change 1: Add lora_strength metadata entry
**Location**: Inside `LEARNING_VARIABLES` dict (after "vae" entry)

**Add**:
```python
"lora_strength": VariableMetadata(
    name="lora_strength",
    display_name="LoRA Strength",
    value_type="composite",
    config_path="lora_override",  # Special handling in controller
    ui_component="lora_composite",
    constraints={
        "lora_source": "stage_card",
        "min_strength": 0.0,
        "max_strength": 2.0,
        "default_step": 0.1,
        "supports_comparison_mode": True,  # Can test different LoRAs
    }
),
```

**Verification**:
- Registry now has 9 variables (4 numeric, 2 discrete, 2 resource, 1 composite)
- Composite variable has special config_path and ui_component

---

### `src/gui/controllers/learning_controller.py`
**Purpose**: Add LoRA retrieval and composite value generation

**Specific Changes**:

#### Change 1: Add `_get_current_loras()` method
**Location**: After `_get_baseline_config()` method (~line 580)

**Implementation**:
```python
def _get_current_loras(self) -> list[dict[str, Any]]:
    """Get currently selected LoRAs from stage card state.
    
    PR-LEARN-022: Retrieves enabled LoRAs from baseline config for LoRA variable.
    
    Returns:
        List of LoRA dicts: [{"name": "...", "strength": ..., "enabled": True}, ...]
    """
    import logging
    logger = logging.getLogger(__name__)
    
    if not self.app_controller:
        logger.warning("[LearningController] No app_controller, cannot get LoRAs")
        return []
    
    # Get baseline config from stage cards
    try:
        baseline = self._get_baseline_config()
        txt2img = baseline.get("txt2img", {})
        loras = txt2img.get("lora_strengths", [])
        
        # Filter to enabled only
        enabled_loras = [l for l in loras if l.get("enabled", False)]
        
        logger.info(f"[LearningController] Found {len(enabled_loras)} enabled LoRAs in stage card")
        return enabled_loras
        
    except Exception as exc:
        logger.error(f"[LearningController] Failed to get current LoRAs: {exc}")
        return []
```

**Verification**:
- Retrieves LoRAs from baseline config
- Filters to enabled only
- Returns list of LoRA dicts

---

#### Change 2: Extend `_generate_variant_values()` for composite
**Location**: In `_generate_variant_values()` method, after resource handling

**Add**:
```python
elif meta.value_type == "composite":
    # PR-LEARN-022: Composite variable (LoRA Strength)
    
    # Determine mode: strength sweep or LoRA comparison
    comparison_mode = experiment.metadata.get("comparison_mode", False)
    
    if comparison_mode:
        # Mode 2: Compare different LoRAs at fixed strength
        selected_loras = experiment.metadata.get("selected_loras", [])
        fixed_strength = float(experiment.metadata.get("fixed_strength", 1.0))
        
        if not selected_loras:
            # Get all enabled LoRAs from stage card
            available_loras = self._get_current_loras()
            selected_loras = [l["name"] for l in available_loras]
        
        values = [{"name": lora, "weight": fixed_strength} for lora in selected_loras]
        logger.info(f"[LearningController]   Generated {len(values)} LoRA comparison variants at strength {fixed_strength}")
    
    else:
        # Mode 1: Test single LoRA at multiple strengths
        lora_name = experiment.metadata.get("lora_name")
        
        if not lora_name:
            # Try to get first enabled LoRA
            available_loras = self._get_current_loras()
            if available_loras:
                lora_name = available_loras[0]["name"]
                logger.warning(f"[LearningController]   No LoRA specified, using first enabled: {lora_name}")
            else:
                raise ValueError("No LoRA specified and no enabled LoRAs in stage card")
        
        # Generate strength range
        start = float(experiment.metadata.get("strength_start", meta.constraints.get("min_strength", 0.5)))
        end = float(experiment.metadata.get("strength_end", meta.constraints.get("max_strength", 1.5)))
        step = float(experiment.metadata.get("strength_step", meta.constraints.get("default_step", 0.1)))
        
        strengths = self._generate_values_from_range(start, end, step)
        
        values = [{"name": lora_name, "weight": s} for s in strengths]
        logger.info(f"[LearningController]   Generated {len(values)} strength variants for {lora_name}")
    
    return values
```

**Verification**:
- Supports both strength sweep and LoRA comparison modes
- Falls back to first enabled LoRA if none specified
- Comprehensive logging

---

#### Change 3: Extend `_apply_variant_override_with_metadata()` for LoRA
**Location**: In `_apply_variant_override_with_metadata()` method, after standard path application

**Add**:
```python
# PR-LEARN-022: Special handling for composite LoRA variable
if meta.value_type == "composite" and isinstance(value, dict):
    # value = {"name": "CharacterLoRA", "weight": 0.8}
    # Store in lora_override for later NJR application
    config.setdefault("lora_override", {}).update(value)
    logger.info(f"[LearningController] Applied LoRA override: {value['name']} @ {value['weight']}")
else:
    # Standard config path application
    final_key = keys[-1]
    target[final_key] = value
    logger.info(f"[LearningController] Applied override: {meta.config_path} = {value}")
```

---

#### Change 4: Modify `_build_variant_njr()` to apply LoRA override
**Location**: In `_build_variant_njr()` method, after building stage_chain, before returning record

**Add**:
```python
# PR-LEARN-022: Apply LoRA override if present
lora_override = final_config.get("lora_override")
if lora_override and isinstance(lora_override, dict):
    from src.pipeline.job_models_v2 import LoRATag
    
    lora_name = lora_override["name"]
    lora_weight = float(lora_override["weight"])
    
    logger.info(f"[LearningController] Applying LoRA override to NJR: {lora_name} @ {lora_weight}")
    
    # Remove any existing tag with same name
    record.lora_tags = [tag for tag in record.lora_tags if tag.name != lora_name]
    
    # Add new tag with override weight
    new_tag = LoRATag(name=lora_name, weight=lora_weight)
    record.lora_tags.append(new_tag)
    
    logger.info(f"[LearningController]   NJR lora_tags: {[f'{t.name}@{t.weight}' for t in record.lora_tags]}")
```

**Verification**:
- LoRA override applied to NJR.lora_tags
- Existing tag with same name replaced
- Logging shows final lora_tags

---

### `src/gui/views/experiment_design_panel.py`
**Purpose**: Add LoRA composite UI widget

**Specific Changes**:

#### Change 1: Add lora_frame initialization
**Location**: In `__init__` after checklist_frame creation (~line 60)

**Add**:
```python
# PR-LEARN-022: Build LoRA composite frame (hidden by default)
self.lora_frame = ttk.LabelFrame(self, text="LoRA Configuration", padding=5)
self.lora_frame.columnconfigure(0, weight=1)

# Initially hide
self.lora_frame.grid_remove()
```

#### Change 2: Extend `_on_variable_changed()` to show LoRA widget
**Location**: In `_on_variable_changed()` method

**Add**:
```python
# Show appropriate widget based on ui_component
if meta.ui_component == "range":
    self._show_range_widget()
elif meta.ui_component == "checklist":
    self._show_checklist_widget(meta)
elif meta.ui_component == "lora_composite":  # PR-LEARN-022
    self._show_lora_composite_widget(meta)
else:
    self._show_range_widget()
```

#### Change 3: Add `_show_lora_composite_widget()` method
**Location**: After `_show_checklist_widget()` method (~line 240)

**Implementation**:
```python
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
```

**Verification**:
- LoRA frame appears for LoRA Strength variable
- Mode selector switches between strength sweep and comparison
- LoRA selector populated from stage card
- Strength range UI works like numeric variables
- Comparison UI shows LoRA checklist + fixed strength

---

#### Change 4: Update `_on_build_preview()` to collect LoRA metadata
**Location**: In `_on_build_preview()` method, in experiment_data dict

**Add**:
```python
# Collect form data
experiment_data = {
    # ... existing fields ...
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
```

---

#### Change 5: Update validation for LoRA variable
**Location**: In `_validate_experiment_data()` method

**Add**:
```python
# PR-LEARN-022: Composite LoRA validation
elif meta.value_type == "composite":
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
```

---

## Files VERIFIED UNCHANGED
- `src/pipeline/job_models_v2.py` - NJR structure includes lora_tags field (already exists)
- `src/controller/learning_execution_controller.py` - Execution logic unchanged
- Stage card files - LoRA management unchanged

---

# ARCHITECTURAL COMPLIANCE

- [x] NJR‑only execution - LoRA overrides applied to NJR.lora_tags
- [x] Stage card config source - LoRAs retrieved from baseline config
- [x] No PipelineConfig - composite metadata is separate
- [x] Metadata-driven design - consistent with PR-LEARN-020/021
- [x] Backward compatible - all previous variable types work unchanged

---

# IMPLEMENTATION STEPS (ORDERED, NON‑OPTIONAL)

## Step 1: Extend Variable Metadata Registry

**File**: `src/learning/variable_metadata.py`

**Action**: Add lora_strength entry to `LEARNING_VARIABLES`

**Verification**:
```bash
grep -n "lora_strength" src/learning/variable_metadata.py
# Expected: Match for metadata entry
```

---

## Step 2: Add LoRA Retrieval to Controller

**File**: `src/gui/controllers/learning_controller.py`

**Action**: Add `_get_current_loras()` method

**Verification**: Method retrieves LoRAs from baseline config

---

## Step 3: Extend Value Generation for Composite

**File**: `src/gui/controllers/learning_controller.py`

**Action**: Add composite handling to `_generate_variant_values()`

**Verification**: Both strength sweep and comparison modes work

---

## Step 4: Extend Override Application for LoRA

**File**: `src/gui/controllers/learning_controller.py`

**Action**: Add LoRA special handling to `_apply_variant_override_with_metadata()`

**Verification**: lora_override dict stored correctly

---

## Step 5: Apply LoRA Override to NJR

**File**: `src/gui/controllers/learning_controller.py`

**Action**: Modify `_build_variant_njr()` to apply LoRA override to lora_tags

**Verification**: NJR.lora_tags contains correct LoRA with override weight

---

## Step 6: Build LoRA Composite UI

**File**: `src/gui/views/experiment_design_panel.py`

**Action**: Add lora_frame, mode selector, and dynamic content builders

**Verification**:
- Mode selector switches UI
- LoRA selector populated from stage card
- Strength range UI functional
- Comparison checklist works

---

# TEST PLAN (MANDATORY)

## Unit Tests

### Test 1: Composite Metadata Entry
**File**: `tests/learning/test_variable_metadata_composite.py` (NEW)

```python
"""Tests for composite LoRA variable metadata.

PR-LEARN-022: Tests LoRA Strength metadata entry.
"""

import pytest
from src.learning.variable_metadata import get_variable_metadata, LEARNING_VARIABLES


def test_lora_strength_metadata_exists():
    """Verify LoRA Strength metadata entry."""
    meta = get_variable_metadata("LoRA Strength")
    
    assert meta is not None
    assert meta.name == "lora_strength"
    assert meta.value_type == "composite"
    assert meta.ui_component == "lora_composite"
    assert meta.constraints.get("lora_source") == "stage_card"


def test_registry_has_nine_variables():
    """Verify registry contains 9 variables after PR-LEARN-022."""
    assert len(LEARNING_VARIABLES) == 9
```

**Run**:
```bash
python -m pytest tests/learning/test_variable_metadata_composite.py -v
```

---

### Test 2: LoRA Retrieval
**File**: `tests/controller/test_learning_controller_lora_retrieval.py` (NEW)

```python
"""Tests for LoRA retrieval from stage cards.

PR-LEARN-022: Tests _get_current_loras() method.
"""

import pytest
from src.gui.learning_state import LearningState
from src.gui.controllers.learning_controller import LearningController


def test_get_current_loras():
    """Test LoRA retrieval from baseline config."""
    state = LearningState()
    
    class MockAppController:
        pass
    
    class MockPipelineController:
        pass
    
    controller = LearningController(
        learning_state=state,
        pipeline_controller=MockPipelineController(),
        app_controller=MockAppController(),
    )
    
    # Mock _get_baseline_config
    controller._get_baseline_config = lambda: {
        "txt2img": {
            "lora_strengths": [
                {"name": "LoRA_A", "strength": 0.8, "enabled": True},
                {"name": "LoRA_B", "strength": 1.0, "enabled": False},
                {"name": "LoRA_C", "strength": 0.6, "enabled": True},
            ]
        }
    }
    
    loras = controller._get_current_loras()
    
    assert len(loras) == 2  # Only enabled
    assert loras[0]["name"] == "LoRA_A"
    assert loras[1]["name"] == "LoRA_C"
```

**Run**:
```bash
python -m pytest tests/controller/test_learning_controller_lora_retrieval.py -v
```

---

### Test 3: Composite Value Generation
**File**: `tests/controller/test_learning_controller_composite_values.py` (NEW)

```python
"""Tests for composite LoRA value generation.

PR-LEARN-022: Tests strength sweep and comparison modes.
"""

import pytest
from src.gui.learning_state import LearningState, LearningExperiment
from src.gui.controllers.learning_controller import LearningController
from src.learning.learning_record import LearningRecordWriter


@pytest.fixture
def learning_controller():
    """Create controller with mock LoRAs."""
    state = LearningState()
    record_writer = LearningRecordWriter()
    
    class MockAppController:
        pass
    
    class MockPipelineController:
        pass
    
    controller = LearningController(
        learning_state=state,
        learning_record_writer=record_writer,
        pipeline_controller=MockPipelineController(),
        app_controller=MockAppController(),
    )
    
    # Mock LoRA retrieval
    controller._get_current_loras = lambda: [
        {"name": "LoRA_A", "strength": 0.8, "enabled": True},
        {"name": "LoRA_B", "strength": 1.0, "enabled": True},
    ]
    
    return controller


def test_generate_lora_strength_sweep_values():
    """Test strength sweep mode."""
    controller = learning_controller()
    
    experiment = LearningExperiment(
        name="Test LoRA Strength",
        variable_under_test="LoRA Strength",
        metadata={
            "comparison_mode": False,
            "lora_name": "LoRA_A",
            "strength_start": 0.5,
            "strength_end": 1.0,
            "strength_step": 0.25,
        }
    )
    
    values = controller._generate_variant_values(experiment)
    
    assert len(values) == 3  # 0.5, 0.75, 1.0
    assert all(isinstance(v, dict) for v in values)
    assert all(v["name"] == "LoRA_A" for v in values)
    assert values[0]["weight"] == 0.5
    assert values[1]["weight"] == 0.75
    assert values[2]["weight"] == 1.0


def test_generate_lora_comparison_values():
    """Test LoRA comparison mode."""
    controller = learning_controller()
    
    experiment = LearningExperiment(
        name="Test LoRA Comparison",
        variable_under_test="LoRA Strength",
        metadata={
            "comparison_mode": True,
            "selected_loras": ["LoRA_A", "LoRA_B"],
            "fixed_strength": 0.9,
        }
    )
    
    values = controller._generate_variant_values(experiment)
    
    assert len(values) == 2
    assert values[0] == {"name": "LoRA_A", "weight": 0.9}
    assert values[1] == {"name": "LoRA_B", "weight": 0.9}
```

**Run**:
```bash
python -m pytest tests/controller/test_learning_controller_composite_values.py -v
```

---

### Test 4: LoRA Override to NJR
**File**: `tests/controller/test_learning_controller_lora_njr.py` (NEW)

```python
"""Tests for LoRA override application to NJR.

PR-LEARN-022: Tests lora_tags manipulation.
"""

import pytest
from src.gui.learning_state import LearningExperiment, LearningVariant
from src.pipeline.job_models_v2 import LoRATag


def test_lora_override_applied_to_njr():
    """Test LoRA override creates correct lora_tags."""
    # This would test _build_variant_njr with lora_override
    # Simplified example:
    
    from src.gui.learning_state import LearningState
    from src.gui.controllers.learning_controller import LearningController
    from src.learning.learning_record import LearningRecordWriter
    
    state = LearningState()
    record_writer = LearningRecordWriter()
    
    # Mock controller setup...
    # Build variant with LoRA override
    # Verify record.lora_tags contains correct LoRA
    
    # Expected behavior:
    # record.lora_tags = [LoRATag(name="TestLoRA", weight=0.8)]
```

**Run**:
```bash
python -m pytest tests/controller/test_learning_controller_lora_njr.py -v
```

---

## Integration Tests

### Test 5: End-to-End LoRA Strength Sweep
**File**: `tests/integration/test_learning_lora_strength_sweep.py` (NEW)

```python
"""Integration test for LoRA strength sweep experiment.

PR-LEARN-022: Tests full LoRA composite variable workflow.
"""

import pytest
from src.gui.learning_state import LearningState
from src.gui.controllers.learning_controller import LearningController
from src.learning.learning_record import LearningRecordWriter


def test_lora_strength_sweep_end_to_end(tmp_path):
    """Test complete LoRA strength sweep flow."""
    state = LearningState()
    record_writer = LearningRecordWriter(records_path=tmp_path / "records.jsonl")
    
    # Setup mocks...
    
    # Create experiment
    experiment_data = {
        "name": "Find Optimal LoRA Strength",
        "variable_under_test": "LoRA Strength",
        "lora_mode": "strength",
        "lora_name": "CharacterLoRA",
        "strength_start": 0.6,
        "strength_end": 1.2,
        "strength_step": 0.2,
        "comparison_mode": False,
        "images_per_value": 1,
        "prompt_source": "custom",
        "custom_prompt": "portrait of a character",
    }
    
    # Update and build
    controller.update_experiment_design(experiment_data)
    experiment = controller.learning_state.current_experiment
    controller.build_plan(experiment)
    
    # Verify plan
    plan = controller.learning_state.plan
    assert len(plan) == 4  # 0.6, 0.8, 1.0, 1.2
    assert all(isinstance(v.param_value, dict) for v in plan)
    assert plan[0].param_value == {"name": "CharacterLoRA", "weight": 0.6}
```

**Run**:
```bash
python -m pytest tests/integration/test_learning_lora_strength_sweep.py -v
```

---

## Commands Executed

```bash
# Unit tests
python -m pytest tests/learning/test_variable_metadata_composite.py -v
python -m pytest tests/controller/test_learning_controller_lora_retrieval.py -v
python -m pytest tests/controller/test_learning_controller_composite_values.py -v
python -m pytest tests/controller/test_learning_controller_lora_njr.py -v

# Integration test
python -m pytest tests/integration/test_learning_lora_strength_sweep.py -v

# Verify LoRA variable support
grep -n "lora_strength" src/learning/variable_metadata.py
grep -n "_get_current_loras" src/gui/controllers/learning_controller.py

# Verify backward compatibility
python -m pytest tests/learning/ -v
python -m pytest tests/integration/test_learning_sampler_comparison.py -v
python -m pytest tests/integration/test_learning_model_comparison.py -v
```

---

# VERIFICATION & PROOF

## git diff
```bash
git diff src/learning/variable_metadata.py
git diff src/gui/controllers/learning_controller.py
git diff src/gui/views/experiment_design_panel.py
```

**Expected changes**:
- MODIFIED: `src/learning/variable_metadata.py` (+15 lines for lora_strength)
- MODIFIED: `src/gui/controllers/learning_controller.py` (+150 lines for LoRA support)
- MODIFIED: `src/gui/views/experiment_design_panel.py` (+300 lines for LoRA UI)

## git status
```bash
git status --short
```

**Expected**:
```
M  src/learning/variable_metadata.py
M  src/gui/controllers/learning_controller.py
M  src/gui/views/experiment_design_panel.py
A  tests/learning/test_variable_metadata_composite.py
A  tests/controller/test_learning_controller_lora_retrieval.py
A  tests/controller/test_learning_controller_composite_values.py
A  tests/controller/test_learning_controller_lora_njr.py
A  tests/integration/test_learning_lora_strength_sweep.py
```

---

# ARCHITECTURAL COMPLIANCE VERIFICATION

## Composite LoRA System
- [x] LoRA Strength composite metadata entry
- [x] LoRA retrieval from stage card state
- [x] Dual mode support (strength sweep / comparison)
- [x] LoRA override applied to NJR.lora_tags
- [x] Validation of LoRA selection

## Backward Compatibility
- [x] All previous variable types work unchanged
- [x] Numeric, discrete, resource tests pass
- [x] No breaking changes to existing experiments

---

# GOLDEN PATH CONFIRMATION

**User Flow: Find Optimal LoRA Strength**

1. User opens Learning tab
2. User enters experiment: "Optimal Character LoRA Strength"
3. User selects "LoRA Strength" variable
4. UI shows LoRA composite widget
5. User selects "Test single LoRA at multiple strengths"
6. LoRA selector shows enabled LoRAs from txt2img stage card
7. User selects "CharacterLoRA-v2"
8. User sets strength range: 0.5 → 1.5, step 0.1
9. UI shows "11 variants will be generated"
10. User enters prompt: "portrait of anime girl"
11. User clicks "Build Preview Only"
12. Plan table shows 11 variants (0.5, 0.6, ..., 1.5)
13. User clicks "Run Experiment"
14. Jobs submitted with correct LoRA tag in NJR
15. Each variant has CharacterLoRA at different strength
16. run_metadata.json contains LoRA info

**Expected Behavior**:
- ✅ LoRA selector populated from stage card
- ✅ Strength range works like numeric variables
- ✅ Variants generated with {name, weight} dicts
- ✅ NJR.lora_tags contains correct LoRA
- ✅ LoRA strength varies across variants
- ✅ Config propagates to run_metadata.json

---

# COMPLETION CRITERIA

This PR is complete when:

1. ✅ LoRA Strength composite metadata entry added
2. ✅ LoRA retrieval from stage card implemented
3. ✅ Dual mode UI functional (strength sweep + comparison)
4. ✅ LoRA override applied to NJR.lora_tags
5. ✅ All unit tests pass (10+ tests)
6. ✅ Integration test demonstrates LoRA strength sweep
7. ✅ Backward compatibility maintained (all PR-LEARN-020/021 tests pass)
8. ✅ Documentation updated

---

**Next Steps**:
1. Execute this PR
2. Validate LoRA experiments work end-to-end in UI
3. Complete Phase 1-3 implementation
4. Consider Phase 4 enhancements (multi-variable, LoRA stacking)
