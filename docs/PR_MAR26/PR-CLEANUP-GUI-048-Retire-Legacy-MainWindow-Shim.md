# PR-CLEANUP-GUI-048: Retire Legacy MainWindow Shim

**Status**: Specification
**Priority**: HIGH
**Effort**: MEDIUM
**Phase**: GUI Boundary Cleanup
**Date**: 2026-03-11

## Context & Motivation

### Problem Statement
`src/gui/main_window.py` remains an active compatibility shim that monkeypatches `MainWindowV2` and supports legacy tests/helpers.

### Why This Matters
This violates the no-shims / no-legacy-path standard and keeps GUI ownership ambiguous.

### Current Architecture
The actual app entrypoint uses `MainWindowV2`, but legacy imports and test fixtures still route through the shim layer.

### Reference
- `src/gui/main_window.py`
- `src/app_factory.py`
- `tests/gui_v2/conftest.py`
- `docs/D-ARCH-004-Codebase-Review-Top10-Issues-and-COAs.md`

## Goals & Non-Goals

### ✅ Goals
1. Remove the active legacy MainWindow shim.
2. Move tests/helpers to `MainWindowV2` directly.
3. Eliminate monkeypatch-based aliasing of `MainWindowV2`.

### ❌ Non-Goals
1. Do not redesign the Tk GUI.
2. Do not combine this with PySide6 migration work.
3. Do not move files between `src/gui` and `src/gui_v2` in this PR.

## Allowed Files

### ✅ Files to Modify
| File | Reason | Lines Changed (Est.) |
|------|--------|----------------------|
| `src/gui/main_window.py` | deprecate then remove shim contents, or reduce to explicit import-only alias if one-step removal is unsafe | 120 |
| `src/app_factory.py` | confirm direct `MainWindowV2` path remains canonical | 20 |
| `tests/gui_v2/conftest.py` | stop building GUI through `StableNewGUI` shim | 80 |
| `tests/controller/test_app_controller_start_run_shim.py` | rename/update to direct v2 path | 40 |
| `tests/controller/test_app_controller_packs.py` | update imports/usages | 40 |
| related tests importing `src.gui.main_window` | migrate to `src.gui.main_window_v2` | 80 |

### ❌ Forbidden Files (DO NOT TOUCH)
| File/Directory | Reason |
|----------------|--------|
| `src/gui/main_window_v2.py` except import/path cleanup | Keep core GUI behavior stable |
| `src/pipeline/**` | Out of scope |
| `src/queue/**` | Out of scope |

## Implementation Plan

### Step 1: Inventory shim consumers
Find all imports of `src.gui.main_window` and categorize them into:
- active runtime
- active tests
- obsolete

### Step 2: Migrate tests/helpers to direct V2 imports
Update fixtures and helpers to use `MainWindowV2` directly.

### Step 3: Remove monkeypatch aliasing
Delete the `main_window_v2_module.MainWindowV2 = StableNewGUI` path and related compatibility stubs once consumers are migrated.

### Step 4: Keep a minimal explicit alias only if still required
If an explicit one-line import alias is still needed temporarily, it must not monkeypatch or add behavior.

## Testing Plan

### Unit Tests
- none

### Integration Tests
- GUI smoke tests using `MainWindowV2`

### Journey Tests
- journey tests that instantiate the window

### Manual Testing
1. Launch app through canonical entrypoint.
2. Run GUI smoke and journey tests.
3. Confirm no legacy shim import is required.

## Verification Criteria

### ✅ Success Criteria
1. No active tests depend on the shim behavior layer.
2. No monkeypatching of `MainWindowV2` remains.
3. App still launches through `MainWindowV2`.

### ❌ Failure Criteria
- test suite still relies on shim behavior
- runtime import paths become ambiguous

## Risk Assessment

### Low Risk Areas
✅ Test import cleanup

### Medium Risk Areas
⚠️ Hidden legacy consumers
- **Mitigation**: inventory all imports before removal

### High Risk Areas
❌ Breaking test harness setup
- **Mitigation**: migrate fixtures first, then remove shim behavior

### Rollback Plan
Restore the shim temporarily if a missed consumer is discovered, then migrate that consumer explicitly.

## Tech Debt Analysis

## Tech Debt Removed
✅ Removes an active compatibility shim
✅ Clarifies the canonical GUI entrypoint

## Tech Debt Added
⚠️ None expected

**Net Tech Debt**: -2

## Architecture Alignment

### ✅ Enforces Architecture v2.6
Removes a legacy path that contradicts the active architecture.

### ✅ Follows Testing Standards
Migrates tests toward the canonical runtime path.

### ✅ Maintains Separation of Concerns
Eliminates monkeypatch-based aliasing between GUI modules.

## Dependencies

### External
- none

### Internal
- `src/gui/main_window.py`
- `src/gui/main_window_v2.py`
- GUI test fixtures/helpers

## Timeline & Effort

### Breakdown
| Task | Effort | Duration |
|------|--------|----------|
| consumer inventory | 0.5 day | Day 1 |
| test/helper migration | 1 day | Day 1-2 |
| shim removal | 0.5 day | Day 2 |

**Total**: 1-2 days

## Approval & Sign-Off

**Planner**: Codex
**Executor**: Codex
**Reviewer**: Rob

**Approval Status**: Pending

## Next Steps

1. Migrate all remaining shim consumers.
2. Remove monkeypatch behavior.
3. Continue with GUI ownership cleanup in PR-056.
