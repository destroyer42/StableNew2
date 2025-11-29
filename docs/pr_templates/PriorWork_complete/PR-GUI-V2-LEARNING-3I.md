# PR-GUI-V2-LEARNING-3I: Full Learning Workflow Smoke Test (2025-11-26_0124)

## Summary
Defines the full end‑to‑end Learning System smoke test process. Ensures PR‑3A through PR‑3H integrate into a functioning pipeline.

### Purpose
Guarantee the Learning Module is stable, integrated, and production‑ready.

## Test Plan
1. GUI Startup
   - All tabs load
   - Learning tab builds without errors

2. Experiment Definition
   - Fill ExperimentDesignPanel
   - Validate successful LearningState update

3. Plan Generation
   - Build plan
   - Verify correct number of variants
   - Table updates appropriately

4. Execution Flow
   - run_plan executes variants
   - Status transitions: Pending → Running → Complete
   - Preview shows each result

5. Rating Flow
   - Select a completed variant
   - Rate 1–5
   - Confirm jsonl appended

6. Failure Scenarios
   - Missing WebUI
   - Invalid parameter selection
   - Partial failures

7. No regressions in Prompt or Pipeline tabs

## Acceptance Criteria
- Full workflow operates without crash
- Output images correctly generated
- Ratings stored and loadable
- State transitions all correct
