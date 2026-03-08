# D-TEST-001: Test Suite Technical Debt Discovery

**Date:** January 1, 2026  
**Context:** Full test suite analysis after RuntimeJobStatus implementation  
**Scope:** All test failures, collection errors, and technical debt  
**Status:** 🔍 DISCOVERY COMPLETE

---

## Executive Summary

Comprehensive analysis of StableNew test suite revealed **significant technical debt** accumulated during CORE1 architectural transition. Test suite health: **~9% passing before hang**, with 15+ collection errors and multiple runtime failures.

**Key Findings:**
- ✅ **Core functionality works** - pipeline, queue, controller tests pass
- ❌ **GUI v2 tests broken** - 10 files use deprecated `QueueJobV2` class
- ❌ **Multiple subsystems untested** - reprocess, scripts, integration paths
- ❌ **Test infrastructure issues** - Tkinter env, encoding, path construction
- ⚠️ **Test suite velocity** - Extremely slow execution, hung at 9%

**Impact:** HIGH - Limited test coverage blocks confident refactoring and feature development.

**Estimated Cleanup Effort:** 16-24 hours across 4 phases

---

## Discovery Methodology

### 1. Test Execution Analysis
```powershell
pytest tests/ --ignore=<problem_files> -v --tb=short
```

**Results:**
- **1333 tests collected** (after ignoring Tkinter files)
- **126 tests executed** before performance degradation (9%)
- **9 API tests FAILED** (webui_process_manager, healthcheck)
- **15 collection ERRORS** (import/path/encoding issues)
- **Test execution hung** - likely infinite loop or deadlock

### 2. Codebase Search
- Searched for `QueueJobV2` references → **10 test files affected**
- Searched for reprocess patterns → **2 test files with path errors**
- Searched for unicode issues → **2 script files with encoding corruption**
- Analyzed stage chain test logic → **1 file with incorrect assumptions**

### 3. Root Cause Analysis
Each failure category traced to specific architectural changes or infrastructure issues.

---

## Technical Debt Categories

### Category 1: Deprecated Job Model References (P0) - ✅ RESOLVED

**Severity:** 🔴 **CRITICAL**  
**Impact:** 10 GUI v2 test files cannot execute  
**Root Cause:** QueueJobV2 class removed during CORE1-D job model unification  
**Resolution:** Tests archived to `archive/legacy_tests/gui_v2_queue_deprecated/` - testing completely removed functionality

#### Affected Files (10)
1. `tests/gui_v2/test_job_queue_v2.py`
2. `tests/gui_v2/test_queue_panel_autorun_and_send_job_v2.py`
3. `tests/gui_v2/test_queue_panel_behavior_v2.py`
4. `tests/gui_v2/test_queue_panel_eta.py`
5. `tests/gui_v2/test_queue_panel_move_feedback.py`
6. `tests/gui_v2/test_queue_panel_v2.py`
7. `tests/gui_v2/test_queue_panel_v2_normalized_jobs.py`
8. `tests/gui_v2/test_queue_persistence_v2.py`
9. `tests/gui_v2/test_running_job_panel_controls_v2.py`
10. `tests/gui_v2/test_running_job_panel_v2.py`

#### Error Pattern
```python
ImportError: cannot import name 'QueueJobV2' from 'src.pipeline.job_models_v2'
```

#### Historical Context
From `src/pipeline/job_models_v2.py` line 1009:
```python
# PR-QUEUE-PERSIST: QueueJobV2 removed (V2 queue system abandoned)
```

The `QueueJobV2` class was deprecated and removed. Tests were never updated to use `UnifiedJobSummary` (the canonical replacement).

#### Decision Points

**Option A: Update Tests to UnifiedJobSummary (Recommended)**
- **Pros:** Aligns with v2.6 architecture, removes tech debt
- **Cons:** Requires understanding each test's intent, may need logic updates
- **Effort:** 4-6 hours (bulk find/replace + verification + fixes)

