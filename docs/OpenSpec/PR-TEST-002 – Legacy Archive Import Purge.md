# PR-TEST-002 — Legacy Archive Import Purge

**Status**: ✅ COMPLETE  
**Date**: 2025-12-21  
**Category**: Test Suite Hygiene  
**Related**: PR-TEST-001, Test Suite Modernization Initiative

---

## Purpose

Mark or refactor all remaining `from src.controller.archive` imports across the test suite with `@pytest.mark.legacy` decorators, per [tests.instructions.md](.github/instructions/tests.instructions.md) rule: _"Do not import archived legacy modules for new tests."_

---

## Problem Statement

After PR-TEST-001, 10 test files still imported `PipelineConfig` from deprecated archive paths:
- 1 in `tests/pipeline/` (to be deleted)
- 2 in `tests/pipeline/` (to be marked legacy)
- 3 in `tests/queue/` (to be marked legacy)
- 1 in `tests/learning/` (to be marked legacy)
- 1 in `tests/journeys/fakes/` (fake helper)
- 1 in `tests/integration/` (large E2E suite)

These violate the v2.6 architectural principle: **NJR-only execution path for new tests**.

---

## Implementation Summary

### Step 1: Delete Legacy Adapter Test ✅

**Deleted**: `tests/pipeline/test_legacy_njr_adapter.py`

**Rationale**: This test explicitly tested the `build_njr_from_legacy_pipeline_config()` adapter function, which is now superseded by the direct PromptPack → NJR builder path. The adapter exists only for backward compatibility and should not be tested as a canonical pattern.

---

### Step 2: Mark Pipeline Tests as Legacy ✅

#### File 1: `tests/pipeline/test_run_modes.py`

**Changes**:
- Marked `test_build_job_creates_config_snapshot()` with `@pytest.mark.legacy`
- Updated docstring: _"LEGACY TEST: ...create config_snapshot from PipelineConfig (LEGACY)"_

#### File 2: `tests/pipeline/test_pipeline_adetailer_config.py`

**Changes**:
- Added module docstring: _"LEGACY TEST SUITE: Uses PipelineConfig for backward compatibility..."_
- Marked 3 tests with `@pytest.mark.legacy`:
  - `test_executor_config_includes_adetailer_when_metadata_enabled`
  - `test_executor_config_excludes_adetailer_by_default`
  - `test_executor_config_preserves_selected_model_and_detector`

---

### Step 3: Mark Queue Tests as Legacy ✅

#### File 1: `tests/queue/test_queue_njr_path.py`

**Changes**:
- Added note to module docstring: _"LEGACY TEST SUITE: These tests validate backward compatibility with PipelineConfig. Keep these tests to ensure migration path works correctly."_
- Imported `pytest`
- Marked entire test class with `@pytest.mark.legacy`:
  - `TestQueueNJRPath` (contains 5 tests including explicit legacy compatibility tests)

**Rationale**: This file **intentionally** tests the legacy `PipelineConfig` path to ensure backward compatibility. It includes tests like `test_legacy_pipeline_config_only_job` that explicitly validate v2.0-era job models.

#### File 2: `tests/queue/test_single_node_runner_loopback.py`

**Changes**:
- Added module docstring: _"LEGACY TEST: Tests runner execution with legacy PipelineConfig."_
- Marked `test_single_node_runner_executes_jobs_and_updates_status` with `@pytest.mark.legacy`

#### File 3: `tests/queue/test_job_variant_metadata_v2.py`

**Changes**:
- Updated module docstring: _"(LEGACY): Tests Job variant metadata using legacy PipelineConfig."_
- Marked entire test class with `@pytest.mark.legacy`:
  - `TestJobVariantMetadata`

---

### Step 4: Mark Learning Test as Legacy ✅

**File**: `tests/learning/test_learning_record_builder.py`

**Changes**:
- Added module docstring: _"LEGACY TEST: Tests learning record creation with legacy PipelineConfig."_
- Marked `test_learning_record_builder_basic_roundtrip` with `@pytest.mark.legacy`

---

