# PR-TEST-001 — Controller Archive Cleanup

**Status**: ✅ COMPLETE  
**Date**: 2025-12-21  
**Category**: Test Suite Hygiene  
**Related**: PR-TEST-002, Test Suite Modernization Initiative

---

## Purpose

Remove 9 archived controller tests and mark 1 active test importing from deprecated `src.controller.archive` paths as legacy, per [tests.instructions.md](.github/instructions/tests.instructions.md) rule: _"Do not import archived legacy modules for new tests."_

---

## Problem Statement

The test suite contained:
- 9 obsolete test files in `tests/controller/archive/` that tested pre-Phase 6 AppController behavior
- 1 active controller test (`test_app_controller_pipeline_integration.py`) importing `PipelineConfig` from archive

These tests violate the v2.6 architectural principle: **NJR-only execution path**.

---

## Implementation Summary

### Step 1: Delete Archived Controller Tests ✅

**Deleted files**:
1. `tests/controller/archive/test_adetailer_stage_integration_v2.py`
2. `tests/controller/archive/test_app_controller_config.py`
3. `tests/controller/archive/test_app_controller_packs.py`
4. `tests/controller/archive/test_app_controller_pipeline_bridge.py`
5. `tests/controller/archive/test_app_controller_pipeline_flow_pr0.py`
6. `tests/controller/archive/test_app_controller_pipeline_integration.py`
7. `tests/controller/archive/test_app_controller_run_mode_defaults.py`
8. `tests/controller/archive/test_app_controller_run_now_bridge.py`
9. `tests/controller/archive/test_resource_refresh_v2.py`

**Result**: `tests/controller/archive/` directory now empty.

---

### Step 2: Mark Active Test as Legacy ✅

**File**: `tests/controller/test_app_controller_pipeline_integration.py`

**Changes**:
1. Added docstring note: _"LEGACY TEST: This test validates the deprecated PipelineConfig path for backward compatibility testing."_
2. Marked both test functions with `@pytest.mark.legacy` decorator:
   - `test_pipeline_config_assembled_from_controller_state`
   - `test_cancel_triggers_token_and_returns_to_idle`

**Rationale**: These tests validate the legacy PipelineRunner interface, which is still used for backward compatibility but should not be the model for new tests.

---

### Step 3: Verification ✅

**Command**: `pytest tests/controller/ -q`

**Result**: All controller tests pass (with expected pre-existing failures unrelated to this PR).

---

## Test Coverage Impact

| Before | After |
|--------|-------|
| 9 archived tests (unmaintained) | 0 archived tests |
| 1 active test with archive import (unmarked) | 1 active test marked `@pytest.mark.legacy` |
| No clear legacy distinction | Clear `@pytest.mark.legacy` markers for backward compatibility tests |

---

## Architectural Alignment

- ✅ Enforces NJR-only execution path for new tests
- ✅ Preserves backward compatibility tests with clear markers
- ✅ Follows [tests.instructions.md](.github/instructions/tests.instructions.md)
- ✅ Reduces test suite maintenance burden

---

## Related Work

- **PR-TEST-002**: Legacy Archive Import Purge (marks/refactors remaining archive imports across pipeline/queue/learning tests)
- **PR-TEST-003**: Journey Tests Modernization (updates journey tests to use real `run_njr()` path)
- **PR-TEST-004**: Golden Path & Compat Fixtures (implements GP1-GP15 tests)

---

## Lessons Learned

1. **Archived code should be clearly marked**: The `#ARCHIVE` comments in deleted files helped identify obsolete tests quickly.
2. **Legacy markers improve clarity**: Using `@pytest.mark.legacy` makes it immediately clear which tests are for backward compatibility vs. canonical examples.
3. **Archive directory cleanup enables fresh starts**: Removing dead test files reduces cognitive load for future contributors.

---

## Next Steps

- ✅ **PR-TEST-002**: Purge remaining archive imports in pipeline/queue/learning tests
- 🔲 **PR-TEST-003**: Modernize journey tests to invoke real NJR execution
- 🔲 **PR-TEST-004**: Implement Golden Path tests (GP1-GP15) and compat fixtures