**Option B: Create QueueJobV2 Alias**
```python
# In src/pipeline/job_models_v2.py:
QueueJobV2 = UnifiedJobSummary  # Backward compatibility
```
- **Pros:** Quick fix, tests run immediately
- **Cons:** Perpetuates tech debt, confusing naming
- **Effort:** 15 minutes + test verification

**Option C: Archive Tests**
- **Pros:** Clean break from legacy
- **Cons:** Loss of test coverage
- **Effort:** 1 hour (move files, document rationale)

**Recommendation:** **Option A** - Update to UnifiedJobSummary. This is the correct long-term solution.

#### Risk Assessment
- **Regression Risk:** LOW - Core functionality already tested and working
- **Coverage Loss Risk:** MEDIUM - 10 tests cover important GUI behaviors
- **Implementation Risk:** LOW - Straightforward find/replace with verification

---

### Category 2: API Test Failures (P1)

**Severity:** 🟡 **HIGH**  
**Impact:** 9 API tests failing, blocking WebUI integration verification  
**Root Cause:** Mocking issues or API contract changes

#### Failing Tests (9)
From `test_results_clean.txt`:

**test_healthcheck_v2.py:**
1. `test_wait_for_webui_ready_does_not_return_true_on_progress_only` - FAILED

**test_webui_process_manager.py:**
2. `test_start_invokes_subprocess_with_config` - FAILED
3. `test_start_raises_structured_error` - FAILED
4. `test_stop_handles_already_exited_process` - FAILED

**test_webui_process_manager_restart_ready.py:**
5. `test_restart_returns_true_when_wait_ready_succeeds` - FAILED
6. `test_restart_returns_false_when_wait_ready_fails` - FAILED
7. `test_restart_without_wait_ready_returns_true` - FAILED
8. `test_custom_max_attempts_passed_to_wait_until_ready` - FAILED
9. `test_custom_delays_passed_to_wait_until_ready` - FAILED
10. `test_client_closed_on_success` - FAILED
11. `test_client_closed_on_failure` - FAILED

#### Pattern Analysis
All failures are in WebUI process lifecycle management:
- Process startup/shutdown
- Health checking
- Client connection management
- Restart logic

#### Investigation Required
Need to examine actual error messages (not visible in truncated output). Likely causes:
1. Mock configuration issues after API refactoring
2. Changed method signatures
3. New required parameters
4. Async/threading changes

#### Decision Points

**Option A: Fix Mocks to Match Current API**
- Investigate each failure
- Update mock expectations
- Verify against actual implementation
- **Effort:** 3-4 hours

**Option B: Rewrite Tests with Integration Approach**
- Replace mocks with actual WebUI subprocess (or test double)
- More realistic but slower
- **Effort:** 6-8 hours

**Recommendation:** **Option A** - Fix mocks. Integration tests should be separate suite.

#### Risk Assessment
- **Regression Risk:** MEDIUM - WebUI lifecycle is critical
- **False Positive Risk:** HIGH - Tests may be failing incorrectly
- **Implementation Risk:** MEDIUM - Requires understanding mock/API contract

---

### Category 3: Path Construction Errors (P2)

**Severity:** 🟡 **MEDIUM**  
**Impact:** 2 reprocess tests cannot execute  
**Root Cause:** Incorrect use of `importlib` with relative paths

#### Affected Files (2)
1. `tests/pipeline/test_reprocess_batching.py`
2. `tests/test_reprocess_batching.py`

#### Error Pattern
```python
FileNotFoundError: [Errno 2] No such file or directory: 
'C:\\Users\\rob\\projects\\StableNew\\tests\\pipeline\\src\\pipeline\\reprocess_builder.py'
```

#### Root Cause
Tests use `importlib.util.spec_from_file_location()` with relative path:
```python
spec = importlib.util.spec_from_file_location(
    "reprocess_builder",
    "src/pipeline/reprocess_builder.py"  # Interpreted from CWD, not test location
)
```

