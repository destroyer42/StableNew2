# PR-MAR26-001 Learning Core Wiring Stabilization

## Objective
Stabilize Learning tab/controller wiring so core learning workflows function and learning integration tests pass.

## Scope
- Normalize LearningController constructor behavior and fallback paths.
- Add missing compatibility methods expected by learning UI and tests.
- Fix app-level completion callback routing.
- Ensure Learning tab can fetch review records through controller.

## Files
- src/gui/controllers/learning_controller.py
- src/gui/views/learning_tab_frame_v2.py
- src/controller/app_controller.py
- tests/controller/test_learning_controller_njr.py (if contract alignment updates are needed)
- tests/controller/test_learning_controller_integration.py (only if legacy contract adjustment is required)

## Required Changes
1. LearningController must accept `execution_controller`-only construction for integration compatibility.
2. Implement `set_learning_enabled(...)` and propagate to execution/pipeline/app state where available.
3. Add `list_recent_records(...)` and `save_feedback(...)` passthroughs to execution controller when available.
4. Add `_njr_to_queue_job(...)` and `_execute_learning_job(...)` compatibility methods.
5. `_submit_variant_job(...)` must use execution controller if present, otherwise fall back to direct queue submission.
6. Fix `AppController._create_learning_completion_handler` to reference `learning_tab.learning_controller`.

## Test Plan
- pytest -q tests/controller/test_learning_controller_njr.py
- pytest -q tests/controller/test_learning_controller_integration.py
- pytest -q tests/controller/test_learning_execution_controller_gui_contract.py

## Acceptance
- Learning controller tests pass.
- No regressions in learning execution controller GUI contract tests.
- Learning tab review dialog can request records via controller path.
