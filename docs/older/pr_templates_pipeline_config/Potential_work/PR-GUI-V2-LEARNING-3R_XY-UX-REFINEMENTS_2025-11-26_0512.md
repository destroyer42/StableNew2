# PR-GUI-V2-LEARNING-3R_XY-UX-REFINEMENTS (2025-11-26_0512)

## Summary
Provides **UX Refinements for X/Y Experiments**, improving usability, preset selection, visualization clarity, and workflow efficiency for the Two‑Variable Experimental Mode introduced in PR‑3Q.

### Reference Design
`C:\Users\rob\projects\StableNew\docs\pr_templates\PR-GUI-V2-LEARNING-TAB-003.md`

---

## Problem
PR‑3Q introduced core X/Y functionality but the UX can be improved:
- Choosing X/Y pairs takes multiple steps.
- Many pairs are common (CFG × steps, sampler × scheduler).
- Heatmap readability can be improved.
- Users need clearer guidance when variant counts approach safety caps.
- Need “quick grid” presets.

---

## Goals
- Add UX refinements to ExperimentDesignPanel, LearningPlanTable, and Charts UI.
- Add presets for common X/Y pairs.
- Improve heatmap labeling and alignment.
- Add dynamic warnings for large variant counts.
- Add optional tooltips and sample previews.

---

## Non‑Goals
- No changes to underlying LearningController logic.
- No change in analytics algorithms.
- No new adaptive learning behavior (handled in PR‑3L).

---

## Implementation Tasks

### 1. ExperimentDesignPanel Enhancements
- Add a **“Quick X/Y Pair Presets”** dropdown:
  - CFG × Steps
  - CFG × Denoise
  - Sampler × Scheduler
  - LoRA Strength × Steps
  - Resolution × Steps
- Add inline explanation box for “Why X/Y experiments matter.”
- Add dynamic count estimator:
  - “This experiment will generate N variants.”
  - Text turns yellow near threshold (≥75%).
  - Text turns red when threshold exceeded.
- Disable “Build Plan” button when invalid.

### 2. Heatmap Improvements
- Add labeled axes:
  - X-axis shows parameter values horizontally.
  - Y-axis values placed vertically with left gutter.
- Enhance ASCII rendering for legibility:
  - Replace characters with more semantically consistent scale:
    - “ .,:-~+=*#%@”
- Add legend box with rating → glyph mapping.
- Add “Invert Heatmap” option for dark/light themes.

### 3. LearningPlanTable
- Add row tooltips:
  - Display full X and Y values.
  - Display short description: “CFG=4, Steps=30”.
- Add column width auto‑fit to ensure clean alignment.

### 4. Safety UX
- When variant count exceeds threshold:
  - Replace build button with a warning block.
  - Provide guidance:
    - “Reduce range step size”
    - “Switch to single‑variable mode”
    - “Limit discrete values”
- When variant count is extremely small (<3):
  - Suggest switching to single‑variable mode instead.

### 5. Integration & Controller Safety
- No changes to controller logic except:
  - New method on controller:
    - `get_variant_count_estimate(experiment_input)`
  - Used by UI only.

---

## Tests

### Manual UX Tests
1. Select preset “CFG × Steps”
   - Confirm fields auto-populate.
2. Validate variant count estimator matches plan builder.
3. Build plan with:
   - small grid (2×2)
   - medium grid (4×4)
   - near-threshold grid (8×8)
4. Verify heatmap labeling is correct.
5. Switch between “Regular” and “Inverted” heatmap modes.

### Automated Tests
- Heatmap axis labeling unit tests.
- Variant count estimator tests:
  - numeric range
  - discrete range
  - mixed ranges

---

## Acceptance Criteria
- UX for X/Y mode is significantly streamlined.
- Users can choose presets quickly.
- Heatmaps are readable, aligned, and properly labeled.
- Safety warnings and variant estimators work consistently.

---

## Rollback
Remove:
- preset controls
- enhanced heatmap labeling
- variant estimator
- LearningPlanTable UX refinements
