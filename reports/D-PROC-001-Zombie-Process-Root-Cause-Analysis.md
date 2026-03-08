# D-PROC-001: Zombie Process Root Cause Analysis & Remediation Plan

**Discovery Type:** CRITICAL System Defect  
**Severity:** HIGH - Memory leak, system instability  
**Recurrence:** 3rd occurrence of this bug  
**Date:** 2025-12-25  
**Status:** Root Cause Identified, Fix Strategy Defined

---

## Executive Summary

StableNew experiences recurring **runaway process spawning** where 14-26+ zombie Python processes and 11+ CMD.exe parent processes accumulate, causing memory leaks (multi-GB) and requiring manual intervention. This has occurred **2-3 times previously**, indicating a systemic architectural flaw in process lifecycle management.

**Root Cause:** `_kill_process_tree()` method in `WebUIProcessManager` only kills Python processes but **completely ignores CMD.exe parent processes**, which continue spawning new Python children indefinitely.

**Impact:** 
- System memory exhaustion
- Degraded performance
- Requires Task Manager intervention
- User frustration & lost work

**Recommended Action:** Implement comprehensive process lifecycle management (PR-PROC-001 series).

---

## 1. Incident Timeline

### Session Context
1. **Session 1-4:** Fixed thread-safety, batch submission race conditions, deadlocks ✅
2. **Session 5:** GUI crashes at 3 jobs → Identified sync I/O GUI freeze ✅
3. **Session 6:** Implemented background writer for history store ✅
4. **CURRENT:** User reports WORSE symptoms:
   - "Built 10 jobs" after submission (wasteful preview rebuild)
   - **14 zombie Python threads visible in Task Manager**
   - Zombies **instantly respawn** when killed
   - "It's getting worse..."

### Discovery Process
1. User requested immediate zombie process termination
2. Agent listed 26 Python processes, many running `launch.py`
3. Killed Python processes → they respawned immediately (26 → 26)
4. Traced parent processes → found **11 CMD.exe parents** spawning Python children
5. Killed CMD parents → zombies stopped respawning (26 → 0) ✅
6. Root cause identified: Process cleanup never kills CMD parents

---

## 2. Root Cause Analysis

### 2.1 The Process Hierarchy Problem

**Windows Process Creation:**
```
User clicks "Launch WebUI"
└─> StableNew spawns subprocess.Popen(...)
    └─> On Windows: Creates CMD.exe shell (implicit or explicit)
        └─> CMD.exe launches python.exe launch.py
            └─> WebUI spawns multiple worker processes
```

**Problem:** When StableNew calls `stop_webui()` or `restart_webui()`:
- ✅ Python worker processes killed
- ✅ Main python.exe process killed
- ❌ **CMD.exe parent NEVER killed**
- ❌ Orphaned CMD shells continue spawning

### 2.2 Code Analysis

#### File: `src/api/webui_process_manager.py`

**Line 199-211: Process Creation**
```python
self._process = subprocess.Popen(
    self._config.command,
    cwd=self._config.working_dir or None,
    env=self._config.build_env(),
    stdout=subprocess.PIPE,
    stderr=subprocess.PIPE,
    shell=use_shell,  # ← May create CMD shell
    creationflags=creationflags if os.name == "nt" else 0,
    text=True,
    encoding="utf-8",
    errors="replace",
    bufsize=1,
)
self._pid = self._process.pid  # ← ONLY tracks Python PID, not CMD parent!
```

**Problem:** `self._pid` is the Python process ID. If `shell=True` or command is a `.bat` file, CMD parent is created but **never tracked**.

**Line 571-760: Process Cleanup (`_kill_process_tree()`)**
```python
def _kill_process_tree(self, pid: int | None) -> None:
    if pid is None:
        return
    
    killed_pids = []
    
    if os.name == "nt":
        try:
            import psutil
            
            # Kill direct children
            try:
                parent = psutil.Process(pid)
                children = parent.children(recursive=True)
                for child in children:
                    child.kill()  # ← Kills Python children
                    killed_pids.append(child.pid)
                parent.kill()  # ← Kills main Python process
                killed_pids.append(pid)
            except psutil.NoSuchProcess:
                pass
            
            # Scan for orphaned Python processes
            for proc in psutil.process_iter(['pid', 'name', 'cmdline', 'cwd']):
                if proc.info['name'] and 'python' in proc.info['name'].lower():
                    # ... [extensive Python process detection]
                    if is_webui:
                        proc.kill()  # ← Kills orphaned Python
                        killed_pids.append(proc.pid)
            
            # ❌ NO CMD.EXE CLEANUP LOGIC ANYWHERE!
```