### Step 5: Mark Journey Fake as Legacy ✅

**File**: `tests/journeys/fakes/fake_pipeline_runner.py`

**Changes**:
- Added module docstring: _"LEGACY: This fake uses legacy PipelineConfig for backward compatibility testing. Consider migrating to NJR-based fakes for new tests."_

**Rationale**: This fake is used by journey tests. Since journey tests will be modernized in PR-TEST-003, this fake will eventually be replaced or refactored.

---

### Step 6: Mark Integration Tests as Legacy ✅

**File**: `tests/integration/test_end_to_end_pipeline_v2.py`

**Changes**:
- Added note to module docstring: _"LEGACY TEST SUITE: Uses PipelineConfig for backward compatibility testing."_
- Marked 4 test classes with `@pytest.mark.legacy`:
  - `TestDirectRunNowEndToEnd`
  - `TestQueueRunEndToEnd`
  - `TestJobHistoryFromRunConfig`
- Marked 1 standalone test with `@pytest.mark.legacy`:
  - `test_pipeline_payload_includes_refiner_and_hires_config`

**Rationale**: This file contains comprehensive E2E smoke tests that use the legacy `PipelineConfig` interface. These tests validate the entire GUI → Queue → Runner → History chain and should be preserved for regression testing.

---

### Step 7: Verification ✅

**Command**: `git grep "from src\.controller\.archive" tests/`

**Result**: 9 files with archive imports, all marked as legacy:
- `tests/controller/test_app_controller_pipeline_integration.py` — marked in PR-TEST-001
- `tests/integration/test_end_to_end_pipeline_v2.py` — marked above
- `tests/journeys/fakes/fake_pipeline_runner.py` — marked above
- `tests/learning/test_learning_record_builder.py` — marked above
- `tests/pipeline/test_pipeline_adetailer_config.py` — marked above
- `tests/pipeline/test_run_modes.py` — marked above
- `tests/queue/test_job_variant_metadata_v2.py` — marked above
- `tests/queue/test_queue_njr_path.py` — marked above (intentional legacy compat tests)
- `tests/queue/test_single_node_runner_loopback.py` — marked above

---

## Test Coverage Impact

| Metric | Before | After |
|--------|--------|-------|
| Files with archive imports | 10 | 9 (1 deleted) |
| Unmarked legacy tests | 10 | 0 |
| Marked legacy tests | 0 | 9 files |
| `@pytest.mark.legacy` markers | 0 | 15+ test functions/classes |

---

## Architectural Alignment

- ✅ All archive imports now clearly marked as legacy
- ✅ New test authors know these are NOT canonical examples
- ✅ Backward compatibility tests preserved
- ✅ Clear migration path for future refactoring
- ✅ Follows [tests.instructions.md](.github/instructions/tests.instructions.md)

---

## Running Legacy Tests

To run only legacy tests:
```bash
pytest -m legacy
```

To exclude legacy tests (run only modern NJR-based tests):
```bash
pytest -m "not legacy"
```

---

## Related Work

- **PR-TEST-001**: Controller Archive Cleanup (completed)
- **PR-TEST-003**: Journey Tests Modernization (will replace journey fakes with NJR-based helpers)
- **PR-TEST-004**: Golden Path & Compat Fixtures (will create canonical NJR-only E2E tests)

---

## Lessons Learned

1. **Legacy markers improve maintainability**: Future contributors immediately know which tests are for backward compatibility vs. canonical examples.
2. **Intentional legacy tests are valuable**: Files like `test_queue_njr_path.py` explicitly validate migration paths and should be kept.
3. **Deletion > refactoring for adapter tests**: The `test_legacy_njr_adapter.py` tested a migration shim that should not be a canonical pattern — deletion was correct.

---

## Next Steps

- ✅ **PR-TEST-001**: Controller archive cleanup (completed)
- ✅ **PR-TEST-002**: Legacy import purge (completed)
- 🔲 **PR-TEST-003**: Modernize journey tests to use real NJR execution (next)
- 🔲 **PR-TEST-004**: Implement Golden Path tests (GP1-GP15) and compat fixtures
