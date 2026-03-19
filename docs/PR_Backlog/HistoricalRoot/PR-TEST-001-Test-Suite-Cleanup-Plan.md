# PR-TEST-001: Test Suite Technical Debt Cleanup

**Date:** January 1, 2026  
**Based On:** D-TEST-001 Discovery  
**Approach:** Phased Cleanup (Option A)  
**Status:** 📋 PLANNING COMPLETE

---

## Executive Summary

Comprehensive test suite modernization to address technical debt from CORE1 architectural transition. Fixes 26 affected files across 3 phases, targeting 100% passing test suite with improved performance.

**Scope:** 3 PRs, 18-24 hours total effort  
**Impact:** Restore ~10 test files, fix 11 failing tests, improve performance  
**Risk:** Low - incremental approach with verification gates

---

## Phased Approach

### Phase A: Critical Path (PR-TEST-001-A)
**Focus:** Fix QueueJobV2 deprecation (P0)  
**Effort:** 4-6 hours  
**Files:** 10 test files in `tests/gui_v2/`  
**Blocker:** None  

### Phase B: API & Performance (PR-TEST-001-B)
**Focus:** Fix API test failures + performance issues (P1)  
**Effort:** 7-10 hours  
**Files:** 11 API tests, test infrastructure  
**Blocker:** Phase A completion recommended but not required  

### Phase C: Remaining Debt (PR-TEST-001-C)
**Focus:** Path errors, encoding, infrastructure (P2-P3)  
**Effort:** 4-5 hours  
**Files:** 5 test files, pytest configuration  
**Blocker:** None (can run parallel to B)  

---

## PR-TEST-001-A: QueueJobV2 Deprecation Fixes

### Objective
Update all GUI v2 tests to use `UnifiedJobSummary` instead of deprecated `QueueJobV2` class.

### Success Criteria
- ✅ All 10 GUI v2 test files execute without import errors
- ✅ All GUI v2 tests pass (or fail for valid reasons, not imports)
- ✅ Zero references to `QueueJobV2` in test files
- ✅ No regressions in core tests

### Allowed Files
```
tests/gui_v2/test_job_queue_v2.py
tests/gui_v2/test_queue_panel_autorun_and_send_job_v2.py
tests/gui_v2/test_queue_panel_behavior_v2.py
tests/gui_v2/test_queue_panel_eta.py
tests/gui_v2/test_queue_panel_move_feedback.py
tests/gui_v2/test_queue_panel_v2.py
tests/gui_v2/test_queue_panel_v2_normalized_jobs.py
tests/gui_v2/test_queue_persistence_v2.py
tests/gui_v2/test_running_job_panel_controls_v2.py
tests/gui_v2/test_running_job_panel_v2.py
```

### Forbidden Files
- Any production code in `src/`
- Other test directories
- Configuration files

### Implementation Steps

#### Step 1: Update Import Statements
**Action:** Replace all QueueJobV2 imports with UnifiedJobSummary

**Find:**
```python
from src.pipeline.job_models_v2 import JobStatusV2, QueueJobV2
from src.pipeline.job_models_v2 import QueueJobV2
```

**Replace with:**
```python
from src.pipeline.job_models_v2 import JobStatusV2, UnifiedJobSummary
from src.pipeline.job_models_v2 import UnifiedJobSummary
```

**Files:** All 10 listed above

#### Step 2: Update Class References
**Action:** Replace QueueJobV2 usage with UnifiedJobSummary

**Pattern 1: Object Creation**
```python
# BEFORE:
job = QueueJobV2.create(config)

# AFTER:
# UnifiedJobSummary doesn't have .create() - use from_njr() or constructor
from src.pipeline.job_models_v2 import NormalizedJobRecord
njr = NormalizedJobRecord(job_id="test", config=config, ...)
job = UnifiedJobSummary.from_njr(njr)
```

**Pattern 2: Type Annotations**
```python
# BEFORE:
def handle_job(job: QueueJobV2) -> None:

# AFTER:
def handle_job(job: UnifiedJobSummary) -> None:
```

**Pattern 3: Test Fixtures**
```python
# BEFORE:
@pytest.fixture
def sample_job():
    return QueueJobV2.create({"prompt": "test"})

# AFTER:
@pytest.fixture
def sample_job():
    njr = NormalizedJobRecord(
        job_id="test-001",
        config={"prompt": "test"},
        path_output_dir="./output",
        filename_template="test_{index}",
        positive_prompt="test",
        stage_chain=[]
    )
    return UnifiedJobSummary.from_njr(njr)
```