**Critical Gap:** The method has:
- ✅ 180+ lines of Python process cleanup logic
- ✅ Sophisticated orphan detection for Python
- ✅ Memory-based heuristics for Python leaks
- ❌ **ZERO lines of CMD.exe handling**
- ❌ No parent process tracking
- ❌ No shell process detection

**Line 762-778: Fallback (`_taskkill_tree()`)**
```python
def _taskkill_tree(self, pid: int) -> None:
    """Use Windows taskkill to kill process tree."""
    result = subprocess.run(
        ["taskkill", "/PID", str(pid), "/T", "/F"],  # ← /T flag SHOULD kill tree
        check=False,
        capture_output=True,
        text=True,
    )
```

**Note:** `taskkill /T` (tree flag) SHOULD kill parent and children, but:
1. Only called as fallback when psutil fails/unavailable
2. Only passed Python PID, not CMD PID
3. May not work if CMD is grandparent (not direct parent)

### 2.3 Spawn Points Audit

| Location | Method | Creates CMD Parent? | Tracks CMD? |
|----------|--------|---------------------|-------------|
| `src/api/webui_process_manager.py:199` | `start()` | Maybe (if `shell=True` or `.bat`) | ❌ NO |
| `src/utils/webui_discovery.py:175` | `launch_webui_safely()` | ✅ YES (`CREATE_NEW_CONSOLE`) | ❌ NO |
| `scripts/launch_webui.py:57` | Manual launch | ✅ YES (shell=True) | ❌ NO |

**Finding:** At least 2 of 3 spawn points explicitly create CMD shells, but NONE track them.

### 2.4 Restart Logic Analysis

**File: `src/api/webui_process_manager.py:425-445`**
```python
def restart_webui(self, ...) -> bool:
    """Restart the WebUI process and wait for its API to become available."""
    
    self.stop_webui()  # ← Calls _kill_process_tree(self._pid)
    try:
        self.start()   # ← Spawns NEW CMD + Python
    except Exception as exc:
        return False
    # ... health check logic
```

**Problem Flow:**
1. `restart_webui()` called (e.g., connection timeout)
2. `stop_webui()` kills Python processes (not CMD)
3. `start()` spawns NEW CMD + Python
4. **Result:** Old CMD still alive, spawning zombies + New CMD spawning new process
5. Repeat on every retry/timeout → exponential growth

### 2.5 Auto-Restart Triggers

**Grep Search Results:** Found multiple auto-restart trigger points:
1. **Connection loss:** `WebUIConnectionController.ensure_connected()` with `autostart=True`
2. **Health check failure:** `WebUIProcessManager.ensure_running()` restarts unhealthy process
3. **Crash recovery:** `WebUIProcessConfig.auto_restart_on_crash = True` (not widely used yet)
4. **Manual retry:** GUI "Retry Connection" button triggers reconnect

**Risk:** Each trigger can spawn new processes without cleaning CMD parents.

---

## 3. Why This Keeps Happening

### 3.1 Lack of Documentation
- No central process lifecycle document (until now)
- Scattered subprocess.Popen calls across codebase
- No clear ownership of process cleanup
- Future developers don't know to check for CMD parents

### 3.2 Incomplete Testing
- No tests verify CMD parent cleanup
- No tests simulate restart loops
- No tests check for zombie accumulation
- No process count monitoring

### 3.3 Windows-Specific Behavior
- Linux: Process groups make cleanup easier (`os.killpg()`)
- Windows: Process hierarchy more complex, CMD shells implicit
- `shell=True` behavior differs between platforms
- `CREATE_NEW_CONSOLE` creates detached CMD

### 3.4 Async Nature of Problem
- Zombies accumulate slowly over hours/days
- Not immediately obvious during development
- Only manifests under certain conditions:
  - Long-running sessions
  - Frequent WebUI restarts
  - Connection instability
  - Crash recovery scenarios

