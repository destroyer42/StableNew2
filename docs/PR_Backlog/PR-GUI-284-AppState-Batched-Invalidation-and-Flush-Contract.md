# PR-GUI-284 - AppState Batched Invalidation and Flush Contract

Status: Completed 2026-03-28

## Purpose

Add cadence-controlled invalidation for runtime-heavy GUI state without slowing
user-edit interactions.

## Outcomes

- hot runtime keys now batch instead of immediately fan out
- immediate user-edit keys remain immediate
- `flush_now()` exists for explicit final delivery
- `GuiInvoker` supports delayed callback scheduling for batched GUI flushes

## Hot Keys

- `runtime_status`
- `queue_status`
- `queue_items`
- `history_items`
- `preview_jobs`
- `operator_log`

## Key Files

- `src/gui/app_state_v2.py`
- `src/gui/gui_invoker.py`
- `tests/gui_v2/test_app_state_notification_batching.py`
- `tests/gui_v2/test_gui_invoker.py`

## Validation

- hot-key batching regression coverage
- immediate-vs-batched notification coverage
- explicit flush coverage
