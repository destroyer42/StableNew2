# PR-GUI-283 - AppController UI Boundary Closure and Operator Log Projection

Status: Completed 2026-03-28

## Delivered

- removed controller-owned `log_text` mutation from `AppController._append_log()`
- moved operator-log state into `AppStateV2`
- made `MainWindowV2.BottomZone` render operator-log state from GUI-owned projection
- removed controller-owned bottom status-label mutation from `_update_status()`

## Validation

- `tests/controller/test_app_controller_logging.py`
- `tests/gui_v2/test_operator_log_projection_v2.py`
- `tests/controller/test_app_controller_packs.py`
- `tests/gui_v2/test_process_logging_v2.py`
