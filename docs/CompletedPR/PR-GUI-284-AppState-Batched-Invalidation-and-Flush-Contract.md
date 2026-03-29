# PR-GUI-284 - AppState Batched Invalidation and Flush Contract

Status: Completed 2026-03-28

## Delivered

- hot runtime notification batching in `AppStateV2`
- explicit `flush_now()` support
- delayed GUI callback scheduling in `GuiInvoker`
- deterministic test coverage for batched vs immediate key delivery

## Validation

- `tests/gui_v2/test_app_state_notification_batching.py`
- `tests/gui_v2/test_gui_invoker.py`
- targeted GUI/controller regression slice
