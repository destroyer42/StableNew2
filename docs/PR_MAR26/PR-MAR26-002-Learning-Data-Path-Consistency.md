# PR-MAR26-002 Learning Data Path and Record Consistency

## Objective
Create one canonical learning records path and remove path fragmentation.

## Scope
- Introduce a shared constant/module for learning records location.
- Update all learning UI/controller/adapters to use the same path.
- Keep backward compatibility migration read path support.

## Files
- src/learning/learning_paths.py (new)
- src/gui/views/learning_tab_frame_v2.py
- src/controller/learning_execution_controller.py
- src/gui_v2/adapters/learning_adapter_v2.py
- src/gui/controllers/learning_controller.py

## Test Plan
- Targeted learning controller and adapter tests
- Smoke run listing recent records from both legacy and new locations

## Acceptance
- All learning record producers/consumers resolve to one canonical file.
- Existing historical records remain readable.
