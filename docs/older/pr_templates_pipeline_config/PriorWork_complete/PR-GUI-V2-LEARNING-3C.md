# PR-GUI-V2-LEARNING-3C: LearningState + LearningController Skeleton (2025-11-26_0104)

## Summary
This PR introduces the foundational backend structures for the Learning module: `LearningState` and `LearningController`. This establishes the data and orchestration backbone for future plan-building and experimental workflows.

### Reference Design  
`C:\Users\rob\projects\StableNew\docs\pr_templates\PR-GUI-V2-LEARNING-TAB-003.md`

## Problem
The Learning tab has UI scaffolding but lacks state models or a controller to support experimental workflows. Without these, PR‑3D+ functional expansions cannot proceed.

## Goals
- Add LearningState with stable data structures
- Add LearningController with placeholder methods
- Integrate both into LearningTabFrame
- Do not yet implement real logic

## Non‑Goals
- No plan generation
- No execution wiring
- No rating or image review logic
- No integration with Pipeline or Prompt tabs

## Allowed Files
- `learning_state.py`
- `learning_controller.py`
- `learning_tab_frame.py` (wiring only)

## Implementation Tasks

### 1. Create `learning_state.py`
Include:
- `LearningState` class with fields:
  - `current_experiment`
  - `plan`
  - `selected_variant`
  - `selected_image_index`
- Stub data classes:
  - `LearningExperiment`
  - `LearningVariant`
  - `LearningImageRef`

### 2. Create `learning_controller.py`
- Accept references to:
  - `PromptWorkspaceState`
  - `PipelineState`
  - `LearningState`
- Define placeholder methods:
  - `build_plan(...)`
  - `run_plan(...)`
  - `on_job_completed(...)`
  - `record_rating(...)`

### 3. Wire into LearningTabFrame
- Instantiate LearningState + LearningController
- Pass references to panels (they will ignore for now)

## Tests
- Application loads without exceptions
- LearningState and LearningController instantiate successfully
- No integration regressions

## Acceptance Criteria
- Files exist with correct class structures
- Learning tab still loads normally
- No behavior added yet

## Rollback
Remove the two new modules and strip wiring from LearningTabFrame.

