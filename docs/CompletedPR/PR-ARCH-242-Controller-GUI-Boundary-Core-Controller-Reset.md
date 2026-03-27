# PR-ARCH-242 - Controller GUI Boundary Core Controller Reset

Status: Completed 2026-03-27

## Summary

This PR removes the active controller-owned runtime path from direct ownership
under `src.gui` by moving shared runtime state and base controller lifecycle
logic into `src.controller`.

## Delivered

- added controller-owned runtime state in
  `src/controller/runtime_state.py`
- added controller-owned base lifecycle/progress/cancellation controller in
  `src/controller/core_pipeline_controller.py`
- moved `src/controller/pipeline_controller.py` off the GUI-owned base class
  and onto the controller-owned base
- removed the active `JobService -> src.gui.pipeline_panel_v2` helper import by
  localizing queue-summary formatting inside `src/controller/job_service.py`
- updated active runtime and GUI import sites to depend on
  `src.controller.runtime_state` instead of `src.gui.state`
- reduced `src/gui/state.py` and `src/gui/controller.py` to compatibility
  surfaces so existing GUI/test imports keep working while ownership now lives
  under `src.controller`
- added a safety regression test proving the core controller/runtime path no
  longer imports `src.gui.controller`, `src.gui.state`, or the GUI queue
  formatter helper

## Key Files

- `src/controller/runtime_state.py`
- `src/controller/core_pipeline_controller.py`
- `src/controller/pipeline_controller.py`
- `src/controller/job_service.py`
- `src/gui/state.py`
- `src/gui/controller.py`
- `tests/safety/test_controller_core_no_gui_imports.py`

## Validation

Focused validation runs:

- `pytest tests/safety/test_controller_core_no_gui_imports.py tests/test_cancel_token.py tests/gui/test_state_manager_legacy.py tests/controller/test_heartbeat_stall_fix.py -q`
- `pytest tests/controller/test_controller_job_lifecycle.py tests/controller/test_pipeline_controller_queue_mode.py tests/controller/test_pipeline_controller_webui_gating.py -q`
- `pytest tests/controller/test_core_run_path_v2.py tests/controller/test_preview_queue_history_flow_v2.py tests/controller/test_pipeline_preview_to_queue_v2.py -q`
- `pytest tests/pipeline/test_executor_cancellation.py tests/pipeline/test_pipeline_runner_cancel_token.py tests/pipeline/test_run_modes.py -q`

Result:

- `56 passed`
