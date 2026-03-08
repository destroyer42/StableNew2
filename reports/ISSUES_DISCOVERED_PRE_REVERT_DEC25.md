# Critical Issues Discovered (Pre-Revert Dec 25, 2024)

**Date**: December 25, 2024  
**Context**: Before reverting all uncommitted changes from queue persistence work  
**Branch**: testingBranchFromWorking (created from cooking)  
**Last Good Commit**: 949a40e (Dec 24, 2:28 PM) - "Reprocess work in progress."

---

## Overview

During queue persistence implementation by Codex, multiple **architectural violations** were introduced that caused:
- GUI crashes when clicking "Clear All"  
- Zombie/orphan processes continuing after GUI shutdown  
- Excessive memory growth (50MB → 1500MB)  
- Hundreds of diagnostic files being generated  

While the queue persistence changes need to be scrapped, **critical architectural issues were discovered** that must be fixed even after the revert.

---

## ✅ CRITICAL ISSUES TO FIX (Independent of Queue Persistence)

### 1. **ProcessAutoScannerService Self-Kill Vulnerability** 🔥
**File**: `src/controller/process_auto_scanner_service.py`  
**Severity**: CRITICAL - Can kill the GUI process itself

**Problem**:
- Scanner runs on 30-second intervals checking for idle/memory-heavy Python processes
- Has VS Code exemption logic but **kills repo-scoped Python processes**
- When GUI is idle for 120s OR exceeds 1024MB RAM → **scanner kills the GUI itself**
- Daemon thread with only 1-second join timeout on shutdown

**Evidence from Analysis**:
- Line 64: Starts as daemon thread automatically
- Line 140-142: Exempts VS Code but not self
- Line 73-78: Continuous scanner loop
- Default thresholds: 120s idle, 1024MB memory

**Fix Required**:
```python
# IMMEDIATE FIX (already applied in uncommitted changes):
self.process_auto_scanner = ProcessAutoScannerService(
    config=ProcessAutoScannerConfig(),
    protected_pids=self._get_protected_process_pids,
    start_thread=False,  # DISABLED - prevents GUI from being killed
)
```

**Long-term Fix**:
- Add own PID to protected PIDs list
- Add GUI parent process PID to protected list
- Increase thresholds (e.g., 300s idle, 2048MB memory)
- Add "is_gui_process" check before killing

---

### 2. **SystemWatchdogV2: Zombie Heartbeat Monitor** 🔥
**File**: `src/services/watchdog_system_v2.py:34`  
**Severity**: HIGH - Creates zombie processes and excessive diagnostics

**Problem**:
- Daemon thread runs forever checking UI heartbeat every 1 second
- When stall detected (>3s idle), triggers diagnostic file writes
- Spawns **additional daemon thread** for each diagnostic write
- Only has 2-second timeout on `.stop()` - inadequate for cleanup
- **Continues running after GUI closes**, writing diagnostic files forever

**Evidence**:
- 200+ diagnostic ZIP files generated (Dec 14-24)
- Files named `stablenew_diagnostics_YYYYMMDD_HHMMSS_ui_heartbeat_stall.zip`
- All from dates/times when GUI was closed but watchdog still running
- Each file ~200-700KB

**Fix Required**:
1. Change daemon=True to daemon=False
2. Track thread in AppController._tracked_threads
3. Increase join timeout to 10 seconds minimum
4. Add graceful shutdown flag check in _loop()
5. Prevent diagnostic writes during shutdown phase

---

### 3. **Thread Lifecycle Management: No Tracking** 🔥
**Files**: Multiple (app_controller.py, job_execution_controller.py, etc.)  
**Severity**: HIGH - Source of all zombie process issues

**Problem**:
Multiple locations spawn background threads with **no tracking or cleanup**:

**Locations Found**:
- `app_controller.py:226` - Queue submission thread (daemon=True)
- `app_controller.py:675` - Draft job enqueue thread (daemon=True)
- `app_controller.py:2961` - Shutdown watchdog thread (daemon=True)
- `job_execution_controller.py:127` - Auto-start worker during `__init__` (before GUI ready)
- `single_node_runner.py:241` - Worker thread with only 2s join timeout

**Root Cause**:
- No centralized thread registry
- No `threading.Thread.join()` calls in shutdown sequence
- Daemon threads with inadequate join timeouts
- Threads spawned during object construction (before shutdown hooks wired)

**Fix Required**:
```python
# Pattern from uncommitted changes (PRESERVE THIS CONCEPT):
class AppController:
    def __init__(self):
        self._tracked_threads: list[threading.Thread] = []
        self._thread_lock = threading.Lock()
    
    def _spawn_tracked_thread(self, target, args=(), name=None):
        """All background threads must use this method."""
        thread = threading.Thread(target=target, args=args, 
                                 daemon=False, name=name)  # Non-daemon!
        with self._thread_lock:
            self._tracked_threads.append(thread)
        thread.start()
        return thread
    
    def shutdown(self):
        """Wait for all tracked threads before shutdown."""
        with self._thread_lock:
            for thread in self._tracked_threads:
                thread.join(timeout=10.0)  # Adequate timeout
```

---

### 4. **Queue Clear: GUI Thread Blocking** 🔥
**File**: `src/controller/app_controller.py:1820-1833`  
**Severity**: MEDIUM-HIGH - Causes GUI freezes

**Problem**:
- `on_queue_clear_v2()` performs **synchronous operations on GUI thread**:
  1. `queue.clear()` - Acquires lock, iterates heap, rebuilds queue
  2. `_refresh_app_state_queue()` - Updates GUI state
  3. `_save_queue_state()` - **Writes JSON to disk on GUI thread**

