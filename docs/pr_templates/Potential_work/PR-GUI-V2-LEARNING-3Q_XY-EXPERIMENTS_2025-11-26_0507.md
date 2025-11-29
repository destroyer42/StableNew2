# PR-GUI-V2-LEARNING-3Q_XY-EXPERIMENTS (2025-11-26_0507)

## Summary
Adds **Two-Variable (“X/Y”) Experimental Mode** to the Learning system, enabling experiments that sweep **two parameters at once** (e.g., CFG *and* steps, sampler *and* scheduler).  
This PR extends the current 1D LearningExperiment and plan builder into a 2D grid capable of generating X×Y combinations and visualizing them via an ASCII heatmap.

### Reference Design
`C:\Users\rob\projects\StableNew\docs\pr_templates\PR-GUI-V2-LEARNING-TAB-003.md`

---

## Problem

So far, the Learning module supports only **single-variable sweeps** (X only).  
In practice, quality is frequently determined by **interactions** between parameters:

- CFG × steps  
- Sampler × scheduler  
- LoRA strength × denoise  
- Resolution × tiling settings  

Without an X/Y mode, users must manually run separate experiments and mentally integrate results. This slows learning and obscures interaction effects.

---

## Goals

- Add a **two-variable mode** to the Learning experiment designer.
- Extend LearningExperiment and LearningVariant to represent:
  - X parameter & value
  - Y parameter & value
- Extend the plan builder (PR-3E) to create an **X×Y grid** of variants.
- Extend LearningPlanTable to show both X and Y for each variant.
- Add a simple ASCII **X/Y heatmap** view to the Charts/Analytics area.
- Respect safety caps to avoid exploding variant counts.

---

## Non-Goals

- No more than **2 dimensions** (no 3D+ hypercube experiments).
- No advanced statistical modeling; that remains in analytics / recommendation PRs.
- No changes to base Pipeline executor beyond what PR-3F already supports.
- No persistent storage changes beyond what PR-3N already introduced.

---

## Preconditions / Dependencies

This PR assumes the following PRs are implemented:

- PR-3D: Experiment Design Panel
- PR-3E: Build Learning Plan (1D)
- PR-3F: Run Learning Plan
- PR-3G: Live status updates in LearningPlanTable
- PR-3K: Analytics backbone
- PR-3M: Visual charts utilities (ASCII)

---

## High-Level Design

X/Y Experiments extend the existing 1D model:

- **LearningExperiment**
  - Adds:
    - x_param (name, type)
    - y_param (name, type)
    - x_values: list or range spec
    - y_values: list or range spec
  - A flag:
    - mode: "single" | "xy"

- **LearningVariant**
  - Adds:
    - x_value
    - y_value

- **Plan Builder (build_plan)**
  - For mode=="single":
    - Current behavior remains unchanged.
  - For mode=="xy":
    - Build Cartesian product:
      - variants = [(x_i, y_j) for x_i in x_values for y_j in y_values]
    - Respect global `max_variants` (cap and warn if exceeded).

- **UI**
  - ExperimentDesignPanel:
    - Adds Y parameter controls.
  - LearningPlanTable:
    - Add X column and Y column.
  - Charts / Analytics:
    - Adds basic ASCII heatmap for a selected metric (e.g., mean rating).

---

## Detailed Implementation Plan

### 1. Extend LearningState & Models (learning_state.py)

**Files:**
- `learning_state.py`

**Tasks:**

1. **Update LearningExperiment**
   - Add fields:
     - `mode: str`  # "single" or "xy"
     - `x_param: Optional[str]`
     - `y_param: Optional[str]`
     - `x_is_numeric: bool`
     - `y_is_numeric: bool`
     - `x_numeric_range: Optional[NumericRange]` (start, end, step)
     - `y_numeric_range: Optional[NumericRange]`
     - `x_discrete_values: Optional[List[str]]`
     - `y_discrete_values: Optional[List[str]]`
   - Maintain backwards compatibility:
     - Default `mode` to "single" for older sessions.
     - 1D experiments may only populate x_* fields.

2. **Update LearningVariant**
   - Add:
     - `x_param: Optional[str]`
     - `y_param: Optional[str]`
     - `x_value: Optional[float|str]`
     - `y_value: Optional[float|str]`
   - Keep existing fields intact.

3. **Add Utility Helpers**
   - Helper to derive a **display label**:
     - e.g., `f"{x_param}={x_value}, {y_param}={y_value}"`.
   - Ensure serialization/deserialization (PR-3N) remains stable:
     - Add version bump if needed, but maintain compatibility.

---

### 2. Extend ExperimentDesignPanel for Y Parameter (experiment_design_panel.py)

**Files:**
- `experiment_design_panel.py`
- `learning_controller.py` (only interface usage)

**Tasks:**

1. UI Additions:
   - **Mode Selector:**
     - Radio buttons or dropdown:
       - "Single Variable"
       - "Two Variables (X/Y)"
   - **Y Parameter Definition** (visible only if "Two Variables" selected):
     - Y parameter dropdown (same parameter options as X: CFG, steps, sampler, scheduler, LoRA strength, etc.).
     - Y range/values fields:
       - Numeric mode:
         - start, end, step
       - Discrete mode:
         - comma-separated values or multi-select list

2. Input Binding:
   - Extend the `ExperimentDesignInput` structure passed to LearningController to include:
     - `mode`
     - `y_param`
     - `y_range_or_values`
   - Ensure that when mode=="single", all Y fields are gracefully ignored.

3. Validation:
   - Additional rules:
     - If mode=="xy":
       - Y param must be selected.
       - Y range/values must be valid.
       - X and Y param **must not be identical** (prevent meaningless 2D).
   - Display validation errors inline in the panel.