#### Step 3: Handle API Differences

**QueueJobV2 Methods → UnifiedJobSummary Equivalents:**

| QueueJobV2 Method | UnifiedJobSummary Equivalent |
|-------------------|------------------------------|
| `QueueJobV2.create(config)` | `UnifiedJobSummary.from_njr(njr)` |
| `job.to_dict()` | `asdict(job)` (from dataclasses) |
| `QueueJobV2.from_dict(data)` | Create NJR, then `.from_njr()` |
| `job.get_display_summary()` | May need manual formatting |

**Action:** Update each test's logic to use new API.

#### Step 4: Verify Test Logic Still Valid

**Check for:**
1. **Test Intent:** Does the test still test what it's supposed to?
2. **Assertions:** Are assertions still meaningful?
3. **Mocking:** Do mocks match new API?

**Example Review:**
```python
# tests/gui_v2/test_job_queue_v2.py::test_queue_job_v2_unique_ids
# OLD: Tests that QueueJobV2.create() generates unique IDs
# NEW: Tests that NormalizedJobRecord creates unique job_ids
# VERDICT: Still valid, but now testing NJR not QueueJobV2
```

#### Step 5: Run Tests & Fix Failures

**Command:**
```bash
pytest tests/gui_v2/ -v --tb=short
```

**Expected Issues:**
1. Missing NJR fields (add required fields)
2. API mismatches (consult job_models_v2.py)
3. Assertion failures (update expectations)

**Iterative Process:**
- Fix one test file at a time
- Run that file's tests
- Move to next file

#### Step 6: Verify No Regressions

**Command:**
```bash
# Run core tests that were passing before
pytest tests/queue/ tests/pipeline/ -v
```

**Success:** All previously passing tests still pass.

### Test Plan

1. **Smoke Test:** Import each modified file
   ```bash
   python -c "import tests.gui_v2.test_job_queue_v2"
   ```
   
2. **Unit Test:** Run each file individually
   ```bash
   pytest tests/gui_v2/test_job_queue_v2.py -v
   ```

3. **Integration Test:** Run all GUI v2 tests
   ```bash
   pytest tests/gui_v2/ -v
   ```

4. **Regression Test:** Run core test suite
   ```bash
   pytest tests/queue/ tests/pipeline/ tests/controller/ -v
   ```

### Documentation Updates

**File:** `docs/D-TEST-001-Test-Suite-Technical-Debt-Discovery.md`  
**Update:** Mark Category 1 as RESOLVED, add PR reference

**File:** `CHANGELOG.md`  
**Entry:**
```markdown
### [PR-TEST-001-A] Test Suite - QueueJobV2 Deprecation Fixes
- Updated 10 GUI v2 test files to use UnifiedJobSummary instead of deprecated QueueJobV2
- Fixed: tests/gui_v2/test_job_queue_v2.py (and 9 others)
- All GUI v2 panel tests now executable
```

### Rollback Plan

If issues arise:
1. Revert commits for PR-TEST-001-A
2. GUI v2 tests return to collection error state
3. No production code affected

### Time Estimate

- **Step 1 (Imports):** 30 minutes (bulk find/replace)
- **Step 2 (References):** 2-3 hours (manual updates per test)
- **Step 3 (API):** 1-2 hours (handle edge cases)
- **Step 4 (Verification):** 30 minutes (review logic)
- **Step 5 (Fixes):** 1-2 hours (iterative debugging)
- **Step 6 (Regression):** 30 minutes (run core tests)
- **Total:** **6-9 hours** (conservatively 8 hours)

---

## PR-TEST-001-B: API Test Failures & Performance

### Objective
Fix 11 failing API tests and improve test suite performance to complete execution.

### Success Criteria
- ✅ All API tests in test_webui_process_manager*.py pass
- ✅ test_healthcheck_v2.py passes
- ✅ Test suite completes execution in <15 minutes
- ✅ No tests hang or timeout

### Allowed Files
```
tests/api/test_healthcheck_v2.py
tests/api/test_webui_process_manager.py
tests/api/test_webui_process_manager_restart_ready.py
tests/conftest.py (for performance fixes)
pytest.ini (for timeout configuration)
```

### Forbidden Files
- Production code in `src/` (unless genuine bug found)
- Other test directories

### Implementation Steps

#### Step 1: Investigate API Test Failures

**Action:** Run failing tests individually with full traceback

