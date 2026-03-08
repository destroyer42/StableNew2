# PR-CORE1-D11E Implementation Complete

**Date:** 2025-12-15  
**Status:** READY FOR REVIEW  
**Branch:** `pr-core1-d11e-autoscanner-webui-protect`

---

## Summary

Successfully hardened `ProcessAutoScannerService` to prevent StableNew from silently killing WebUI during startup.

### Root Cause
StableNew was terminating the WebUI Python process in the background because:
1. The process auto-scanner targeted **any Python process** (including WebUI)
2. It killed processes when "idle" (actually process age) exceeded 120 seconds **OR** memory exceeded 1GB
3. WebUI runs as Python, often exceeds 1GB RSS after model load, and is started **outside the StableNew repo directory**
4. The scanner had **no protection for WebUI PID** until after the first job starts

Result: WebUI page loads successfully → dropdowns populate → ~2-13 seconds later → scanner terminates WebUI → "silent disconnect"

---

## Changes Implemented

### 1. Repo-Scoping Filter (ProcessAutoScannerService)
**File:** `src/controller/process_auto_scanner_service.py`

**Change:** Added early filter to only scan processes inside `REPO_ROOT`.

```python
# REPO-SCOPING: Only scan processes inside REPO_ROOT
# This prevents killing external processes like WebUI that happen to be Python
if not self._is_repo_process(proc):
    continue
```

**Effect:** WebUI at `C:\Users\rob\stable-diffusion-webui` (outside repo) is now **never eligible** for termination, regardless of age or memory.

---

### 2. WebUI PID Protection (AppController)
**File:** `src/controller/app_controller.py`

**Change:** Updated `_get_protected_process_pids()` to always include WebUI PID.

```python
def _get_protected_process_pids(self) -> Iterable[int]:
    pids: set[int] = set()
    
    # Always protect WebUI PID (if running)
    # This is critical to prevent ProcessAutoScannerService from killing WebUI
    # even if protected_pids callback logic changes in the future
    if hasattr(self, "webui_process_manager") and self.webui_process_manager:
        webui_pid = getattr(self.webui_process_manager, "pid", None)
        if webui_pid and isinstance(webui_pid, int):
            pids.add(webui_pid)
    
    # Protect PIDs from running jobs
    if self.job_service:
        # ... existing job PID protection ...
```

**Effect:** WebUI PID is protected from moment of startup, before first job runs (belt + suspenders).

---

### 3. Comprehensive Kill Logging
**File:** `src/controller/process_auto_scanner_service.py`

**Change:** Enhanced logging before process termination with full context.

```python
logger.warning(
    "AUTO_SCANNER_TERMINATE: pid=%s name=%s cwd=%s memory_mb=%.1f idle_sec=%.1f "
    "idle_threshold=%s memory_threshold=%s protected_count=%d cmdline=%s",
    pid, name, cwd_str, rss, idle,
    self._config.idle_threshold_sec,
    self._config.memory_threshold_mb,
    len(protected),
    cmdline_str,
)
```

**Effect:** Any future kills are immediately diagnosable (proves it was intentional repo cleanup, not WebUI).

---

### 4. Comprehensive Test Suite
**File:** `tests/controller/test_process_auto_scanner_service.py`

**7 tests added:**

#### Test A: Non-repo Python process is ignored
- Simulates WebUI at `C:\...\stable-diffusion-webui`
- Sets age=300s, memory=2000MB (exceeds both thresholds)
- Verifies: **NOT terminated** (repo-scoping catches it)

#### Test B: Repo Python process can be terminated when thresholds exceeded
- Simulates stray job inside `REPO_ROOT/tmp`
- Sets age=300s, memory=2000MB
- Verifies: **IS terminated** (scanner still works for intended repo cleanup)

#### Test C: Protected PID is never terminated
- Protects a repo process that meets thresholds
- Verifies: **NOT terminated** (protection works)

#### Test D: Kill logging includes full context
- Verifies warning log includes pid, cwd, memory, cmdline
- Captures and asserts log message content

#### Test E: Processes below thresholds not terminated
- Age=30s, memory=100MB (below both thresholds)
- Verifies: **NOT terminated** (thresholds still respected)

