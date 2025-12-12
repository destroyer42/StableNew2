# PR-GUI-V2-LEARNING-3L: Adaptive Learning Loop System (2025-11-26_0141)

## Summary
Implements the **Adaptive Learning Loop (ALL)** system, enabling automatic re‑runs of experiments based on results, confidence thresholds, and parameter convergence.

This is an advanced feature that turns StableNewV2 into a feedback‑driven optimization tool.

### Reference Design  
`C:\Users\rob\projects\StableNew\docs\pr_templates\PR-GUI-V2-LEARNING-TAB-003.md`

---

## Problem
Even with recommendations and analytics, users still need to manually re‑run experiments.  
A fully adaptive system can guide itself toward optimal settings.

---

## Goals
- Enable LearningController to:
  - Detect unclear results
  - Trigger follow‑up experiment runs
  - Narrow ranges iteratively
  - Explore promising parameter clusters
- Add Adaptive Mode toggle in ExperimentDesignPanel
- Update plan + table + review workflow for multi‑iteration cycles

---

## Non‑Goals
- No deep ML models
- No backend/queue architecture redesign

---

## Implementation Tasks

### 1. Update LearningState
Add:
- adaptive_mode: bool
- iteration_index
- history_of_plans

### 2. Enhance LearningController
Add methods:
- should_refine_plan()
- refine_parameter_range()
- enqueue_followup_experiments()
- merge_results()

Flow:
1. Run base experiment.
2. Compute analytics.
3. Identify areas with:
   - highest rating gradient
   - unexplored promising zones
4. Narrow range and generate next‑iteration plan.
5. Append to plan list.

### 3. UI Integration
In ExperimentDesignPanel:
- Add “Adaptive Mode” checkbox
- Add controls for:
  - max_iterations
  - convergence threshold
  - minimum confidence

In LearningPlanTable:
- Show iteration number column.

### 4. Loop Control
- Prevent infinite loops
- Stop when:
  - threshold met
  - max iterations reached
  - variance too low

---

## Tests
- Multi‑iteration flow on synthetic data
- Adaptive narrowing respects bounds
- Follow‑up plans appended not overwritten

---

## Acceptance Criteria
- Adaptive mode automatically performs refinement cycles
- Table shows multi‑iteration workflow
- Full loop runs without crash

---

## Rollback
Remove ALL-related fields and functions.