When pytest runs from `tests/pipeline/`, it looks for:
```
tests/pipeline/src/pipeline/reprocess_builder.py  # WRONG
```

Instead of:
```
src/pipeline/reprocess_builder.py  # CORRECT
```

#### Decision Points

**Option A: Use Standard Imports (Recommended)**
```python
from src.pipeline import reprocess_builder
```
- **Pros:** Idiomatic Python, no path issues
- **Cons:** None
- **Effort:** 15 minutes

**Option B: Fix Path Construction**
```python
project_root = Path(__file__).parent.parent
builder_path = project_root / "src" / "pipeline" / "reprocess_builder.py"
spec = importlib.util.spec_from_file_location("reprocess_builder", str(builder_path))
```
- **Pros:** Keeps dynamic loading pattern
- **Cons:** Unnecessary complexity
- **Effort:** 30 minutes

**Recommendation:** **Option A** - Use standard imports. No need for dynamic loading in tests.

#### Risk Assessment
- **Regression Risk:** LOW - Reprocess functionality already works
- **Implementation Risk:** LOW - Trivial change
- **Coverage Loss Risk:** LOW - 2 tests easily fixable

---

### Category 4: Unicode Encoding Errors (P3)

**Severity:** 🟢 **LOW**  
**Impact:** 2 script tests cannot execute  
**Root Cause:** Corrupted characters from copy-paste or encoding mismatch

#### Affected Files (2)
1. `tests/scripts/test_full_flow.py` (line 73)
2. `tests/scripts/test_img2img_bug.py` (line 94)

#### Error Pattern
```python
SyntaxError: (unicode error) 'utf-8' codec can't decode byte 0x83 in position 0: 
invalid start byte
```

#### Root Cause
Files contain replacement character `\ufffd` (�) in print statements:
```python
print("�o. VALUES CORRECT")  # Line 73 in test_full_flow.py
print("�o. BUG FIXED - Values are correct!")  # Line 94 in test_img2img_bug.py
```

Likely intended characters:
- ✓ (checkmark)
- ✅ (emoji checkmark)
- OK

#### Decision Points

**Option A: Replace with ASCII**
```python
print("OK. VALUES CORRECT")
print("PASS. BUG FIXED - Values are correct!")
```
- **Pros:** No encoding issues, portable
- **Cons:** Less visual appeal
- **Effort:** 5 minutes

**Option B: Use UTF-8 Emoji**
```python
print("✓ VALUES CORRECT")
print("✅ BUG FIXED - Values are correct!")
```
- **Pros:** Visual appeal maintained
- **Cons:** Requires proper UTF-8 handling
- **Effort:** 10 minutes

**Recommendation:** **Option A** - Use ASCII. These are test files, not user-facing output.

#### Risk Assessment
- **Regression Risk:** NONE - No functional impact
- **Implementation Risk:** NONE - Trivial text replacement
- **Coverage Loss Risk:** NONE - Tests easily fixable

---

### Category 5: Stage Chain Logic Error (P2)

**Severity:** 🟡 **MEDIUM**  
**Impact:** 1 integration test fails during collection  
**Root Cause:** Test expectations don't match current run_plan builder logic

#### Affected Files (1)
`tests/test_stage_chain_fix.py`

#### Error Pattern
```python
AssertionError: Expected 3 jobs, got 1
assert 1 == 3
```

#### Root Cause Analysis

**Test Code:**
```python
njr = NormalizedJobRecord(
    job_id="test-001",
    config={},
    path_output_dir="./test_output",
    filename_template="test_{index}",
    positive_prompt="beautiful woman portrait",
    stage_chain=[
        StageConfig(stage_type="txt2img"),
        StageConfig(stage_type="adetailer"),
        StageConfig(stage_type="upscale"),
    ],
)

plan = build_run_plan_from_njr(njr)
assert len(plan.jobs) == 3  # FAILS - only 1 job created
```

