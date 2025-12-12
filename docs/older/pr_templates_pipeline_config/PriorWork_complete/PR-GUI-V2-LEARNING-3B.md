# PR-GUI-V2-LEARNING-3B: Learning Tab Layout Skeleton (2025-11-26_0104)

## Summary
This PR transforms the Learning tab from a placeholder into a full internal layout structure with a header + three‑column workspace, following the layout defined in the Learning Tab spec document.

### Reference Design  
`C:\Users\rob\projects\StableNew\docs\pr_templates\PR-GUI-V2-LEARNING-TAB-003.md`

## Problem
The Learning tab currently contains only a trivial scaffold. The Learning module requires a structured workspace including design controls, plan table, and review displays.

## Goals
- Build the internal layout for the Learning tab.
- Implement three column panels:
  - **ExperimentDesignPanel**
  - **LearningPlanTable**
  - **LearningReviewPanel**
- Create a header region.

## Non‑Goals
- No logic wiring
- No LearningState or LearningController behavior
- No plan building, execution, or rating logic yet

## Allowed File Additions/Modifications
- `learning_tab_frame.py`
- New view files:
  - `experiment_design_panel.py`
  - `learning_plan_table.py`
  - `learning_review_panel.py`

## Forbidden Changes
- No controller/state implementations
- No touching Prompt or Pipeline tabs

## Implementation Tasks
1. **Create Header**
   - Add `LearningHeader` section with placeholder label.

2. **Three‑Column Body**
   - Create a container frame in `LearningTabFrame`.
   - Inside it, place:
     - Left: ExperimentDesignPanel
     - Center: LearningPlanTable
     - Right: LearningReviewPanel
   - Use grid or PanedWindow with resize weights.

3. **Panel Files**
   - Each new view file contains:
     - Class definition
     - Minimal constructor
     - Placeholder label only

4. **No Behavior**
   - No state access
   - No controller routing
   - Pure layout only

## Tests
- Learning tab loads without error
- Resizing window adjusts 3 columns proportionally
- Panels display correct placeholders

## Acceptance Criteria
- Header visible
- Three columns visible
- No functional regressions

## Rollback
Remove the new panel files and revert LearningTabFrame layout.

