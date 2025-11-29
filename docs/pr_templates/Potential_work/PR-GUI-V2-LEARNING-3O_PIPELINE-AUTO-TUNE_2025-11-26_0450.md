# PR-GUI-V2-LEARNING-3O_PIPELINE-AUTO-TUNE (2025-11-26_0450)

## Summary
Implements Learning → Pipeline integration by adding **Auto-Tuning Profiles**. The Pipeline tab may now import recommended settings derived from Learning Module data.

### Reference Design
`C:\Users\rob\projects\StableNew\docs\pr_templates\PR-GUI-V2-LEARNING-TAB-003.md`

## Problem
Learning Module produces optimized parameter recommendations, but users must manually copy them into the Pipeline tab.

## Goals
- Add Pipeline “Apply Recommended Settings” button
- Update PipelineState with recommended:
  - sampler
  - scheduler
  - cfg scale
  - steps
  - LoRA strengths
- Perform safe overwrite confirmation

## Implementation Tasks
1. Add to LearningController:
   - get_best_settings_for_pipeline()
2. Add button to PipelineConfigPanel:
   - On click:
     - Fetch recommendations
     - Update PipelineState
     - Refresh UI fields
3. Add confirmation dialog:
   - “Overwrite current settings?”

## Tests
- Applying settings updates UI
- Works for all three stages
- No destructive resets

## Acceptance Criteria
- One-click pipeline optimization via Learning data