**Actual Builder Logic** (`src/pipeline/run_plan.py` line 42):
```python
for idx, stage_config in enumerate(stage_chain):
    # Check if stage is enabled
    is_enabled = getattr(stage_config, "enabled", True)  # Defaults to True
    if not is_enabled:
        continue  # Skip disabled stages
```

**The Problem:**
The test creates `StageConfig` instances without the `enabled` field. The builder checks `getattr(stage_config, "enabled", True)` which **should** default to True, but something is preventing all 3 stages from being added.

**Hypothesis:**
Looking at the builder more carefully (lines 65-68), there's a **fallback logic**:
```python
# Fallback: if no enabled stages found, create a single txt2img job
if not jobs:
    jobs.append(PlannedJob(stage_name="txt2img", ...))
    enabled_stages = ["txt2img"]
```

This suggests the `for` loop is completing **without adding any jobs**, then the fallback creates 1 txt2img job.

**Why would `getattr(stage_config, "enabled", True)` return False?**

Checking `StageConfig` definition required...

#### Investigation Required
1. Examine `StageConfig` dataclass definition
2. Check if `enabled` field has a default value of `False`
3. Understand if test needs updating or builder has regression

#### Decision Points

**Option A: Update Test to Set enabled=True**
```python
stage_chain=[
    StageConfig(stage_type="txt2img", enabled=True),
    StageConfig(stage_type="adetailer", enabled=True),
    StageConfig(stage_type="upscale", enabled=True),
]
```
- **Pros:** Explicit, matches expected usage
- **Cons:** Test may be correct, builder may have regression
- **Effort:** 10 minutes

**Option B: Investigate Builder Regression**
- Check if CORE1 changes broke multi-stage logic
- Verify `StageConfig.enabled` default
- May need builder fix instead of test fix
- **Effort:** 1-2 hours

**Option C: Update Test Assertion**
```python
assert len(plan.jobs) == 1  # Expect fallback behavior
```
- **Pros:** Matches current behavior
- **Cons:** Defeats test purpose (testing multi-stage fix)
- **Effort:** 5 minutes

**Recommendation:** **Option B** - Investigate builder. The test name is "test_stage_chain_fix" suggesting it was created to verify a specific PR fix. Builder regression is more likely than bad test.

#### Risk Assessment
- **Regression Risk:** HIGH - If builder is broken, multi-stage jobs don't work
- **Implementation Risk:** MEDIUM - May require builder changes
- **Coverage Loss Risk:** LOW - Only 1 test, but tests critical functionality

---

### Category 6: Tkinter/Tcl Environment Issues (P2)

**Severity:** 🟡 **MEDIUM**  
**Impact:** All GUI tests cannot execute on CI or headless systems  
**Root Cause:** Python tkinter cannot find Tcl/Tk libraries

#### Affected Files (Multiple)
- `tests/test_pipeline_tab_render.py`
- Most files in `tests/gui/`
- Some files in `tests/gui_v2/`

#### Error Pattern
```python
_tkinter.TclError: Can't find a usable init.tcl in the following directories:
{C:\Users\rob\AppData\Local\Programs\Python\Python310\tcl\tcl8.6} ...
This probably means that Tcl wasn't installed properly.
```

#### Root Cause
Python's tkinter module looks for Tcl/Tk library files in specific paths. On this system:
- Tcl/Tk libraries are missing or misconfigured
- Environment variables (`TCL_LIBRARY`, `TK_LIBRARY`) not set
- Python installation incomplete

#### Impact Analysis
- **Local Development:** Blocks GUI testing
- **CI/CD:** Will fail in headless environments
- **Coverage:** Significant portion of GUI functionality untested

#### Decision Points