**Commands:**
```bash
pytest tests/api/test_healthcheck_v2.py::test_wait_for_webui_ready_does_not_return_true_on_progress_only -vvs
pytest tests/api/test_webui_process_manager.py::test_start_invokes_subprocess_with_config -vvs
pytest tests/api/test_webui_process_manager_restart_ready.py::test_restart_returns_true_when_wait_ready_succeeds -vvs
```

**Expected Findings:**
1. Mock expectations not matching actual API calls
2. Changed method signatures
3. New required parameters
4. Async behavior changes

**Document:**
Create `test_failures_analysis.md` with:
- Test name
- Error message
- Root cause
- Fix approach

#### Step 2: Fix Mock Configurations

**Pattern:** Update mock setup to match current API

**Example (Hypothetical):**
```python
# BEFORE (test_webui_process_manager.py):
mock_subprocess.return_value = mock_process

# AFTER:
mock_subprocess.return_value = mock_process
mock_process.pid = 12345  # New required attribute
```

**Action:** For each failing test:
1. Identify the mock being used
2. Check actual implementation in `src/api/`
3. Update mock to match current behavior
4. Run test to verify

#### Step 3: Investigate Performance Issues

**Action:** Profile test execution

**Commands:**
```bash
# Get slowest tests
pytest tests/ --durations=20 --tb=no

# Run with timeout to identify hangs
pytest tests/ --timeout=10 --timeout-method=thread
```

**Expected Findings:**
- Tests with network calls not properly mocked
- Tests with sleep() calls
- Tests with infinite loops
- Tests waiting for external resources

#### Step 4: Fix Performance Issues

**Pattern 1: Add Timeouts**
```python
# In pytest.ini:
[pytest]
timeout = 10
timeout_method = thread
```

**Pattern 2: Mock Slow Operations**
```python
# BEFORE:
def test_something():
    time.sleep(5)  # Simulating slow operation
    assert result

# AFTER:
def test_something(monkeypatch):
    monkeypatch.setattr("time.sleep", lambda x: None)
    assert result
```

**Pattern 3: Parallelize**
```bash
# Install pytest-xdist
pip install pytest-xdist

# Run tests in parallel
pytest tests/ -n auto
```

#### Step 5: Identify Hanging Test

**Action:** Binary search through test files

**Process:**
1. Run first half of tests
2. If hangs, repeat on first quarter
3. If doesn't hang, run second half
4. Continue until single test identified

**Command Pattern:**
```bash
pytest tests/api/test_webui_resources.py -v  # Last test before hang
pytest tests/api/test_webui_resources.py::test_api_backed_discovery -v
```

**Once Found:** Either fix or mark as `@pytest.mark.slow` and skip

#### Step 6: Run Full Suite

**Command:**
```bash
pytest tests/ --ignore=tests/gui/ --ignore=tests/gui_v2/ -v --tb=short
```

**Success:** All tests complete in <15 minutes

### Test Plan

1. **Individual:** Run each fixed test in isolation
2. **API Suite:** Run all API tests together
3. **Performance:** Measure execution time
4. **Full Suite:** Run complete test suite

### Documentation Updates

**File:** `docs/D-TEST-001-Test-Suite-Technical-Debt-Discovery.md`  
**Update:** Mark Category 2 and Category 7 as RESOLVED

**File:** `docs/TEST-PERFORMANCE-IMPROVEMENTS.md` (new)  
**Content:** Document performance fixes, before/after metrics

### Rollback Plan

- Revert mock changes if tests start failing
- Remove timeout configuration if causing false negatives
- No production code risk

### Time Estimate

- **Step 1 (Investigate):** 2 hours
- **Step 2 (Fix Mocks):** 2-3 hours
- **Step 3 (Profile):** 1 hour
- **Step 4 (Fix Performance):** 2-3 hours
- **Step 5 (Hanging Test):** 1 hour
- **Step 6 (Full Suite):** 1 hour
- **Total:** **9-13 hours** (conservatively 11 hours)

---

## PR-TEST-001-C: Remaining Technical Debt

### Objective
Fix path construction errors, unicode encoding issues, and configure test infrastructure.

### Success Criteria
- ✅ All reprocess tests execute
- ✅ All script tests execute
- ✅ Stage chain test passes or has clear rationale
- ✅ Tkinter tests skipped in CI (not failing)
- ✅ Documentation updated

### Allowed Files
```
tests/pipeline/test_reprocess_batching.py
tests/test_reprocess_batching.py
tests/scripts/test_full_flow.py
tests/scripts/test_img2img_bug.py
tests/test_stage_chain_fix.py
pytest.ini
.github/workflows/*.yml (if CI config needed)
docs/D-TEST-001-Test-Suite-Technical-Debt-Discovery.md
docs/TESTING.md (new)
```

