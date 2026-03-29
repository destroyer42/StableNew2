# PR-GUI-283 - AppController UI Boundary Closure and Operator Log Projection

Status: Completed 2026-03-28

## Purpose

Remove the last controller-owned operator-log widget mutation path and move the
operator log into GUI-owned projected state.

## Outcomes

- `AppController._append_log()` no longer writes into `bottom_zone.log_text`
- `AppStateV2` owns a bounded `operator_log` buffer and dedicated notification key
- `MainWindowV2.BottomZone` renders operator-log state from `AppStateV2`
- controller status updates no longer mutate the bottom status label directly

## Key Files

- `src/controller/app_controller.py`
- `src/gui/app_state_v2.py`
- `src/gui/main_window_v2.py`
- `tests/controller/test_app_controller_logging.py`
- `tests/gui_v2/test_operator_log_projection_v2.py`

## Validation

- controller logging regression
- GUI operator-log projection regression
- compileall on touched GUI/controller files
