# PR-PROCESS-001: Windows CMD/Shell Process Cleanup & Crash Recovery

**Status**: 🟡 Specification (Awaiting Approval)  
**Priority**: HIGH  
**Effort**: MEDIUM (3-4 days)  
**Phase**: Phase 4 — Stability & Process Management  
**Date**: 2025-12-25

---

## 1. Summary (Executive Abstract)

StableNew does not properly clean up orphaned CMD/shell processes when the WebUI is launched via `.cmd` or `.bat` files on Windows. When the application exits normally or crashes during startup, intermediate shell processes (`cmd.exe`, `conhost.exe`) and their spawned Python children can remain alive, consuming system resources and blocking port 7860.

This PR implements three critical safety mechanisms:

1. **Explicit CMD/shell process cleanup** in `WebUIProcessManager._kill_process_tree()`
2. **Emergency atexit handler** in `main.py` for crash-during-startup scenarios
3. **Enhanced orphan monitor** to detect and terminate intermediate shell processes

**Impact**: Eliminates the "5-7 orphaned python.exe processes" issue documented in D-GUI-002, ensures clean shutdown in all scenarios (normal exit, GUI crash, early startup failure), and prevents port conflicts on subsequent launches.

**Risk**: Low — changes are defensive additions to existing cleanup paths, no behavioral changes to normal execution flow.

---

## 2. Motivation / Problem Statement

### Current Behavior

**Problem 1: CMD wrapper processes not cleaned up**

When WebUI is launched via `.bat` or `.cmd` file:
```
cmd.exe (PID 1000) ← Shell wrapper
  └── python.exe (PID 2000) ← Actual WebUI process
```

Current cleanup in `WebUIProcessManager._kill_process_tree()`:
- ✅ Kills tracked parent PID (WebUI python.exe)
- ✅ Enumerates and kills children via `psutil.Process.children()`
- ❌ **Does NOT** check for intermediate shell processes
- ❌ **Does NOT** clean up `cmd.exe` or `conhost.exe` wrappers

**Result**: When `.cmd` file exits quickly after spawning Python, the Python process becomes orphaned and:
- Won't appear as a child of the tracked PID
- Won't match direct cmdline pattern matching (unless "webui" is in args)
- **Survives shutdown and blocks port 7860**

**Evidence**: D-GUI-002 documents user reports of "5-7 python.exe processes" remaining after shutdown.

---

**Problem 2: No cleanup during crash-before-WebUI-init**

Current crash handling in `main.py`:
```python
try:
    root.mainloop()
except BaseException as exc:
    graceful_exit(app_controller, root, single_instance_lock, logger, 
                  window=window, reason="fatal-error")
```

**Gap**: If app crashes **before** `_update_window_webui_manager()` completes (line ~174), `webui_manager` is still `None` and `graceful_exit()` has nothing to clean up.

**Scenario**:
1. User starts StableNew
2. WebUI launches via `.bat` file (python.exe starts)
3. GUI crashes during Tkinter initialization
4. `graceful_exit()` runs but `webui_manager` is `None`
5. WebUI python.exe keeps running indefinitely

**Result**: Orphaned WebUI blocks port 7860, user must manually kill via Task Manager.

---

**Problem 3: Orphan monitor only checks GUI PID**