### Forbidden Files
- Production code (unless stage chain test reveals genuine bug)

### Implementation Steps

#### Step 1: Fix Path Construction Errors

**Files:**
- `tests/pipeline/test_reprocess_batching.py`
- `tests/test_reprocess_batching.py`

**Before:**
```python
import importlib.util

spec = importlib.util.spec_from_file_location(
    "reprocess_builder",
    "src/pipeline/reprocess_builder.py"  # Wrong path
)
reprocess_builder = importlib.util.module_from_spec(spec)
spec.loader.exec_module(reprocess_builder)
```

**After:**
```python
# Use standard import
from src.pipeline import reprocess_builder

# Or if dynamic loading truly needed:
from pathlib import Path

project_root = Path(__file__).parent.parent
builder_path = project_root / "src" / "pipeline" / "reprocess_builder.py"
spec = importlib.util.spec_from_file_location("reprocess_builder", str(builder_path))
reprocess_builder = importlib.util.module_from_spec(spec)
spec.loader.exec_module(reprocess_builder)
```

**Recommendation:** Use standard import unless there's a specific reason not to.

#### Step 2: Fix Unicode Encoding

**Files:**
- `tests/scripts/test_full_flow.py` (line 73)
- `tests/scripts/test_img2img_bug.py` (line 94)

**Before:**
```python
print("�o. VALUES CORRECT")  # Line 73
print("�o. BUG FIXED - Values are correct!")  # Line 94
```

**After:**
```python
print("OK. VALUES CORRECT")  # Line 73
print("PASS. BUG FIXED - Values are correct!")  # Line 94
```

**Action:** Open files in UTF-8 editor, replace corrupted characters with ASCII.

#### Step 3: Investigate Stage Chain Test

**File:** `tests/test_stage_chain_fix.py`

**Investigation Steps:**
1. Read StageConfig definition in `src/pipeline/job_models_v2.py`
2. Check `enabled` field default value
3. Run test with debug output:
   ```python
   for stage in stage_chain:
       print(f"Stage: {stage.stage_type}, enabled: {getattr(stage, 'enabled', 'MISSING')}")
   ```
4. Trace through `build_run_plan_from_njr()` with debugger

**Possible Outcomes:**

**Outcome A: StageConfig.enabled defaults to False**
- **Fix:** Update test to set `enabled=True` explicitly
- **Code:**
  ```python
  stage_chain=[
      StageConfig(stage_type="txt2img", enabled=True),
      StageConfig(stage_type="adetailer", enabled=True),
      StageConfig(stage_type="upscale", enabled=True),
  ]
  ```

**Outcome B: Builder has regression**
- **Fix:** Fix builder logic in `src/pipeline/run_plan.py`
- **Root Cause:** Likely an incorrect check like `if stage_config.enabled:` instead of `if getattr(stage_config, "enabled", True):`

**Outcome C: Test is outdated**
- **Fix:** Update test to match current expected behavior
- **Document:** Explain why 1 job is correct

#### Step 4: Configure Tkinter Test Skipping

**File:** `pytest.ini`

**Add:**
```ini
[pytest]
addopts = 
    --ignore=tests/gui/
    --ignore=tests/test_pipeline_tab_render.py
    --ignore=tests/test_stage_cards_panel.py
    --ignore=tests/test_pipeline_tab.py
    --ignore=tests/test_all_stage_cards.py
    -v
```

**Alternative (More Flexible):**
```ini
[pytest]
markers =
    gui: marks tests as requiring GUI environment (tkinter)

# Then mark GUI tests:
@pytest.mark.gui
def test_something():
    ...

# Run non-GUI tests:
pytest -m "not gui"
```

#### Step 5: Create Testing Documentation

**File:** `docs/TESTING.md`

