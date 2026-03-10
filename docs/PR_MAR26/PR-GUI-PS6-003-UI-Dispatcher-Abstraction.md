# PR-GUI-PS6-003: UI Dispatcher Abstraction

**Status**: In Progress
**Priority**: HIGH
**Effort**: MEDIUM (1 week)
**Phase**: PySide6 Migration
**Date**: 2026-03-09

## Context & Motivation
Tk-specific dispatch assumptions (`after`) are embedded in controller-facing paths.

## Goals & Non-Goals
### ? Goals
1. Introduce toolkit-neutral UI dispatcher contract.
2. Route controller UI calls through dispatcher abstraction.
3. Add thread-behavior tests.
### ? Non-Goals
No Qt widgets yet.

## Allowed Files
### ? Files to Create
| File | Purpose | Lines (Est.) |
|------|---------|--------------|
| src/gui/ui_dispatcher.py | Dispatcher interface + implementations | 180 |
| tests/controller/test_ui_dispatcher_contract.py | Dispatch/threading tests | 160 |
| docs/PR_MAR26/PR-GUI-PS6-003-UI-Dispatcher-Abstraction.md | PR spec | 170 |
### ? Files to Modify
| File | Reason | Lines Changed (Est.) |
|------|--------|----------------------|
| src/controller/app_controller.py | replace direct Tk assumptions | 120 |
| src/gui/gui_invoker.py | adapter wiring | 70 |
| src/app_factory.py | dispatcher construction | 40 |
### ? Forbidden Files (DO NOT TOUCH)
| File/Directory | Reason |
|----------------|--------|
| src/pipeline/** | Out of scope |
| src/queue/** | Out of scope |

## Implementation Plan
1. Add dispatcher protocol.
2. Wire Tk dispatcher implementation.
3. Replace direct UI scheduling calls.
4. Add thread-affinity tests.

## Testing Plan
- pytest -q tests/controller/test_ui_dispatcher_contract.py
- pytest -q tests/integration/test_golden_path_suite_v2_6.py

## Verification Criteria
No direct Tk scheduling in controller path except inside Tk dispatcher implementation.

## Risk Assessment
?? Deadlock/thread regressions.
- Mitigation: explicit threading tests.

## Tech Debt Analysis
Net: -2

## Next Steps
PR-PS6-004

## Implementation Summary (Incremental)

**Implementation Date**: 2026-03-09
**Executor**: Codex
**Status**: PARTIAL (controller-side scheduling replacement complete)

### What Was Implemented
1. Added `src/gui/ui_dispatcher.py` with `UiDispatcher`, `TkUiDispatcher`, and `ImmediateUiDispatcher`.
2. Updated `src/app_factory.py` to inject `ui_scheduler=TkUiDispatcher(root).invoke` into `AppController`.
3. Added `tests/gui_v2/test_ui_dispatcher.py`.
4. Replaced direct controller `root.after` usages in `src/controller/app_controller.py` with centralized dispatcher helpers:
   - `_dispatch_via_root_after`
   - `_ui_dispatch_later`
   - `_get_ui_root`
5. Routed lifecycle/status/log/debounce scheduling through dispatcher helpers.
6. Added safety guard for job services without `register_completion_handler`.

### Verification
1. `pytest -q tests/gui_v2/test_ui_dispatcher.py`
2. `pytest -q tests/controller/test_queue_callback_gui_thread_marshaling.py tests/controller/test_ui_dispatch_threading.py tests/controller/test_job_execution_controller_ui_dispatch.py`
3. `pytest -q tests/integration/test_golden_path_suite_v2_6.py`