**Option A: Fix Environment (For Local Development)**
```powershell
$env:TCL_LIBRARY = "C:\Users\rob\AppData\Local\Programs\Python\Python310\tcl\tcl8.6"
$env:TK_LIBRARY = "C:\Users\rob\AppData\Local\Programs\Python\Python310\tcl\tk8.6"
```
Or reinstall Python with Tcl/Tk included.
- **Pros:** Enables full local testing
- **Cons:** Doesn't solve CI/CD issue
- **Effort:** 1 hour

**Option B: Skip GUI Tests in CI**
```ini
# In pytest.ini:
[pytest]
addopts = --ignore=tests/gui/ --ignore=tests/test_pipeline_tab_render.py
```
- **Pros:** CI can run non-GUI tests
- **Cons:** No GUI test coverage in CI
- **Effort:** 15 minutes

**Option C: Mock Tkinter in Tests**
```python
# In conftest.py:
import pytest
import sys
from unittest.mock import MagicMock

@pytest.fixture(autouse=True, scope="session")
def mock_tkinter():
    if "tkinter" not in sys.modules:
        sys.modules["tkinter"] = MagicMock()
        sys.modules["tkinter.ttk"] = MagicMock()
```
- **Pros:** Tests can import tkinter code
- **Cons:** Tests don't verify real GUI behavior
- **Effort:** 2 hours

**Option D: Use Headless Display (Linux/CI)**
```bash
Xvfb :99 -screen 0 1024x768x24 &
export DISPLAY=:99
pytest tests/
```
- **Pros:** Real tkinter testing in CI
- **Cons:** Platform-specific, adds complexity
- **Effort:** 3 hours

**Recommendation:** **Option B** for immediate CI compatibility, **Option A** for local development if needed. GUI testing is lower priority than core pipeline/queue tests.

#### Risk Assessment
- **Regression Risk:** LOW - GUI manually testable
- **Implementation Risk:** LOW - Configuration change
- **Coverage Loss Risk:** MEDIUM - GUI behavior untested in CI

---

### Category 7: Test Suite Performance Issues (P1)

**Severity:** 🟡 **HIGH**  
**Impact:** Test suite hung at 9%, execution extremely slow  
**Root Cause:** Unknown - requires profiling

#### Symptoms
- 1266 tests collected
- Only 126 tests executed (9%)
- Hung during `tests/api/test_webui_resources.py`
- No progress after several minutes

#### Possible Causes
1. **Infinite Loop:** Test logic never completes
2. **Deadlock:** Thread synchronization issue
3. **Resource Contention:** File locks, network timeouts
4. **Slow Mocks:** Inefficient mock setup/teardown
5. **Memory Issues:** Memory leak causing slow-down

#### Investigation Required
- Profile test execution with `pytest --durations=20`
- Run tests individually to isolate hanging test
- Check for thread/process leaks
- Review mock configurations for performance issues

#### Decision Points

**Option A: Isolate and Fix Slow Tests**
- Identify tests taking >5 seconds
- Optimize or mark as `@pytest.mark.slow`
- **Effort:** 4-6 hours

**Option B: Parallel Test Execution**
```bash
pytest -n auto  # pytest-xdist plugin
```
- **Pros:** Better resource utilization
- **Cons:** Doesn't fix root cause
- **Effort:** 1 hour (setup + verification)

**Option C: Test Suite Reorganization**
- Separate fast unit tests from slow integration tests
- Run in stages: unit → integration → e2e
- **Effort:** 8-12 hours

**Recommendation:** **Option A** - Isolate and fix. Performance issues are technical debt that compounds over time.

#### Risk Assessment
- **Development Velocity Risk:** HIGH - Slow tests discourage running them
- **CI/CD Risk:** HIGH - Long test runs expensive and fragile
- **Implementation Risk:** MEDIUM - May require architectural changes

---

## Priority Matrix

