# PR-GUI-V2-LEARNING-3A: Learning Tab Scaffold (2025-11-26_0104)

## Summary
This PR introduces the **Learning Tab Scaffold**, creating the third primary workspace tab in GUI V2. It establishes a new full‑width tab inside the global Notebook (post‑PR‑00), providing a structural foundation for all Learning Module features.

### Reference Design  
`C:\Users\rob\projects\StableNew\docs\pr_templates\PR-GUI-V2-LEARNING-TAB-003.md`

## Problem
The GUI currently includes only Prompt and Pipeline tabs. The Learning subsystem requires its own workspace with full isolation and appropriate layout space. No Learning-specific UI, controller, or state is available yet.

## Goals
- Add a new **Learning** tab to the Notebook.
- Implement `LearningTabFrame` with a placeholder scaffold.
- Ensure tab switching replaces the full workspace (consistent with PR‑00 Notebook refactor).
- Prepare the environment for future PR‑3B → PR‑3H implementations.

## Non‑Goals
- No real UI elements beyond a placeholder.
- No Learning logic, state wiring, or backend integration.
- No Pipeline or Prompt modifications.

## Allowed Files to Modify
- `main_window_v2.py` (tab wiring)
- `learning_tab_frame.py` (new)

## Forbidden Files
- Controllers
- State models
- Pipeline or Prompt tab files
- Backend/executor code

## Implementation Tasks
1. **Add LearningTabFrame**
   - Create `src/gui/views/learning_tab_frame.py`
   - Implement a simple Frame subclass with:
     - A placeholder label: “Learning Workspace (Scaffold)”
     - Basic spacing and padding

2. **Wire into Notebook**
   - In `MainWindowV2`:
     - Import LearningTabFrame
     - Add as a new tab named **“Learning”**
     - Maintain tab order: Prompt → Pipeline → Learning

3. **No Side Effects**
   - Ensure Prompt and Pipeline remain unchanged.
   - No layout collisions after PR‑00 refactor.

## Tests
- GUI loads without error
- Tab is visible and selectable
- Switching tabs replaces entire workspace correctly

## Acceptance Criteria
- Learning tab appears
- No regressions in existing tabs
- Application boots cleanly

## Rollback Plan
Delete `learning_tab_frame.py` and remove the Notebook entry. Undo import lines.