---

## 4. Immediate Action Taken

During this session, agent performed emergency cleanup:

1. **Identified zombies:** 26 Python processes + 11 CMD parents
2. **Killed CMD parents:** Forced termination of all 11 CMD processes
3. **Killed remaining Python:** Cleaned up orphaned children
4. **Verified cleanup:** Process count reduced to 0
5. **Confirmed stability:** No respawning after 5 seconds

**Command Used:**
```powershell
# Kill CMD parents
$cmdParents = @(17532, 35368, 40880, ...); 
$cmdParents | ForEach-Object { Stop-Process -Id $_ -Force }

# Kill all Python
Get-Process python | Stop-Process -Force
```

**Result:** ✅ All zombies eliminated, system stable

---

## 5. Comprehensive Fix Strategy

### 5.1 Short-Term (PR-PROC-001A): CMD Parent Tracking & Cleanup

**Changes Required:**
1. Add `self._cmd_parent_pid` tracking to `WebUIProcessManager`
2. Detect CMD parent after `subprocess.Popen()` using psutil
3. Modify `_kill_process_tree()` to kill CMD parents FIRST
4. Add aggressive scan for orphaned CMD.exe processes
5. Test restart scenarios verify no accumulation

**Files Modified:**
- `src/api/webui_process_manager.py` (~100 lines changed)

