# PR-GUI-V2-LEARNING-3D: Experiment Design Panel Full Implementation (2025-11-26_0109)

## Summary
Implements the full Experiment Design Panel UI, validation, and LearningState population. This PR enables the Learning Tab to capture structured experiment definitions for later plan‑building and execution.

### Reference Design  
`C:\Users\rob\projects\StableNew\docs\pr_templates\PR-GUI-V2-LEARNING-TAB-003.md`

## Problem
The Learning tab currently has layout scaffolding but lacks any meaningful user input mechanism to define an experiment—stage, variable, ranges, prompt source, etc. PR‑3C created LearningState and LearningController skeletons but nothing uses them yet.

## Goals
- Implement full ExperimentDesignPanel UI.
- Bind form controls to LearningController.update_experiment_design().
- Provide validation & user feedback.
- Populate LearningState.current_experiment with a structured LearningExperiment.

## Non-Goals
- No plan generation (PR‑3E)
- No execution (PR‑3F)
- No rating or image review logic

## Allowed Files
- experiment_design_panel.py
- learning_controller.py
- learning_state.py
- learning_tab_frame.py (wiring only)

## Implementation Tasks
### 1. Complete ExperimentDesignPanel UI
Include:
- Experiment Name
- Description
- Target Stage (txt2img, img2img/adetailer, upscale)
- Variable Under Test (CFG, Steps, Sampler, Scheduler, LoRA strength)
- Numeric ranges (start/end/step) or discrete values
- Images per variant
- Prompt Source:
  - Use current PromptWorkspaceState slot
  - OR explicit text box

Add “Build Preview Only” button.
Add disabled “Run Experiment” button (wired in PR‑3F).

### 2. Form → LearningController.update_experiment_design()
- Collect all inputs into ExperimentDesignInput (dict or dataclass).
- Call controller.update_experiment_design().
- Controller constructs a LearningExperiment and stores it in state.

### 3. Validation
- Required fields: name, stage, parameter.
- If numeric range: start ≤ end, step > 0.
- If discrete list: must have ≥ 1 entry.
- If prompt override selected: text must be non‑empty.

### 4. Feedback
- Inline label for success (“Experiment definition updated”).
- Inline label for failure with reason.

## Tests
- Form loads correctly.
- Validation correctly blocks invalid form submissions.
- Valid submission updates LearningState.current_experiment.
- No execution triggered.

## Acceptance Criteria
- Learning tab collects complete experiment definitions.
- LearningState.current_experiment correctly structured.
- No regressions.

## Rollback
Remove UI elements, controller bindings, and revert LearningTabFrame wiring.
