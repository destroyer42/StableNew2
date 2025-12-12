# PR-GUI-V2-LEARNING-3G: LearningPlanTable Live Status Updates (2025-11-26_0124)

## Summary
Implements full LearningPlanTable live updates and reactive status changes as variants move through the Learning workflow. Enhances table with dynamic state transitions, row highlighting, and basic sorting.

### Reference Design  
`C:\Users\rob\projects\StableNew\docs\pr_templates\PR-GUI-V2-LEARNING-TAB-003.md`

## Problem
PR-3E creates variants and a plan. PR-3F executes variants. But the table is static and does not reflect updates during execution.

## Goals
- Dynamic status updates in LearningPlanTable
- Row highlighting and optional sorting
- Integration with LearningController.on_variant_status_changed()
- Zero changes to backend executor
- Make table UX strong enough for PR‑3H (Rating)

## Implementation Tasks
1. Add status update API to LearningPlanTable
   - update_row_status(index, status)
   - highlight_row(index)
   - clear_highlights()

2. Add new statuses:
   - Pending
   - Running
   - Complete
   - Failed

3. Bind controller events
   - LearningController calls table.update_row_status()
   - Implement on_variant_status_changed()

4. (Optional) Sorting UX (low risk)
   - “Sort by status”
   - “Sort by parameter value”

5. Ensure non-blocking UI update via Tk events

## Acceptance Criteria
- Table visually updates during execution
- Status transitions accurately represented
- No exceptions or GUI freezes