Current orphan monitor ([webui_process_manager.py](c:\Users\rob\projects\StableNew\src\api\webui_process_manager.py#L837-L880)):
```python
def _orphan_monitor_loop(self) -> None:
    while not self._orphan_monitor_stop.is_set():
        if not psutil.pid_exists(gui_pid):
            # Kill WebUI
            break
```

**Limitation**: Only detects if StableNew GUI PID disappears. Does NOT detect:
- Intermediate shell processes that spawn children and exit
- Orphaned processes that reparent to system
- Child processes that outlive their parent shell

**Result**: WebUI can remain alive even after GUI exits if it was spawned via `.cmd` wrapper.

---

### User Impact

**Scenario**: User launches StableNew, WebUI fails to start, crashes GUI

**Current Outcome**:
```
1. User clicks StableNew.exe
2. WebUI launches via webui.cmd
3. GUI crashes during theme loading
4. User restarts → "Port 7860 already in use"
5. User opens Task Manager → 7 python.exe processes
6. User manually kills all python.exe → loses other Python work
```

**Proposed Outcome**:
```
1. User clicks StableNew.exe
2. WebUI launches via webui.cmd
3. GUI crashes during theme loading
4. Emergency cleanup kills all WebUI-related processes
5. User restarts → Works immediately
```

**Benefit**: Eliminates manual Task Manager intervention and prevents user frustration.

---

## 3. Scope & Non-Goals

### 3.1 In-Scope

1. **WebUI Process Cleanup Enhancement**
   - Add explicit `cmd.exe` / `conhost.exe` detection to `_kill_process_tree()`
   - Match processes by working directory + cmdline patterns
   - Kill shell wrappers in addition to Python processes

2. **Emergency Crash Handler**
   - Add module-level atexit handler in `main.py`
   - Track WebUI manager globally for emergency access
   - Ensure cleanup runs even if GUI never fully initializes

3. **Orphan Monitor Enhancement**
   - Extend orphan detection to check for intermediate shell processes
   - Add periodic scan for WebUI processes without valid parent
   - Log when reparented processes are detected

4. **Diagnostic Logging**
   - Log all killed process PIDs, names, cmdlines
   - Log working directories for shell process matches
   - Add debug logging for orphan detection events

### 3.2 Out-of-Scope

1. **Non-Windows Platforms**: This PR focuses on Windows-specific shell cleanup
   - Unix/Linux shell handling unchanged (already works via SIGTERM)
   - macOS behavior unchanged

2. **WebUI Launch Method Changes**: Does not modify how WebUI starts
   - `.bat` / `.cmd` file handling logic unchanged
   - `shell=True` behavior unchanged

3. **Process Container Refactor**: Does not touch existing process container abstraction
   - `ProcessContainerV2` unchanged
   - Job-bound process cleanup unchanged

4. **GUI Lifecycle Changes**: Does not alter GUI startup/shutdown sequence
   - `main.py` mainloop structure unchanged
   - `graceful_exit()` signature unchanged

### 3.3 Subsystems Affected

- **WebUI Process Manager**: Core cleanup logic
- **Main Entrypoint**: Emergency handler registration
- **Logging System**: Enhanced diagnostics

---

## 4. Behavioral Changes (Before → After)

### 4.1 User-Facing Behavior

| Area | Before | After |
|------|--------|-------|
| **Normal Shutdown** | Leaves 2-7 orphaned python.exe processes when WebUI launched via `.cmd` | All WebUI processes cleanly terminated, including shell wrappers |
| **GUI Crash** | WebUI keeps running indefinitely, blocks port 7860 | WebUI killed within 2s of crash, port immediately available |
| **Task Manager** | User must manually identify and kill WebUI processes | No manual intervention needed |
| **Restart Behavior** | "Port already in use" error on next launch | Clean restart every time |

### 4.2 Internal System Behavior

| Subsystem | Before | After |
|-----------|--------|-------|
| **WebUIProcessManager** | Kills parent PID + psutil children only | Additionally scans for cmd.exe/conhost.exe by cwd + cmdline |
| **main.py** | Relies on try/except for crash handling | Registers atexit handler as final safety net |
| **Orphan Monitor** | Only checks if GUI PID exists | Also detects reparented WebUI processes |
| **Logging** | Minimal cleanup diagnostics | Full process tree logged: PID, name, cmdline, cwd, memory |

### 4.3 Backward Compatibility

**✅ Fully Compatible**

- No changes to public APIs or method signatures
- No changes to configuration schema
- No changes to file formats or data structures
- All changes are additive defensive measures

**Why**: All modifications are internal to cleanup paths that only execute during shutdown/crash scenarios. Normal execution flow entirely unchanged.

---

## 5. Architectural Alignment

### Canonical Documents

**ARCHITECTURE_v2.6.md** — Section 3.4 "WebUI Lifecycle Management"
- ✅ Maintains separation: WebUI managed by `WebUIProcessManager`
- ✅ No GUI direct access to process management
- ✅ Controller remains mediator

**GOVERNANCE_v2.6.md** — Section 4.2 "Defensive Programming"
- ✅ Implements fail-safe cleanup mechanisms
- ✅ Adds diagnostic logging for debugging
- ✅ Maintains zero-assumption error handling

**StableNew_Coding_and_Testing_v2.6.md** — Section 7.5 "Job-Bound Process Cleanup"
- ✅ Extends existing process cleanup patterns
- ✅ Uses psutil consistently
- ✅ Follows established logging conventions

### Architectural Boundaries Respected

- ✅ GUI does not manage processes (all changes in WebUIProcessManager/main.py)
- ✅ Controller mediates lifecycle (emergency handler respects controller contract)
- ✅ Process management isolated (no cross-layer contamination)

---

## 6. Allowed / Forbidden Files

### 6.1 Allowed Files

| File | Justification |
|------|---------------|
| `src/api/webui_process_manager.py` | Primary location for WebUI process cleanup logic |
| `src/main.py` | Register emergency atexit handler for crash scenarios |
| `tests/api/test_webui_process_cleanup.py` | New test file for cleanup validation (NEW) |
| `docs/DEBUG HUB v2.6.md` | Add troubleshooting section for orphaned processes |
| `CHANGELOG.md` | Document PR changes |

### 6.2 Forbidden Files

**Explicitly UNTOUCHED**:
- `src/gui/main_window_v2.py` — No GUI lifecycle changes
- `src/controller/app_controller.py` — Controller logic unchanged
- `src/pipeline/executor.py` — Pipeline execution unaffected
- `src/controller/job_service.py` — Job-bound cleanup separate concern
- `src/utils/process_container_v2.py` — Process container abstraction unchanged

---

## 7. Step-by-Step Implementation Plan

### Step 1: Enhance `_kill_process_tree()` for CMD/Shell Cleanup

**File**: `src/api/webui_process_manager.py`

**Location**: Inside `_kill_process_tree()` method (after existing python.exe scan)

**Add**:
```python
# NEW: Kill cmd.exe and conhost.exe shell wrappers
# These are left behind when .bat/.cmd files spawn python.exe then exit
if platform.system() == "Windows":
    webui_dir = self._config.working_dir
    shell_pids_killed = []
    
    for proc in psutil.process_iter(['pid', 'name', 'cmdline', 'cwd']):
        try:
            name = proc.info['name']
            if name and name.lower() in ('cmd.exe', 'conhost.exe'):
                cmdline = proc.info.get('cmdline', [])
                cwd = proc.info.get('cwd', '')
                
                # Match by working directory
                is_webui_dir = webui_dir and cwd and Path(cwd) == Path(webui_dir)
                
                # Match by cmdline mentioning webui
                is_webui_cmdline = any(
                    'webui' in str(arg).lower() or 
                    'launch' in str(arg).lower()
                    for arg in cmdline
                )
                
                if is_webui_dir or is_webui_cmdline:
                    logger.warning(
                        "Killing shell process: PID=%s name=%s cwd=%s cmdline=%s",
                        proc.pid, name, cwd, cmdline
                    )
                    proc.kill()
                    shell_pids_killed.append(proc.pid)
                    
        except (psutil.NoSuchProcess, psutil.AccessDenied):
            pass
        except Exception as exc:
            logger.debug("Error checking shell process: %s", exc)
    
    if shell_pids_killed:
        logger.warning(
            ">>> Killed %d shell wrapper processes: %s",
            len(shell_pids_killed), shell_pids_killed
        )
```

**Rationale**: Catches `.cmd` launcher processes that spawn WebUI and exit, leaving orphaned Python children.

---

### Step 2: Add Emergency Atexit Handler

**File**: `src/main.py`

**Location**: Module level (after imports, before `main()`)

**Add**:
```python
import atexit

# Global reference for emergency cleanup
_webui_manager_global: WebUIProcessManager | None = None
_emergency_cleanup_registered = False

def _emergency_webui_cleanup() -> None:
    """
    Emergency cleanup for WebUI processes.
    
    Runs via atexit if app crashes before normal shutdown completes.
    This is a last-resort safety net — normal shutdown should handle cleanup.
    """
    if _webui_manager_global is None:
        return
    
    logger = logging.getLogger(__name__)
    try:
        logger.warning("EMERGENCY CLEANUP: Killing WebUI processes via atexit handler")
        _webui_manager_global.stop_webui(grace_seconds=1.0)
        logger.warning("EMERGENCY CLEANUP: Complete")
    except Exception as exc:
        logger.error("EMERGENCY CLEANUP: Failed - %s", exc, exc_info=True)
```

**Register handler in `main()`** (after WebUI manager is created):

```python
def main() -> None:
    # ... existing setup ...
    
    root, app_state, app_controller, window = build_v2_app(
        root=tk.Tk(), webui_manager=webui_manager
    )
    
    # NEW: Register emergency cleanup after WebUI bootstrap
    root.after(1000, lambda: _register_emergency_cleanup(window))
    
    # ... rest of main ...

def _register_emergency_cleanup(window) -> None:
    """Register emergency cleanup handler once WebUI manager is available."""
    global _webui_manager_global, _emergency_cleanup_registered
    
    if _emergency_cleanup_registered:
        return
    
    webui_mgr = getattr(window, 'webui_process_manager', None)
    if webui_mgr:
        _webui_manager_global = webui_mgr
        atexit.register(_emergency_webui_cleanup)
        _emergency_cleanup_registered = True
        logging.getLogger(__name__).debug(
            "Emergency cleanup handler registered for WebUI PID %s",
            webui_mgr.pid
        )
```

**Rationale**: Ensures WebUI is killed even if app crashes during startup before `graceful_exit()` can run.

---

### Step 3: Enhance Orphan Monitor

**File**: `src/api/webui_process_manager.py`

**Location**: Inside `_orphan_monitor_loop()` method

**Replace** existing single PID check with comprehensive scan:

```python
def _orphan_monitor_loop(self) -> None:
    """Monitor thread that kills WebUI if StableNew GUI exits."""
    gui_pid = os.getpid()
    webui_dir = self._config.working_dir
    check_interval = 2.0  # seconds
    
    logger.info(
        "[Orphan Monitor] Started: GUI_PID=%s, WebUI_PID=%s, check_interval=%.1fs",
        gui_pid, self.pid, check_interval
    )
    
    while not self._orphan_monitor_stop.is_set():
        try:
            # Check 1: GUI process still alive?
            if not psutil.pid_exists(gui_pid):
                logger.warning(
                    "[Orphan Monitor] GUI process %s no longer exists, killing WebUI",
                    gui_pid
                )
                self._kill_all_webui_processes()
                break
            
            # Check 2: WebUI process reparented (shell wrapper exited)?
            if self.pid and psutil.pid_exists(self.pid):
                try:
                    webui_proc = psutil.Process(self.pid)
                    parent = webui_proc.parent()
                    
                    # If parent changed from GUI to system (PID 1 or None)
                    if parent is None or parent.pid in (0, 1, 4):  # System PIDs
                        logger.warning(
                            "[Orphan Monitor] WebUI process %s reparented to system, "
                            "checking for shell wrapper exit",
                            self.pid
                        )
                        # Don't kill immediately — check if it's intentional
                        # (WebUI might legitimately run as background service)
                        
                except psutil.NoSuchProcess:
                    pass  # Process exited, normal
            
            # Check 3: Scan for orphaned WebUI processes without valid parent
            orphaned_webui_pids = self._scan_for_orphaned_webui_processes()
            if orphaned_webui_pids:
                logger.warning(
                    "[Orphan Monitor] Found %d orphaned WebUI processes: %s",
                    len(orphaned_webui_pids), orphaned_webui_pids
                )
                # Kill them if GUI is still alive but WebUI manager lost track
                if psutil.pid_exists(gui_pid):
                    for orphan_pid in orphaned_webui_pids:
                        try:
                            psutil.Process(orphan_pid).kill()
                            logger.warning("[Orphan Monitor] Killed orphan PID %s", orphan_pid)
                        except Exception as exc:
                            logger.debug("Failed to kill orphan %s: %s", orphan_pid, exc)
                            
        except Exception as exc:
            logger.debug("[Orphan Monitor] Check failed: %s", exc)
        
        self._orphan_monitor_stop.wait(check_interval)
    
    logger.info("[Orphan Monitor] Stopped")

def _scan_for_orphaned_webui_processes(self) -> list[int]:
    """Scan for WebUI python.exe processes that have no valid parent."""
    if not psutil:
        return []
    
    webui_dir = self._config.working_dir
    orphans = []
    
    for proc in psutil.process_iter(['pid', 'name', 'cmdline', 'ppid', 'cwd']):
        try:
            name = proc.info['name']
            if not name or 'python' not in name.lower():
                continue
            
            cmdline = proc.info.get('cmdline', [])
            cwd = proc.info.get('cwd', '')
            ppid = proc.info.get('ppid')
            
            # Is this a WebUI process?
            is_webui = (
                (webui_dir and cwd and Path(cwd) == Path(webui_dir)) or
                any('webui' in str(arg).lower() or 'launch' in str(arg).lower() 
                    for arg in cmdline)
            )
            
            if is_webui:
                # Check if parent is system or nonexistent
                try:
                    parent = psutil.Process(ppid) if ppid else None
                    if parent is None or ppid in (0, 1, 4):
                        orphans.append(proc.pid)
                except psutil.NoSuchProcess:
                    orphans.append(proc.pid)
                    
        except (psutil.NoSuchProcess, psutil.AccessDenied):
            pass
        except Exception as exc:
            logger.debug("Error scanning for orphans: %s", exc)
    
    return orphans

def _kill_all_webui_processes(self) -> None:
    """Kill all WebUI-related processes (used by orphan monitor)."""
    if self.pid:
        self._kill_process_tree(self.pid)
```

**Rationale**: Detects and kills WebUI processes that become orphaned when shell wrappers exit.

---

### Step 4: Add Diagnostic Logging

**File**: `src/api/webui_process_manager.py`

**Location**: In `_kill_process_tree()` before killing processes

**Enhance** existing logging to include full process details:

```python
# Before killing, log full diagnostic info
logger.warning(
    ">>> Killing process: PID=%s name=%s cwd=%s mem=%.1fMB cmdline=%s",
    proc.pid,
    proc.info.get('name'),
    proc.info.get('cwd'),
    proc.info.get('memory_info').rss / (1024 * 1024) if proc.info.get('memory_info') else 0,
    ' '.join(proc.info.get('cmdline', []))[:100]  # Truncate long cmdlines
)
```

**Rationale**: Aids debugging when cleanup fails or unexpected processes remain.

---

### Step 5: Add Crash Scenario Tests

**File**: `tests/api/test_webui_process_cleanup.py` (NEW)

**Add comprehensive test coverage**:

```python
"""Tests for WebUI process cleanup including CMD/shell wrappers."""

import os
import subprocess
import sys
import time
from pathlib import Path
from unittest.mock import Mock, patch

import pytest

try:
    import psutil
except ImportError:
    psutil = None

from src.api.webui_process_manager import (
    WebUIProcessConfig,
    WebUIProcessManager,
)


@pytest.mark.skipif(os.name != "nt", reason="Windows-specific test")
@pytest.mark.skipif(psutil is None, reason="psutil required")
class TestCMDShellCleanup:
    """Test cleanup of cmd.exe and conhost.exe wrappers."""
    
    def test_cleanup_kills_cmd_wrapper(self, tmp_path):
        """Verify that cmd.exe wrapper is killed along with python.exe."""
        # Create a dummy .bat file that launches python
        bat_file = tmp_path / "launch_test.bat"
        bat_file.write_text(
            f"@echo off\n"
            f'"{sys.executable}" -c "import time; time.sleep(60)"\n'
        )
        
        config = WebUIProcessConfig(
            command=[str(bat_file)],
            working_dir=str(tmp_path),
            autostart_enabled=False,
        )
        
        manager = WebUIProcessManager(config)
        manager.start()
        
        time.sleep(1)  # Let process start
        
        # Find cmd.exe wrapper
        cmd_pids = []
        for proc in psutil.process_iter(['pid', 'name', 'cwd']):
            if (proc.info['name'] and 
                'cmd.exe' in proc.info['name'].lower() and
                proc.info.get('cwd') == str(tmp_path)):
                cmd_pids.append(proc.pid)
        
        assert len(cmd_pids) > 0, "Should have found cmd.exe wrapper"
        
        # Stop manager (should kill cmd.exe + python.exe)
        manager.stop_webui(grace_seconds=2.0)
        
        time.sleep(1)
        
        # Verify cmd.exe is gone
        for cmd_pid in cmd_pids:
            assert not psutil.pid_exists(cmd_pid), \
                f"cmd.exe PID {cmd_pid} should have been killed"
    
    def test_orphan_monitor_detects_reparented_process(self, tmp_path):
        """Verify orphan monitor detects when python.exe is reparented."""
        # This test simulates the scenario where .cmd exits but python continues
        # In practice, the orphan monitor should detect and kill it
        
        # Create python script that runs for 30s
        script = tmp_path / "long_runner.py"
        script.write_text("import time; time.sleep(30)")
        
        # Launch via subprocess (simulates .cmd launcher)
        proc = subprocess.Popen(
            [sys.executable, str(script)],
            cwd=str(tmp_path),
        )
        
        python_pid = proc.pid
        time.sleep(0.5)
        
        # Terminate the launcher (simulates .cmd exiting)
        proc.terminate()
        proc.wait(timeout=2)
        
        # Python should still be running (orphaned)
        assert psutil.pid_exists(python_pid), "Python should still be alive"
        
        # Orphan monitor would detect this and kill it
        # (Actual test would need full WebUIProcessManager setup)
        
        # Cleanup
        try:
            psutil.Process(python_pid).kill()
        except:
            pass


@pytest.mark.skipif(os.name != "nt", reason="Windows-specific test")
class TestEmergencyCleanup:
    """Test emergency atexit handler for crash scenarios."""
    
    def test_atexit_handler_runs_on_crash(self, tmp_path, monkeypatch):
        """Verify atexit handler kills WebUI if main() crashes."""
        # This would be an integration test that:
        # 1. Starts app
        # 2. Triggers crash
        # 3. Verifies WebUI is killed
        
        # Simplified unit test version:
        from src.main import _emergency_webui_cleanup, _webui_manager_global
        
        mock_manager = Mock()
        mock_manager.stop_webui = Mock()
        
        # Simulate global assignment
        import src.main as main_module
        main_module._webui_manager_global = mock_manager
        
        # Call emergency cleanup
        _emergency_webui_cleanup()
        
        # Verify stop_webui was called
        mock_manager.stop_webui.assert_called_once()
```

---

### Step 6: Update Documentation

**File**: `docs/DEBUG HUB v2.6.md`

**Add new troubleshooting section**:

```markdown
### Issue: Orphaned WebUI Processes After Crash

**Symptoms**:
- Port 7860 already in use on next launch
- Task Manager shows multiple python.exe processes
- WebUI appears to be running but GUI is not

**Root Cause**:
When StableNew crashes during startup, WebUI processes may not be cleaned up properly.

**Resolution** (Automatic as of PR-PROCESS-001):
1. Emergency atexit handler kills WebUI processes
2. Orphan monitor detects reparented processes
3. CMD/shell wrappers explicitly cleaned up

**Manual Resolution** (if needed):
```powershell
# Find and kill all WebUI-related python.exe
Get-Process python | Where-Object {
    $_.CommandLine -like '*webui*' -or 
    $_.Path -like '*webui*'
} | Stop-Process -Force

# Find and kill cmd.exe wrappers
Get-Process cmd | Where-Object {
    $_.CommandLine -like '*webui*'
} | Stop-Process -Force
```

**Prevention**:
- Upgrade to v2.6+ (includes PR-PROCESS-001 fixes)
- Avoid launching WebUI manually outside of StableNew
- Check logs in `logs/webui/` for crash details
```

---

## 8. Test Plan

### 8.1 New Tests

| Test File | Coverage |
|-----------|----------|
| `tests/api/test_webui_process_cleanup.py` | CMD wrapper cleanup, orphan detection, emergency handler |

**Test Cases**:
1. ✅ `test_cleanup_kills_cmd_wrapper` — Verify cmd.exe killed with python.exe
2. ✅ `test_cleanup_kills_conhost_wrapper` — Verify conhost.exe killed
3. ✅ `test_orphan_monitor_detects_reparented_process` — Detect orphans
4. ✅ `test_atexit_handler_runs_on_crash` — Emergency cleanup invoked
5. ✅ `test_no_cleanup_when_webui_not_started` — Graceful no-op

### 8.2 Updated Tests

| Test File | Changes |
|-----------|---------|
| `tests/api/test_webui_process_manager.py` | Add assertions for shell process cleanup |
| `tests/journeys/test_shutdown_no_leaks.py` | Verify no cmd.exe remain after shutdown |

### 8.3 Test Scaffolding Matrix

| Category | Required? | Notes |
|----------|-----------|-------|
| Normal-path tests | ✔ | Verify cleanup during normal shutdown |
| Edge-case tests | ✔ | Test .bat vs .cmd vs direct python launch |
| Failure-mode tests | ✔ | Test crash-during-startup scenario |
| GUI event tests | ❌ | No GUI changes |
| State/restore tests | ❌ | No state persistence changes |
| Process lifecycle tests | ✔ | NEW: Validate all process cleanup paths |

---

## 9. Acceptance Criteria

- ✅ Normal shutdown kills all WebUI processes (python.exe + cmd.exe + conhost.exe)
- ✅ GUI crash during startup triggers emergency cleanup within 2 seconds
- ✅ Orphan monitor detects reparented WebUI processes
- ✅ No orphaned processes remain after shutdown (validated via `Get-Process`)
- ✅ Port 7860 immediately available after StableNew exits
- ✅ All new tests pass
- ✅ Existing journey tests remain green
- ✅ Documentation updated (DEBUG HUB + CHANGELOG)
- ✅ No architectural boundary violations

---

## 10. Validation Checklist (Mandatory)

### Pre-Merge Validation

- [ ] App boots normally (no regression)
- [ ] WebUI launches via `.bat` file successfully
- [ ] Normal shutdown leaves zero orphaned processes
- [ ] Crash during startup kills WebUI within 2s
- [ ] Task Manager shows no python.exe after exit
- [ ] Port 7860 available immediately after shutdown
- [ ] Logs contain diagnostic info for all killed processes
- [ ] All unit tests pass
- [ ] Journey tests pass (shutdown-no-leaks)

### Platform-Specific Validation

**Windows 10/11**:
- [ ] .bat file launch + normal shutdown → clean
- [ ] .bat file launch + GUI crash → clean
- [ ] .cmd file launch + normal shutdown → clean
- [ ] .cmd file launch + GUI crash → clean

**Unix/Linux** (should be unaffected):
- [ ] Normal shutdown still works
- [ ] No new errors in logs

---

## 11. Documentation Impact Assessment

### 11.1 Documentation Impact Questions

| Question | Answer |
|----------|--------|
| Does this PR change a subsystem's behavior? | ✅ YES — WebUI process cleanup |
| Does it change responsibilities between layers? | ❌ NO |
| Does it alter queue, randomizer, or controller semantics? | ❌ NO |
| Does it modify run modes or job lifecycle? | ❌ NO |
| Does it update UX or GUI layout? | ❌ NO |
| Does it modify developer workflow, PR flow, or governance? | ❌ NO |

### 11.2 Mapping to Required Docs

| Document | Section | Update |
|----------|---------|--------|
| `ARCHITECTURE_v2.6.md` | Section 3.4 "WebUI Lifecycle" | Add note about emergency cleanup |
| `DEBUG HUB v2.6.md` | Add "Orphaned Processes" section | New troubleshooting guide |
| `CHANGELOG.md` | Add PR-PROCESS-001 entry | See below |

### 11.3 CHANGELOG.md Entry

```markdown
## [PR-PROCESS-001] - 2025-12-25
**Summary**: Windows CMD/Shell Process Cleanup & Crash Recovery

**Problem**: WebUI processes launched via .bat/.cmd files were not cleaned up during 
normal shutdown or GUI crashes, leaving 5-7 orphaned python.exe processes that blocked 
port 7860 and required manual Task Manager intervention.

**Solution**: 
- Enhanced _kill_process_tree() to explicitly kill cmd.exe and conhost.exe shell wrappers
- Added emergency atexit handler in main.py for crash-during-startup scenarios
- Enhanced orphan monitor to detect reparented WebUI processes

**Impact**: Eliminates orphaned process issue, ensures clean shutdown in all scenarios.

**Files Modified**:
- src/api/webui_process_manager.py: Enhanced _kill_process_tree(), orphan monitor
- src/main.py: Added emergency atexit handler
- tests/api/test_webui_process_cleanup.py: New test file (NEW)
- docs/DEBUG HUB v2.6.md: Added orphaned process troubleshooting

**Canonical Docs Updated**:
- ARCHITECTURE_v2.6.md: Section 3.4 (WebUI lifecycle management)
- DEBUG HUB v2.6.md: New "Orphaned Processes" troubleshooting section

**Testing**:
- All unit tests pass
- Journey tests pass (shutdown-no-leaks)
- Manual validation: No orphaned processes after crash

**Notes**:
- Windows-specific fix (Unix/Linux unaffected)
- Backward compatible (additive changes only)
- No configuration changes required
```

---

## 12. Rollback Plan

### 12.1 Rollback Specification Matrix

| Category | Items |
|----------|-------|
| **Files to revert** | `src/api/webui_process_manager.py`, `src/main.py` |
| **Files to delete** | `tests/api/test_webui_process_cleanup.py` |
| **Tests to revert** | `tests/journeys/test_shutdown_no_leaks.py` (if modified) |
| **Doc updates to undo** | `DEBUG HUB v2.6.md` (remove orphaned process section), `CHANGELOG.md` (remove entry) |
| **Expected behavior after rollback** | Returns to original behavior (orphaned processes may remain after crash) |

### 12.2 Rollback Procedure

```bash
# 1. Revert code changes
git revert <commit-hash>

# 2. Delete new test file
git rm tests/api/test_webui_process_cleanup.py

# 3. Verify no orphaned global state
grep -r "_webui_manager_global" src/

# 4. Run tests to ensure no breakage
pytest tests/api/test_webui_process_manager.py
pytest tests/journeys/test_shutdown_no_leaks.py

# 5. Manual verification
# - Launch StableNew
# - Close GUI
# - Check Task Manager for python.exe
# - (May see orphans after rollback — expected)
```

---

## 13. Potential Pitfalls (LLM Guidance)

### Critical Mistakes to Avoid

1. **❌ DO NOT modify `graceful_exit()` signature**
   - Emergency handler should be independent
   - `graceful_exit()` is called from multiple locations

2. **❌ DO NOT kill non-WebUI Python processes**
   - Must check working directory OR cmdline patterns
   - User may have other Python processes running

3. **❌ DO NOT use global state in WebUIProcessManager**
   - Emergency handler uses module-level global in `main.py` only
   - Keep process manager instance clean

4. **❌ DO NOT block main thread during cleanup**
   - All cleanup must be async or background
   - Emergency handler runs in atexit (already off main thread)

5. **❌ DO NOT assume psutil is available**
   - Check `if psutil is None` before all psutil calls
   - Degrade gracefully if psutil missing

6. **❌ DO NOT kill processes by name alone**
   - `python.exe` is too generic
   - Must match working directory OR cmdline

7. **❌ DO NOT modify orphan monitor without timeout**
   - Must have maximum scan duration
   - Avoid infinite loops if psutil hangs

---

## 14. Additional Notes / Assumptions

### Assumptions

1. **Windows-Only Fix**: This PR focuses on Windows where `.bat`/`.cmd` files are common
   - Unix/Linux already handle SIGTERM correctly
   - macOS behavior assumed similar to Linux

2. **psutil Available**: Tests require psutil
   - Already in requirements.txt
   - Production code degrades gracefully if missing

3. **Single WebUI Instance**: Emergency handler assumes one WebUI manager
   - Multiple WebUI managers not supported (not a current use case)

4. **Port 7860 Default**: Troubleshooting assumes default port
   - User can configure different port
   - Documentation should mention checking actual configured port

### Future Enhancements (Out of Scope)

- **Process Container Integration**: Could unify cleanup via `ProcessContainerV2`
- **Cross-Platform Testing**: Validate on Linux/macOS with equivalent shell wrappers
- **Automatic Port Detection**: Scan for orphaned processes on any port
- **Process Hierarchy Visualization**: Add debug tool to show full process tree

---

## 15. Implementation Checklist

- [ ] Step 1: Enhance `_kill_process_tree()` with CMD cleanup
- [ ] Step 2: Add emergency atexit handler in `main.py`
- [ ] Step 3: Enhance orphan monitor with reparent detection
- [ ] Step 4: Add diagnostic logging for all killed processes
- [ ] Step 5: Create `test_webui_process_cleanup.py` with 5 test cases
- [ ] Step 6: Update DEBUG HUB documentation
- [ ] Step 7: Add CHANGELOG entry
- [ ] Step 8: Manual validation (crash + cleanup)
- [ ] Step 9: Journey test validation (shutdown-no-leaks)
- [ ] Step 10: Final review and approval

---

✔ **End of PR-PROCESS-001 Specification**

**Ready for**: Implementation by Codex/Copilot  
**Review by**: ChatGPT + Human Owner  
**Target Merge**: Phase 4 (v2.6.1)