---

### 3. Extend LearningController.update_experiment_design (learning_controller.py)

**Files:**
- `learning_controller.py`
- (Uses) `learning_state.py`

**Tasks:**

1. Accept extended input:
   - Add Y fields and `mode` to update_experiment_design signature or payload.

2. Build LearningExperiment:
   - For mode=="single":
     - Behavior unchanged (use only X).
   - For mode=="xy":
     - Populate all X/Y fields.
     - Normalize numeric ranges into explicit value lists (optional, or leave to builder).
     - Validate that total combinations do not exceed safety thresholds:
       - Example: max 64 or value from config.
       - If exceeded:
         - Cap or reject with a clear error message surfaced to the panel.

3. Store in LearningState:
   - Update `LearningState.current_experiment`.
   - Clear or mark stale any old plan in `LearningState.plan`.

---

### 4. Extend Plan Building to Support X/Y (learning_controller.py / build_plan)

**Files:**
- `learning_controller.py`
- `learning_state.py`
- `learning_plan_table.py` (row population)

**Tasks:**

1. Update build_plan():
   - Inspect `experiment.mode`.
   - If "single":
     - Existing 1D variant generation logic remains.
   - If "xy":
     - Derive `x_values` and `y_values` from experiment definition:
       - If numeric:
         - Generate via `start, end, step`.
       - If discrete:
         - Use list as-is.
     - Build combinations:
       - for each x_value in x_values:
         - for each y_value in y_values:
           - create LearningVariant with:
             - `x_param`, `y_param`, `x_value`, `y_value`

2. Safety Limits:
   - Compute `total_variants = len(x_values) * len(y_values)`.
   - If `total_variants > MAX_LEARNING_VARIANTS`:
     - Option A (recommended): refuse build and show error.
     - Option B: cap with warning and partial plan.
   - `MAX_LEARNING_VARIANTS` could be 64 or config-driven.

3. Update LearningState.plan:
   - Overwrite existing plan with new list of LearningVariants.
   - Set iteration index / history as needed (PR-3L integration).

4. Update LearningPlanTable:
   - Add new columns:
     - `X` and `Y` (or `X Value`, `Y Value`).
   - When populating rows:
     - show both values.
   - Existing columns (status, stage, parameter value) should remain.

---

### 5. Add Basic ASCII X/Y Heatmap (visual_charts.py + LearningReviewPanel)

**Files:**
- `visual_charts.py`
- `learning_analytics.py` (for data aggregation)
- `learning_review_panel.py`
- `learning_controller.py` (interface glue)

**Tasks:**

1. Data Aggregation (learning_analytics.py):
   - Add helper:
     - `build_xy_matrix(records, x_param, y_param) -> (x_values, y_values, matrix)`
       - matrix[i][j] = avg rating (or other metric) for (x_values[i], y_values[j]).

2. Rendering (visual_charts.py):
   - Add:
     - `ascii_xy_heatmap(x_values, y_values, matrix) -> List[str]`
       - Returns a list of text lines, e.g., a grid where intensity is mapped to characters like:
         - " .:-=+*#%@"

3. Controller Glue (learning_controller.py):
   - Add:
     - `get_xy_heatmap(experiment) -> List[str]`
   - Use analytics + visual_charts.

4. UI (learning_review_panel.py):
   - In the Charts tab:
     - Add a mode toggle:
       - "1D Curve" vs "2D X/Y Heatmap"
     - When experiment.mode=="xy":
       - Enable X/Y heatmap view.
       - Render the returned text lines in a monospace text widget.

---

## Risks & Mitigations

- **Explosion in variant count**  
  - Mitigation: MAX_LEARNING_VARIANTS check & warning.
- **Confusing UI**  
  - Mitigation: Clear on-screen copy:
    - “X is primary sweep, Y is nested sweep.”
- **Backwards compatibility**  
  - Mitigation: Default mode="single", Y fields optional; existing sessions read as 1D experiments.

---

## Tests

### Unit Tests
- LearningState:
  - 1D vs 2D experiment creation.
- LearningController.build_plan:
  - Single variable: unchanged behavior.
  - X/Y:
    - correct Cartesian size.
    - correct assignment of x_value, y_value.
- Analytics / heatmap:
  - Correct computation of matrix from synthetic rating data.
  - ascii_xy_heatmap output dimensions correct.

### Manual Tests
1. **Single-variable sanity check**
   - Define 1D experiment as before.
   - Build and run plan.
   - Confirm behavior unchanged.

2. **Small X/Y test**
   - X: CFG {4, 7}
   - Y: Steps {20, 40}
   - Confirm 4 variants created.
   - Confirm table shows all combinations.
   - Confirm heatmap is generated.

3. **Safety limit**
   - Define X with 10 values, Y with 10 values (100 total).
   - Confirm system refuses or caps with clear message if limit is 64.

4. **Heatmap UI**
   - Ensure the heatmap is legible and aligned in the Charts tab.

---

## Acceptance Criteria

- Learning designer supports selecting:
  - 1D experiments (unchanged).
  - 2D X/Y experiments.
- build_plan generates the correct combinations for X/Y mode.
- LearningPlanTable shows X and Y columns and the right values.
- X/Y heatmap renders correctly for rated runs.
- No regression in existing 1D flows.

---

## Rollback Plan

- Revert changes to:
  - `learning_state.py` (remove mode/x/y fields).
  - `learning_controller.py` (remove X/Y logic).
  - `experiment_design_panel.py` (remove Y controls and mode selector).
  - `learning_plan_table.py` (remove X/Y columns).
  - `learning_analytics.py`, `visual_charts.py`, `learning_review_panel.py` (remove heatmap-related additions).
- Reload the last known-good session format if any migration was attempted.