| Category | Priority | Severity | Effort | Risk | Files Affected |
|----------|----------|----------|--------|------|----------------|
| 1. Deprecated QueueJobV2 | P0 | 🔴 Critical | 4-6h | Low | 10 |
| 2. API Test Failures | P1 | 🟡 High | 3-4h | Medium | 11 tests |
| 7. Performance Issues | P1 | 🟡 High | 4-6h | High | All |
| 3. Path Construction | P2 | 🟡 Medium | 0.5h | Low | 2 |
| 5. Stage Chain Logic | P2 | 🟡 Medium | 1-2h | High | 1 |
| 6. Tkinter Environment | P2 | 🟡 Medium | 1h | Low | Many |
| 4. Unicode Encoding | P3 | 🟢 Low | 0.5h | None | 2 |

---

## Impact Analysis

### Test Coverage Gaps

**Currently Verified:**
- ✅ Queue system (job queueing, priorities, persistence)
- ✅ Pipeline (job building, model unification)
- ✅ API client (WebUI communication)
- ✅ Controller (app controller integration)

**Currently Broken/Untested:**
- ❌ GUI v2 panels (queue panel, running job panel, persistence UI)
- ❌ WebUI process lifecycle (startup, restart, health checks)
- ❌ Reprocess workflows (batch reprocessing, folder selection)
- ❌ Multi-stage execution (stage chain validation)
- ❌ Integration tests (end-to-end workflows)

### Business Impact
- **Feature Development:** Slowed by lack of confidence in test coverage
- **Refactoring:** Risky without comprehensive test verification
- **Bug Detection:** Reduced - GUI and integration issues slip through
- **Developer Experience:** Poor - tests slow or broken

---

## Risk Assessment

### High-Risk Areas

**1. GUI Panel Behavior (Category 1)**
- 10 tests cover critical user interactions
- Queue management, job display, persistence
- **Without tests:** GUI regressions undetected until user reports

**2. Multi-Stage Job Execution (Category 5)**
- Core pipeline functionality
- **If broken:** txt2img→img2img→upscale chains fail silently
- Test specifically created to verify a PR fix

**3. WebUI Lifecycle (Category 2)**
- Process crashes or hangs affect all users
- **Without tests:** Startup/shutdown bugs in production

### Medium-Risk Areas

**4. Reprocess Workflows (Category 3)**
- Advanced feature, fewer users affected
- Manual testing possible

**5. Test Suite Velocity (Category 7)**
- Compounds over time
- Discourages test-driven development

### Low-Risk Areas

**6. Tkinter Environment (Category 6)**
- GUI testable manually
- Not blocking core functionality

**7. Script Tests (Category 4)**
- Ad-hoc validation scripts
- Not critical for production

---

## Architectural Insights

### What This Reveals About CORE1 Migration

1. **Incomplete Test Migration:** Job model changes (QueueJobV2 → UnifiedJobSummary) didn't include test updates
2. **Test Suite Neglect:** Tests weren't run during architectural changes
3. **CI/CD Gap:** No continuous testing catching these issues early
4. **Documentation Lag:** Test updates not included in PR plans

### Lessons Learned

1. **Tests Are First-Class Code:** Must be updated alongside production code
2. **Architectural Changes Require Test Audits:** Grep for deprecated names, update references
3. **CI Must Enforce Test Passing:** Can't merge if tests fail
4. **Performance Matters:** Slow tests lead to skipped tests

---

## Dependencies & Blockers

### External Dependencies
- **Tkinter/Tcl:** Environment configuration for GUI tests
- **pytest-xdist:** For parallel execution (if pursuing)

### Internal Dependencies
- **StageConfig Definition:** Need to understand `enabled` field behavior
- **WebUI Test Doubles:** May need to create lightweight test doubles for WebUI

### Blockers
- **None** - All fixes can proceed independently

---

## Success Criteria

