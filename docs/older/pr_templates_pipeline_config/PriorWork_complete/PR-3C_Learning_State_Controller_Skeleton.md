# PR‑3C — Add LearningState + LearningController (Skeleton Only)

### Goal
Introduce backend components required for the Learning system, without implementing real behavior yet.

### Changes
Create two new modules:

---

## 1. `learning_state.py`
Defines the persistent state for learning operations:
- `LearningState` with:
  - `current_experiment = None`
  - `plan = []`
  - Optional placeholders:
    - `selected_variant`
    - `selected_image_index`

Defines data structures:
- `LearningExperiment`
- `LearningVariant`
- `LearningImageRef`

All minimal stubs.

---

## 2. `learning_controller.py`
Defines LearningController with empty methods:
- `build_plan(...)` — TODO
- `run_plan(...)` — TODO
- `on_job_completed(...)` — TODO
- `record_rating(...)` — TODO

Controller receives references to:
- `PromptWorkspaceState`
- `PipelineState`
- `LearningState`

---

## Wiring
- `LearningTabFrame` should instantiate:
  - One `LearningState`
  - One `LearningController`
- Panels created in PR‑3B receive the references but do not yet use them.

### Deliverables
- Complete Learning subsystem scaffolding.
- No functionality until PR‑3D and onward.
