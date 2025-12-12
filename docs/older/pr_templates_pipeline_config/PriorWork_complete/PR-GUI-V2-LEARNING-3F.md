# PR-GUI-V2-LEARNING-3F: Run Learning Plan via Pipeline (2025-11-26_0109)

## Summary
Implements LearningController.run_plan(), enabling the Learning Tab to issue experimental jobs through the Pipeline execution path. PR‑3F connects LearningVariants → PipelineState → executor.

### Reference Design  
`C:\Users\rob\projects\StableNew\docs\pr_templates\PR-GUI-V2-LEARNING-TAB-003.md`

## Problem
Experiments can be defined and planned, but there is no way to execute them. The Learning module must generate real jobs, submit them to the Pipeline, and track results.

## Goals
- Implement run_plan()
- Convert each LearningVariant into one or more Pipeline jobs
- Submit via existing pipeline executor
- Update LearningPlanTable with per‑variant execution status
- Connect preview panel updates via on_job_completed()

## Non-Goals
- No rating logic (future PR)
- No gallery or advanced review behavior
- No speculative retries or auto‑tuning

## Allowed Files
- learning_controller.py
- learning_state.py
- learning_plan_table.py (status updates)
- learning_review_panel.py (metadata preview only)
- pipeline_controller_v2.py (minimal integration point—append jobs, no rewrites)

## Implementation Tasks
### 1. run_plan()
For each LearningVariant:
- Build a Pipeline job request:
  - Apply variable under test to proper config field
  - Use PromptWorkspaceState or override prompt
  - Stage‑appropriate configuration
- Submit jobs using pipeline_controller.submit_learning_job(job)

### 2. Status Tracking
- Variant status transitions:
  - Pending → Running → Complete / Failed
- Table updates accordingly

### 3. on_job_completed()
- Controller receives job completion events.
- Identify corresponding LearningVariant
- Update:
  - Status = Complete
  - ImageRef (path/bytes)
- Send image + metadata to LearningReviewPanel.display_result()

### 4. Error Handling
- Failure → mark variant as Failed
- Continue remaining variants

## Tests
- Plan executes sequentially or in correct batch mode
- Variants transition states correctly
- Preview receives correct images
- No regression in Pipeline tab execution

## Acceptance Criteria
- All variants run through Pipeline
- Table accurately represents state
- Preview updates for each completed run

## Rollback
Remove run_plan, job submission calls, and table/status/preview updates.