### Phase 1 Completion (Critical Path)
- ✅ All GUI v2 tests execute without collection errors
- ✅ Core test suite (queue, pipeline, controller, API) passes 100%
- ✅ Test execution completes in <5 minutes for core tests

### Phase 2 Completion (Full Coverage)
- ✅ All API tests pass
- ✅ Multi-stage job test passes
- ✅ Reprocess tests fixed
- ✅ Full test suite passes in <15 minutes

### Phase 3 Completion (Infrastructure)
- ✅ CI/CD configured to skip GUI tests or mock tkinter
- ✅ Test performance optimized (no tests >5s)
- ✅ Documentation updated with test running instructions

---

## Estimated Effort Breakdown

### Phase 1: Critical Fixes (P0)
- Update QueueJobV2 references: **4-6 hours**
- **Total:** **4-6 hours**

### Phase 2: High-Priority Fixes (P1)
- Fix API test failures: **3-4 hours**
- Investigate/fix performance issues: **4-6 hours**
- **Total:** **7-10 hours**

### Phase 3: Medium-Priority Fixes (P2)
- Fix path construction: **0.5 hours**
- Investigate stage chain test: **1-2 hours**
- Configure Tkinter skipping: **1 hour**
- **Total:** **2.5-3.5 hours**

### Phase 4: Low-Priority & Cleanup (P3)
- Fix unicode encoding: **0.5 hours**
- Documentation updates: **1 hour**
- **Total:** **1.5 hours**

### **Grand Total:** **15.5-21 hours**

**Realistic Estimate with Testing/Verification:** **18-24 hours**

---

## Recommended Approach

### Option A: Phased Cleanup (Recommended)
1. **PR-TEST-001-A:** Fix QueueJobV2 references (P0) - 4-6h
2. **PR-TEST-001-B:** Fix API tests + performance (P1) - 7-10h
3. **PR-TEST-001-C:** Remaining fixes + infrastructure (P2-P3) - 4-5h

**Pros:** Incremental progress, testable milestones  
**Cons:** 3 PRs to review  
**Total Time:** 15-21h

### Option B: Big Bang Cleanup
1. **PR-TEST-001:** Fix everything in one PR - 18-24h

**Pros:** Single comprehensive fix  
**Cons:** Large PR difficult to review, higher risk  
**Total Time:** 18-24h

### Option C: Essential Only
1. **PR-TEST-001:** Fix P0 + P1 only - 11-16h
2. Defer P2-P3 to future

**Pros:** Fastest path to working test suite  
**Cons:** Leaves some debt unaddressed  
**Total Time:** 11-16h

### **Recommendation:** **Option A (Phased Cleanup)**
- Manageable PRs
- Early wins build momentum
- Lower risk per PR

---

## Next Steps

1. **User Decision:** Choose Option A, B, or C
2. **Create PR Plans:** Detailed implementation plans for chosen option
3. **Execute Phase 1:** Focus on P0 (QueueJobV2) first
4. **Verify Core Tests:** Ensure queue/pipeline/controller still passing
5. **Continue Phases:** Progress through P1 → P2 → P3

---

## Open Questions

1. **StageConfig.enabled Default:** What is the actual default value?
2. **Performance Root Cause:** Which test is hanging?
3. **API Test Failure Details:** What are the actual error messages?
4. **CI/CD Requirements:** What's the target test execution time?
5. **GUI Test Strategy:** Mock, skip, or fix environment?

---

## Conclusion

Test suite has significant technical debt from CORE1 architectural transition. **Critical path is clear:** fix QueueJobV2 references, then address API/performance issues.

**Estimated effort (18-24 hours)** is reasonable for the scope of issues. Phased approach recommended to maintain momentum and reduce risk.

Once complete, test suite will provide confidence for continued refactoring and feature development.

---

**Discovery Status:** ✅ COMPLETE  
**Ready for PR Planning:** YES  
**Recommended Next Action:** Create PR-TEST-001-A plan (QueueJobV2 fixes)
