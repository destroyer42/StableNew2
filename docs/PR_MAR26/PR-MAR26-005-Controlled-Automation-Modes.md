# PR-MAR26-005 Controlled Automation Modes

## Objective
Add safe automation modes for recommendation application and micro-experiments.

## Scope
- Introduce mode flags: suggest-only, apply-with-confirm, auto-micro-experiment.
- Add safety checks and queue caps.
- Add logging and rollback guardrails.

## Files
- src/gui/views/learning_tab_frame_v2.py
- src/gui/controllers/learning_controller.py
- src/controller/pipeline_controller.py

## Acceptance
- Automation is opt-in and safe.
- System remains stable and non-crashing under repeated runs.