**Content:**
```markdown
# StableNew Testing Guide

## Running Tests

### Full Suite
```bash
pytest tests/
```

### Core Tests Only (Fast)
```bash
pytest tests/queue/ tests/pipeline/ tests/controller/
```

### Skip GUI Tests
```bash
pytest tests/ -m "not gui"
```

### With Coverage
```bash
pytest tests/ --cov=src --cov-report=html
```

## Test Organization

- `tests/queue/` - Job queue system tests
- `tests/pipeline/` - Pipeline execution tests
- `tests/controller/` - Controller integration tests
- `tests/api/` - WebUI API client tests
- `tests/gui_v2/` - GUI v2 panel tests (requires tkinter)
- `tests/integration/` - End-to-end workflow tests

## Troubleshooting

### Tkinter Errors
If you see "Can't find a usable init.tcl", GUI tests cannot run.
Solution: Run with `-m "not gui"` or fix Python tkinter installation.

### Slow Tests
Use `pytest --durations=20` to identify slow tests.

### Hanging Tests
Use `pytest --timeout=10` to prevent infinite loops.

## Writing Tests

- Follow TDD: Write test before implementation
- Use descriptive test names: `test_<what>_<scenario>_<expected>`
- Mock external dependencies (WebUI, filesystem, network)
- Keep tests fast (<1 second each)
- Mark slow tests: `@pytest.mark.slow`
```

### Test Plan

1. **Reprocess:** `pytest tests/pipeline/test_reprocess_batching.py tests/test_reprocess_batching.py -v`
2. **Scripts:** `pytest tests/scripts/test_full_flow.py tests/scripts/test_img2img_bug.py -v`
3. **Stage Chain:** `pytest tests/test_stage_chain_fix.py -v`
4. **Full Suite:** `pytest tests/ -v`

### Documentation Updates

**File:** `docs/D-TEST-001-Test-Suite-Technical-Debt-Discovery.md`  
**Update:** Mark all categories as RESOLVED

**File:** `CHANGELOG.md`  
**Entry:**
```markdown
### [PR-TEST-001-C] Test Suite - Infrastructure & Cleanup
- Fixed path construction errors in reprocess tests
- Fixed unicode encoding in script tests
- Investigated and fixed stage chain test
- Configured pytest to skip GUI tests in CI
- Added comprehensive testing documentation
```

### Rollback Plan

- Configuration changes easily reverted
- No production code changes (unless stage chain bug found)
- Documentation updates are additive

### Time Estimate

- **Step 1 (Path Fixes):** 30 minutes
- **Step 2 (Encoding):** 15 minutes
- **Step 3 (Stage Chain):** 1-2 hours
- **Step 4 (Tkinter Config):** 30 minutes
- **Step 5 (Documentation):** 1 hour
- **Total:** **3-4 hours**

---

## Overall Implementation Strategy

### Execution Order
1. **Week 1:** PR-TEST-001-A (QueueJobV2 fixes) - 8 hours
2. **Week 2:** PR-TEST-001-B (API/Performance) - 11 hours
3. **Week 2:** PR-TEST-001-C (Remaining) - 3 hours (parallel to B)

**Total:** 22 hours over 2 weeks

### Review Process
- Each PR reviewed before next starts
- Run full test suite before merging each PR
- Document any discovered issues for future PRs

### Success Metrics

**Before:**
- ❌ 15 collection errors
- ❌ 11 API test failures
- ❌ Test suite hung at 9%
- ❌ ~90% of tests not running

**After:**
- ✅ 0 collection errors
- ✅ All API tests passing
- ✅ Test suite completes in <15 minutes
- ✅ ~95%+ tests running and passing

---

## Risk Mitigation

### Risk: Breaking Working Tests
**Mitigation:** Run regression suite before/after each change

### Risk: Discovering New Issues
**Mitigation:** Document and defer to future PRs if not critical

### Risk: Time Overruns
**Mitigation:** Timeboxed investigation, escalate if stuck >2 hours

### Risk: Architecture Issues Uncovered
**Mitigation:** Document, create separate discovery/PR for architecture fixes

---

## Dependencies

### External
- pytest, pytest-xdist (for parallel execution)
- pytest-timeout (for hanging tests)

### Internal
- Understanding of UnifiedJobSummary API
- Access to StageConfig definition
- Understanding of WebUI API contract

---

## Communication Plan

### Before Each PR
- Post PR plan in discussion
- Get approval from product owner (Rob)
- Confirm no conflicts with other work

### During Implementation
- Daily updates on progress
- Flag blockers immediately
- Share findings from investigations

### After Each PR
- Post completion summary
- Update discovery document with resolutions
- Celebrate wins! 🎉

---

## Conclusion

Comprehensive 3-phase plan to restore test suite health. Phased approach allows for incremental progress, early wins, and manageable reviews.

**Total Effort:** 18-24 hours  
**Timeline:** 2 weeks  
**Risk:** Low (incremental, well-defined)  
**Impact:** HIGH (restored test coverage, improved confidence)

---

**Planning Status:** ✅ COMPLETE  
**Ready for Execution:** YES  
**Recommended Next Action:** Begin PR-TEST-001-A (QueueJobV2 fixes)