#### Test F & G: Edge cases
- Scanner disabled
- psutil unavailable

---

## Test Results

```
tests/controller/test_process_auto_scanner_service.py::TestProcessAutoScannerRepoScoping::test_non_repo_python_process_is_ignored PASSED
tests/controller/test_process_auto_scanner_service.py::TestProcessAutoScannerRepoScoping::test_repo_python_process_can_be_terminated_when_thresholds_exceeded PASSED
tests/controller/test_process_auto_scanner_service.py::TestProcessAutoScannerRepoScoping::test_protected_pid_is_never_terminated PASSED
tests/controller/test_process_auto_scanner_service.py::TestProcessAutoScannerRepoScoping::test_kill_logging_includes_full_context PASSED
tests/controller/test_process_auto_scanner_service.py::TestProcessAutoScannerRepoScoping::test_processes_below_thresholds_are_not_terminated PASSED
tests/controller/test_process_auto_scanner_service.py::TestProcessAutoScannerEdgeCases::test_scanner_handles_psutil_not_available PASSED
tests/controller/test_process_auto_scanner_service.py::TestProcessAutoScannerEdgeCases::test_scanner_disabled_does_not_scan PASSED

7 passed in 0.16s
```

**All existing controller tests:** Pass (no regressions)

---

## Scope Compliance

### ✅ In-Scope Changes
- `src/controller/process_auto_scanner_service.py` (repo-scoping + logging)
- `src/controller/app_controller.py` (WebUI PID protection)
- `tests/controller/test_process_auto_scanner_service.py` (new tests)

### ✅ Out-of-Scope (Not touched)
- Pipeline runner, executor, job models, DTOs
- SafeMode behavior
- WebUI installation/config
- Queue runner, NJR schema
- Any runner/builder/resolver internals

---

## Expected Behavior After D11E

1. **WebUI stays alive:** After StableNew startup, WebUI remains running indefinitely
2. **Background cleanup still works:** Stray Python processes inside `REPO_ROOT` are still eligible for termination
3. **Clear diagnostics:** If anything is killed, logs clearly show `AUTO_SCANNER_TERMINATE` with full context
4. **No more silent disconnects:** WebUI does not disappear on user, discoverable only at job time

---

## Manual Proof (Reproduction)

### Step 1: Verify WebUI stays alive
```bash
# Start StableNew normally
# Wait 60+ seconds (no user action)
# In separate terminal, check WebUI is still listening:
curl -sS http://127.0.0.1:7860/sdapi/v1/sd-models >NUL && echo WEBUI_OK
```

### Step 2: Verify generation still works
```bash
# In WebUI local page (http://127.0.0.1:7860)
# Run txt2img (e.g., 512x512, 10 steps)
# Should not disconnect mid-generation
```

### Step 3: Verify logs
```bash
# Search stablenew.log.jsonl or console output
# Should NOT contain:
#   "AUTO_SCANNER_TERMINATE: pid=<webui_pid>"
#
# If WebUI pid was ever mentioned in kill logs, something went wrong
```

---

## Risk Assessment

### Mitigation (Low Risk)
- Changes are **highly localized** to scanner behavior
- Repo-scoping is **more restrictive** (safer)
- WebUI PID protection is **additive** (always on)
- Tests cover all acceptance criteria

### Rollback (Simple)
- Revert this commit
- No schema changes, no migrations needed
- Self-contained to scanner module

---

## Deliverables Checklist

- [x] Step 1: Repo-scoping filter added to scanner
- [x] Step 2: WebUI PID protection added to app_controller
- [x] Step 3: Comprehensive kill logging added
- [x] Step 4: Test suite created (7 tests, all passing)
- [x] Regressions: 0 (all existing tests pass)
- [x] Scope: Tight (only scanner + tests touched)
- [x] Non-Goals: Respected (no pipeline/runner changes)

---

## Conclusion

**PR-CORE1-D11E stops StableNew from silently killing WebUI** by restricting the process auto-scanner to only target processes inside the StableNew repository directory and by explicitly protecting the WebUI PID from startup. The fix is minimal, well-tested, and immediately diagnosable if anything goes wrong in the future.

**Status: Ready to merge.**
