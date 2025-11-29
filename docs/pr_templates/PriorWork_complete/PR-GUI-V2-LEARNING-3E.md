# PR-GUI-V2-LEARNING-3E: Build Learning Plan (2025-11-26_0109)

## Summary
Implements LearningController.build_plan(), taking a LearningExperiment and producing a fully structured list of LearningVariants and a LearningPlan. PR‑3E creates the internal job matrix required for experimental runs.

### Reference Design  
`C:\Users\rob\projects\StableNew\docs\pr_templates\PR-GUI-V2-LEARNING-TAB-003.md`

## Problem
Experiment definitions exist (after PR‑3D) but no plan is generated. The system needs a structured plan (variants, configs, prompts) before jobs can be executed in PR‑3F.

## Goals
- Implement LearningController.build_plan()
- Generate LearningVariant objects based on the variable under test
- Populate LearningState.plan
- Update LearningPlanTable to show each variant with status “Pending”

## Non-Goals
- No job execution
- No rating/review logic
- No UI modifications beyond updating the plan table

## Allowed Files
- learning_controller.py
- learning_state.py
- learning_plan_table.py (table population only)

## Implementation Tasks
### 1. Implement build_plan()
Given LearningExperiment:
- If numeric range: generate values start…end with step.
- If discrete values: use list directly.
- For each value:
  - Create a LearningVariant with:
    - value_under_test
    - stage
    - prompt (from PromptWorkspaceState or override)
    - model_settings / pipeline_settings stubbed for now
  - Append to LearningState.plan

### 2. Integrate with LearningPlanTable
- Clear table
- Populate one row per variant:
  - Variant #
  - Parameter value
  - Stage
  - Status (“Pending”)

### 3. Controller / State Integrity
- build_plan() overwrites any previous plan.
- After building:
  - LearningState.current_experiment must remain intact.
  - LearningState.plan must contain fresh LearningVariants.

## Tests
- Valid experiment builds correct number of variants.
- Numeric and discrete parameter modes both work.
- Table updates accordingly.
- No execution triggered.

## Acceptance Criteria
- Learning plan view correctly shows all variants.
- State accurately reflects experiment design.
- No regressions.

## Rollback
Remove build_plan code, remove variant generation, revert table updates.