**Fix Required**:
- Move queue clear to background thread
- Use callback to update GUI after completion
- Or use `after_idle()` to defer file I/O

---

### 5. **Memory Leaks: Unbounded Collections** 🔥
**Multiple Files**  
**Severity**: MEDIUM - Causes gradual memory growth

**Problems Found**:

1. **JobQueue._finalized_jobs** (`job_queue.py:207-210`):
   - Dict grows unbounded with completed jobs
   - Never cleaned up
   - Fix: Add max size or TTL-based eviction

2. **ProcessAutoScannerSummary.killed** (`process_auto_scanner_service.py:32`):
   - List of killed processes with no max size
   - Grows indefinitely during long sessions
   - Fix: Cap at 100 most recent

3. **AppController CancelToken dict** (`app_controller.py:183-190`):
   - Tokens for cancelled jobs never purged
   - Fix: Clean up after job completes

4. **Job payload retention**:
   - `Job.payload` holds pipeline callables with closures over large objects
   - Fix: Clear payload after job completes

---

### 6. **Shutdown Sequence: Incomplete** 🔥
**File**: `src/controller/app_controller.py:2953-3113` (shutdown_app)  
**Severity**: HIGH - All zombie issues stem from this

**Current Shutdown Order**:
1. Cancel active jobs
2. Stop background work
3. Shutdown learning hooks
4. Shutdown WebUI
5. Shutdown job service

**Missing Steps**:
- ❌ Join on all spawned background threads
- ❌ Stop ProcessAutoScannerService
- ❌ Stop SystemWatchdogV2
- ❌ Verify all threads are dead before exit
- ❌ Close file handles (history store writer)

**Fix Required**:
Add comprehensive shutdown sequence that waits for ALL background operations.

---

## 🚫 CHANGES TO DISCARD (Queue Persistence Bugs)

These changes from Codex broke the system and should NOT be preserved:

1. **Queue state persistence logic in AppController**
   - Added complex save/restore logic that crashes on clear
   - Introduced race conditions in queue operations

2. **JobExecutionController deferred autostart**
   - Spawns worker thread during `__init__` before GUI ready
   - Causes orphaned threads if shutdown happens during init

3. **Async job submission without proper error handling**
   - Multiple background threads without coordination
   - No feedback to user when operations fail silently

4. **Queue state JSON serialization**
   - Attempts to serialize non-serializable job objects
   - Causes crashes when queue contains certain job types

---

## 📋 Action Plan (Post-Revert)

### Phase 1: Critical Fixes (Do First)
1. **Disable ProcessAutoScannerService** - Immediate safety fix
2. **Fix SystemWatchdogV2 shutdown** - Stop zombie diagnostics
3. **Implement thread tracking** - Foundation for clean shutdown
4. **Fix shutdown sequence** - Join all threads before exit

### Phase 2: Memory Leak Fixes
1. Cap `_finalized_jobs` dict size
2. Cap `ProcessAutoScannerSummary.killed` list
3. Purge old CancelTokens
4. Clear Job.payload after completion

### Phase 3: Queue Clear Fix
1. Move queue operations to background thread
2. Add proper GUI callback mechanism

### Phase 4: Queue Persistence (Redesign)
- **DO NOT** implement until Phases 1-3 are complete and stable
- When implementing, use proper async patterns
- Add comprehensive error handling
- Test thoroughly before committing

---

## 🔬 How We Discovered These Issues

The queue persistence work acted as a "stress test" that exposed these latent architectural issues:

1. **Increased background thread activity** → Revealed lack of thread tracking
2. **More frequent queue operations** → Exposed ProcessAutoScanner self-kill bug
3. **Longer running sessions** → Revealed memory leaks
4. **More shutdown/restart cycles** → Exposed incomplete shutdown sequence
5. **Diagnostic system activation** → Revealed SystemWatchdog zombie behavior

**These issues existed before but were masked by:**
- Shorter testing sessions
- Less concurrent activity
- Manual restarts before issues manifested

---

## 💡 Key Architectural Lessons

### 1. **All Background Threads Must Be Tracked**
- No more `daemon=True` without explicit justification
- All threads must be joined during shutdown
- Use centralized thread registry pattern

### 2. **Never Spawn Threads in __init__**
- Constructor should only initialize state
- Background operations should be explicit `start()` calls
- Gives caller control over lifecycle

### 3. **Shutdown Must Be Comprehensive**
- Every start() needs matching stop()
- Every thread needs join()
- Every file handle needs close()
- No assumptions about "daemon will die automatically"

### 4. **I/O Operations Off GUI Thread**
- File writes, network calls, heavy computation → background thread
- GUI thread only for UI updates and event handling

### 5. **Bounded Collections**
- Every list/dict that accumulates must have max size or TTL
- No "it won't grow that large" assumptions

---

## 🎯 Success Criteria (Post-Fix)

Before considering queue persistence again:

1. ✅ GUI runs for 1+ hour without memory growth
2. ✅ Shutdown completes in <5 seconds with no zombies
3. ✅ ProcessAutoScanner never kills GUI
4. ✅ SystemWatchdog stops cleanly on shutdown
5. ✅ No diagnostic files written after GUI closes
6. ✅ All background threads join within 10 seconds
7. ✅ Queue operations don't block GUI
8. ✅ Process monitoring shows clean exit (no orphans)

---

## 📁 Files to Reference

These files contain the critical issues analysis:
- `reports/GUI_CRASH_AND_ZOMBIE_PROCESS_ANALYSIS.md` - Detailed root cause analysis
- This file - High-level summary for post-revert work

---

**Status**: Ready for revert. Issues documented for subsequent fixes.