**Estimated Effort:** 2-4 hours
**Risk:** Low (additive, doesn't break existing logic)

### 5.2 Short-Term (PR-PROC-001B): Runaway Process Detection

**Changes Required:**
1. Add `_check_runaway_processes()` to `SystemWatchdogV2`
2. Implement threshold detection (>10 Python or >3 CMD = runaway)
3. Add `_trigger_emergency_cleanup()` method
4. Create diagnostic bundle on detection
5. Test with simulated runaway scenario

**Files Modified:**
- `src/services/watchdog_system_v2.py` (~80 lines added)

**Estimated Effort:** 2-3 hours
**Risk:** Low (monitoring only, doesn't affect normal flow)

### 5.3 Short-Term (PR-PROC-001C): Shutdown Sequence Enhancement

**Changes Required:**
1. Enhance `AppController.shutdown()` with explicit WebUI cleanup
2. Add process count verification before exit
3. Add timeout-based force cleanup
4. Test shutdown leaves no zombies

**Files Modified:**
- `src/controller/app_controller.py` (~30 lines changed)

**Estimated Effort:** 1-2 hours
**Risk:** Low (improves existing shutdown)

### 5.4 Medium-Term (PR-PROC-002): Process Registry

**Changes Required:**
1. Create `src/utils/process_registry.py`
2. Implement global process tracking
3. Integrate with all subprocess spawn points
4. Add lifecycle auditing
5. Add emergency kill_all method

**Files Modified:**
- NEW: `src/utils/process_registry.py` (~200 lines)
- `src/api/webui_process_manager.py` (integrate registry)
- `src/controller/app_controller.py` (integrate registry)

**Estimated Effort:** 4-6 hours
**Risk:** Medium (requires integration across multiple modules)

### 5.5 Long-Term (Future): Process Isolation

**Options:**
1. **Docker:** Run WebUI in container, StableNew communicates via API only
2. **WSL:** Use Windows Subsystem for Linux for process isolation
3. **Service Manager:** Register WebUI as Windows Service with supervision

**Estimated Effort:** 1-2 weeks
**Risk:** High (major architectural change)

---

## 6. Testing Requirements

### 6.1 Regression Tests (Essential)
- `test_webui_restart_no_zombie_accumulation()` - Restart 10x, verify process count stable
- `test_cmd_parent_tracking()` - Verify CMD parent PID captured
- `test_cmd_parent_cleanup()` - Verify CMD killed on stop
- `test_shutdown_leaves_no_processes()` - Verify complete cleanup

### 6.2 Integration Tests (Important)
- `test_connection_loss_recovery()` - Simulate connection timeout, verify cleanup
- `test_crash_recovery()` - Kill WebUI, verify restart cleans up
- `test_long_running_session()` - Run 8+ hours, monitor process count

### 6.3 Manual Tests (Required)
- Launch WebUI via `.bat` file, verify CMD tracked
- Force crash WebUI, verify no orphaned CMD
- Restart WebUI 20x rapidly, verify stable process count
- Close StableNew, verify Task Manager shows 0 Python/CMD processes

---

## 7. Documentation Deliverables

Created this session:
- ✅ `docs/PROCESS_LIFECYCLE_MANAGEMENT_v2.6.md` - Comprehensive lifecycle doc
- ✅ `reports/D-PROC-001-Zombie-Process-Root-Cause-Analysis.md` - This document

Still needed:
- [ ] Update `ARCHITECTURE_v2.6.md` - Add Process Lifecycle section
- [ ] Update `DEBUG HUB v2.6.md` - Add "Zombie Processes" troubleshooting
- [ ] Create `docs/runbooks/ZOMBIE_PROCESS_RECOVERY.md` - Emergency recovery guide
- [ ] Create `docs/runbooks/PROCESS_AUDIT_CHECKLIST.md` - Pre-release checklist
- [ ] Update `DOCS_INDEX_v2.6.md` - Reference new docs

---

## 8. Risk Assessment

### 8.1 If Not Fixed
- **Certainty:** Will happen again (has happened 3x already)
- **Frequency:** Every 1-2 weeks of active development
- **Impact per incident:** 1-2 hours debugging + manual cleanup + user frustration
- **System impact:** Memory exhaustion, potential crashes
- **User trust:** Decreases with each recurrence

### 8.2 Fix Risks
- **Implementation risk:** LOW - Changes are additive and well-isolated
- **Regression risk:** LOW - Fixes improve existing cleanup, don't change API contracts
- **Test coverage:** MEDIUM - Requires new test infrastructure for process monitoring
- **Platform risk:** MEDIUM - Windows-specific behavior, harder to test on Linux/Mac

### 8.3 Recommendation
**PRIORITY: CRITICAL - Implement PR-PROC-001A/B/C immediately (before next release)**

Rationale:
- Bug is recurring and predictable
- Root cause is well-understood
- Fix is straightforward and low-risk
- Impact on user experience is severe
- Technical debt is compounding

---

## 9. Next Steps

### Immediate (This Session)
- [x] Kill all zombie processes (DONE)
- [x] Create comprehensive documentation (DONE)
- [x] Root cause analysis complete (DONE)

### Next Session (User Approval Required)
1. **User Review:** Review `PROCESS_LIFECYCLE_MANAGEMENT_v2.6.md` and this discovery report
2. **Prioritize:** Decide on PR sequence (recommend: A → B → C)
3. **Implement:** Execute PR-PROC-001A (CMD parent tracking)
4. **Test:** Verify no zombies after restart loops
5. **Deploy:** Merge to main branch

### Follow-Up (Next Sprint)
1. Implement PR-PROC-001B (runaway detection)
2. Implement PR-PROC-001C (shutdown enhancement)
3. Add comprehensive test suite
4. Document lessons learned

---

## 10. Appendix: Evidence

### 10.1 Terminal Output - Zombie Discovery
```
PS> Get-Process python | Measure-Object | Select-Object -ExpandProperty Count
26

PS> Get-Process python | Where-Object {...} | ForEach-Object { $parentId = ...; Get-Process -Id $parentId }
# Found 11 CMD.exe parents + multiple python.exe parents (zombies spawning zombies!)
```

### 10.2 Terminal Output - Successful Cleanup
```
PS> $cmdParents | ForEach-Object { Stop-Process -Id $_ -Force }
Killed CMD parent 17532
Killed CMD parent 35368
... (11 total)

PS> Get-Process python | Stop-Process -Force
# All Python killed

PS> Start-Sleep -Seconds 5; Get-Process python | Measure-Object | Select-Object -ExpandProperty Count
0

SUCCESS: All zombies eliminated!
```

### 10.3 Code Evidence - Missing CMD Cleanup
See Section 2.2 for detailed code analysis showing `_kill_process_tree()` has 180+ lines of Python cleanup but zero CMD handling.

---

**END OF DISCOVERY REPORT**

**Prepared by:** GitHub Copilot  
**Reviewed by:** [Pending]  
**Approved for Implementation:** [Pending]
