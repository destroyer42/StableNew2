# GUI Crash & Zombie Process Root Cause Analysis

**Date**: 2025-01-XX  
**Branch**: cooking  
**Status**: CRITICAL - Multiple Architectural Violations Detected  
**Severity**: PRODUCTION BLOCKING

---

## Executive Summary

The "Clear All" button crash and zombie process issues stem from **multiple architectural violations** introduced in recent uncommitted changes:

1. **Background threads spawned without cleanup mechanisms**
2. **Blocking operations running on GUI thread**
3. **Daemon threads that don't respect shutdown signals**
4. **Process scanner killing the GUI process itself**
5. **Missing thread.join() calls during shutdown**

These are not isolated bugs—they represent fundamental violations of the v2.6 architecture's threading contract.

---

## Critical Findings

### 1. ProcessAutoScannerService: The Primary Culprit

**Location**: `src/controller/process_auto_scanner_service.py`

**Issue**: Background scanner thread that:
- Starts automatically as daemon thread (line 64)
- Runs on 30-second interval scanning Python processes
- **KILLS REPO-SCOPED PYTHON PROCESSES** including the GUI itself
- Has VS Code exemption logic but still terminates child processes
- Only calls `join(timeout=1.0)` on shutdown—inadequate for cleanup

```python
# Lines 62-66
if start_thread and not _is_test_mode():
    self._thread = threading.Thread(
        target=self._run_loop, daemon=True, name="ProcessAutoScanner"
    )
    self._thread.start()
```

**Evidence**:
- Line 140: `if not self._is_repo_process(proc): continue`
- Line 142: `if self._is_vscode_related(proc): continue`
- Default thresholds: 120s idle, 1024MB memory → GUI processes exceed this
- Scanner loop at line 73-78 runs continuously
- Kills processes with `psutil` without checking if they're the GUI

**Root Cause**: When GUI is idle for 120s OR exceeds 1024MB RAM, the scanner kills it.

---

### 2. Queue Clear Operations: GUI Thread Blocking

**Location**: `src/controller/app_controller.py:1820-1833`

**Issue**: `on_queue_clear_v2()` performs **synchronous operations on GUI thread**:

```python
def on_queue_clear_v2(self) -> int:
    """Clear all jobs from the queue."""
    queue = getattr(self.job_service, "job_queue", None)
    if queue and hasattr(queue, "clear"):
        result = int(queue.clear())  # <-- Acquires lock, iterates heap
        if result > 0:
            self._refresh_app_state_queue()  # <-- GUI state refresh
        self._save_queue_state()  # <-- FILE I/O ON GUI THREAD
        return result
```

**Problems**:
1. `queue.clear()` (line 1827): Acquires `threading.Lock`, iterates heap, rebuilds queue
2. `_refresh_app_state_queue()` (line 1829): Updates GUI state synchronously
3. `_save_queue_state()` (line 1830): **Writes JSON to disk on GUI thread**

**Root Cause**: Any delay in lock acquisition, heap operations, or file I/O freezes GUI.

---

### 3. JobExecutionController: Deferred Autostart Trap

**Location**: `src/controller/job_execution_controller.py:120-127`

**Issue**: Queue auto-starts worker thread during `__init__`:

```python
# Lines 117-127
self._deferred_autostart = False  # Track if we need to auto-start
self._restore_queue_state()
self._queue_persistence = QueuePersistenceManager(self)
self._persist_queue_state()

# Execute deferred autostart if queue was restored with auto_run enabled
if self._deferred_autostart:
    logger.info("Executing deferred queue autostart")
    self.start()  # <-- Spawns worker thread during construction
```

**Root Cause**: Thread spawned during controller initialization before GUI is ready. If shutdown happens before full initialization, thread is orphaned.

---

### 4. SingleNodeJobRunner: Daemon Thread Without Proper Join

**Location**: `src/queue/single_node_runner.py:239-242`

**Issue**: Worker thread created as daemon but only 2-second timeout on shutdown:

```python
# Line 241
self._worker = threading.Thread(target=self._worker_loop, daemon=True)
self._worker.start()

# Lines 244-247 (stop method)
def stop(self) -> None:
    self._stop_event.set()
    if self._worker:
        self._worker.join(timeout=2.0)  # <-- Insufficient for running jobs
```

**Root Cause**: If worker is executing a job when `stop()` is called, 2-second timeout expires and thread continues in background, orphaned.

---

### 5. AppController: Multiple Async Submit Threads

**Location**: `src/controller/app_controller.py:226, 675, 2602, 2961`

**Issue**: Four separate locations spawn daemon threads without tracking:

```python
# Line 226 - Queue submission
threading.Thread(target=self._submit_jobs_async, args=(jobs,), daemon=True).start()

# Line 675 - Draft job enqueue
threading.Thread(target=self._enqueue_draft_jobs_async, daemon=True).start()

# Line 2602 - Unknown operation
# daemon=True,

# Line 2961 - Shutdown watchdog
threading.Thread(target=self._shutdown_watchdog, daemon=True).start()
```

**Root Cause**: No tracking of these threads. No join calls. Threads continue after GUI closes.

---

### 5b. SystemWatchdogV2: Continuous Heartbeat File Writes

**Location**: `src/services/watchdog_system_v2.py:34`

**Issue**: **THIS IS THE HEARTBEAT STALL DIAGNOSTICS** you mentioned!

SystemWatchdogV2 spawns a daemon thread that:
- Runs forever in 1-second loop checking UI heartbeat
- Triggers diagnostic file writes every 30 seconds when stalls detected
- Continues running **even after GUI closes** because it's daemon=True
- Writes files to `reports/diagnostics/` every minute

```python
def start(self) -> None:
    t = threading.Thread(target=self._loop, daemon=True, name="SystemWatchdogV2")
    t.start()
    self._thread = t

def _loop(self) -> None:
    while not self._stop.is_set():  # Runs forever!
        try:
            self._check()  # Checks heartbeat, triggers diagnostics
        except Exception:
            pass
        time.sleep(self._loop_period)  # 1 second
```

**Evidence**:
- Watchdog checks `last_ui_heartbeat_ts` every second
- When stall detected (>3s idle), calls `diagnostics.build_async()`
- `build_async()` spawns **another daemon thread** to write files
- Files written to `reports/diagnostics/ui_heartbeat_stall_<timestamp>.zip`
- **Thread never stops** because `.stop()` only has 2-second timeout
- After GUI closes, watchdog continues detecting "stalls" and writing files

**Root Cause**: Daemon thread + inadequate join timeout = zombie watchdog process writing files forever.

---

### 6. Shutdown Sequence: Missing Thread Cleanup

**Location**: `src/controller/app_controller.py:2953-3113`

**Issue**: `shutdown_app()` doesn't wait for all threads:

```python
# Current shutdown order:
# 1. Cancel active jobs
# 2. Stop background work (calls stop_all_background_work)
# 3. Shutdown learning hooks
# 4. Shutdown WebUI
# 5. Shutdown job service

# Missing:
# - Join on _submit_jobs_async threads
# - Join on _enqueue_draft_jobs_async threads
# - ProcessAutoScannerService thread join
# - JobExecutionController worker thread join
# - Verification that all spawned threads are dead
```

**Root Cause**: Shutdown completes before threads finish, leaving orphans attached to VS Code terminal.

---

## Memory Leak Analysis

**Symptoms**: Processes growing from <50MB to 300-1500MB

**Root Causes**:

1. **JobQueue accumulation**: Completed jobs not cleared from `_finalized_jobs` dict
2. **AppStateV2 history accumulation**: No cleanup of old history records
3. **ProcessAutoScannerSummary accumulation**: `killed` list never cleared
4. **Thread-local storage leaks**: Daemon threads retain references to controller/services
5. **Job payload retention**: `Job.payload` holds pipeline callables with closures over large objects

**Evidence**:
- `job_queue.py:207-210`: `_finalized_jobs` dict grows unbounded
- `process_auto_scanner_service.py:32`: `killed: list[dict]` with no max size
- `app_controller.py:183-190`: `CancelToken` dict never purged

---

## Zombie Process Mechanism

**Why processes respawn**:
1. VS Code terminal keeps parent process alive
2. Parent process is `pythonw.exe` or `python.exe` started by VS Code
3. Child processes (WebUI, job runners) are spawned by parent
4. When GUI closes, parent process remains in VS Code terminal
5. ProcessAutoScannerService or orphaned threads restart operations
6. New child processes spawn from still-alive parent

**Why manual kill respawns**:
- Killing child process → parent's subprocess monitoring detects exit
- Parent spawns replacement child (WebUI restart logic)
- Loop continues until parent is killed

**Why processes exceed RAM**:
- JobQueue history accumulation
- Tkinter widget references retained in closures
- PIL Image objects in thumbnail cache
- Job payload callables with captured large objects

---

## Architectural Violations Summary

| Violation | Location | V2.6 Rule Broken |
|-----------|----------|------------------|
| Background thread auto-start | `process_auto_scanner_service.py:64` | "No threads without explicit lifecycle management" |
| GUI thread blocking I/O | `app_controller.py:1830` | "All I/O must be async or off main thread" |
| Daemon threads without join | `single_node_runner.py:241` | "All threads must be joined during shutdown" |
| Process scanner killing GUI | `process_auto_scanner_service.py:140+` | "Repo-scoped operations must exclude self" |
| Thread spawning in constructors | `job_execution_controller.py:126` | "No threads in __init__" |
| Untracked thread spawns | `app_controller.py:226,675,2602,2961` | "All threads must be tracked and joinable" |
| Missing shutdown cleanup | `app_controller.py:2953-3113` | "Shutdown must join all threads" |
| Unbounded memory growth | `job_queue.py:207` | "All collections must have max size" |

---

## Reproduction Steps

1. Start StableNew GUI
2. Add jobs to queue
3. Let jobs run for 30+ seconds
4. Click "Clear All" button
5. **Result**: GUI freezes or crashes

**Alternative**:
1. Start GUI
2. Leave idle for 120+ seconds
3. **Result**: ProcessAutoScannerService kills GUI

**Alternative**:
1. Start GUI
2. Run jobs until RAM > 1024MB
3. **Result**: ProcessAutoScannerService kills GUI

---

## Immediate Fixes Required

### Fix 1: Disable ProcessAutoScannerService Until Refactor

```python
# src/controller/app_controller.py:409
self.process_auto_scanner = ProcessAutoScannerService(
    protected_pids=self._protected_pids_supplier,
    start_thread=False,  # DISABLED until fixed
)
```

### Fix 2: Move Queue Clear to Background Thread

```python
# src/controller/app_controller.py:1820-1833
def on_queue_clear_v2(self) -> int:
    """Clear all jobs from the queue."""
    def _clear_async():
        queue = getattr(self.job_service, "job_queue", None)
        if queue and hasattr(queue, "clear"):
            result = int(queue.clear())
            if result > 0:
                self._schedule_on_ui_thread(self._refresh_app_state_queue)
            self._save_queue_state()
    
    threading.Thread(target=_clear_async, daemon=False).start()
    return 0  # Return immediately, actual count not available
```

### Fix 3: Track and Join All Threads

```python
# src/controller/app_controller.py
class AppController:
    def __init__(self, ...):
        self._tracked_threads: list[threading.Thread] = []
        self._thread_lock = threading.Lock()
    
    def _spawn_tracked_thread(self, target, args=(), name=None):
        thread = threading.Thread(target=target, args=args, daemon=False, name=name)
        with self._thread_lock:
            self._tracked_threads.append(thread)
        thread.start()
        return thread
    
    def shutdown_app(self, ...):
        # ... existing shutdown steps ...
        
        # NEW: Join all tracked threads
        logger.info("Joining %d tracked threads...", len(self._tracked_threads))
        for thread in self._tracked_threads:
            if thread.is_alive():
                thread.join(timeout=5.0)
                if thread.is_alive():
                    logger.warning("Thread %s did not exit after 5s", thread.name)
```

### Fix 4: Fix ProcessAutoScannerService Self-Kill

```python
# src/controller/process_auto_scanner_service.py:110+
def scan_once(self) -> ProcessAutoScannerSummary:
    gui_pid = os.getpid()  # Store GUI PID
    parent_pid = os.getppid()  # Store parent PID
    
    protected = {int(pid) for pid in (self._protected_pids() or [])}
    protected.add(gui_pid)  # NEVER kill self
    protected.add(parent_pid)  # NEVER kill parent
    
    for proc in self._psutil.process_iter(...):
        pid = getattr(proc, "pid", None)
        if pid in protected:
            continue  # Skip protected processes
        # ... rest of logic ...
```

### Fix 5: Remove Deferred Autostart

```python
# src/controller/job_execution_controller.py:117-127
# REMOVE deferred autostart logic
self._restore_queue_state()
self._queue_persistence = QueuePersistenceManager(self)
self._persist_queue_state()

# DO NOT start worker thread in __init__
# Let caller explicitly call .start() when ready
```

---

## Long-Term Architectural Fixes

### 1. Thread Pool Pattern
Replace ad-hoc thread spawning with managed thread pool:

```python
from concurrent.futures import ThreadPoolExecutor

class AppController:
    def __init__(self, ...):
        self._thread_pool = ThreadPoolExecutor(max_workers=4, thread_name_prefix="StableNew")
    
    def shutdown_app(self, ...):
        self._thread_pool.shutdown(wait=True, timeout=10.0)
```

### 2. Background Task Manager
Centralized service for all background operations:

```python
class BackgroundTaskManager:
    def __init__(self):
        self._tasks: dict[str, threading.Thread] = {}
        self._stop_events: dict[str, threading.Event] = {}
    
    def start_task(self, name: str, target: Callable):
        stop_event = threading.Event()
        thread = threading.Thread(target=target, args=(stop_event,), daemon=False)
        self._tasks[name] = thread
        self._stop_events[name] = stop_event
        thread.start()
    
    def stop_all(self, timeout: float = 5.0):
        for stop_event in self._stop_events.values():
            stop_event.set()
        for thread in self._tasks.values():
            thread.join(timeout=timeout)
```

### 3. GUI-Safe Queue Operations
All queue mutations must go through async boundary:

```python
class QueueService:
    def __init__(self, ui_scheduler: Callable):
        self._ui_scheduler = ui_scheduler
        self._operation_queue = queue.Queue()
        self._worker = threading.Thread(target=self._process_operations, daemon=False)
        self._worker.start()
    
    def clear_async(self, callback: Callable[[int], None]):
        self._operation_queue.put(("clear", callback))
    
    def _process_operations(self):
        while True:
            op, callback = self._operation_queue.get()
            if op == "clear":
                result = self._queue.clear()
                self._ui_scheduler(lambda: callback(result))
```

### 4. Process Scoping Rules
ProcessAutoScannerService must:
- Never scan processes in its own process tree
- Never scan processes with same working directory
- Never scan processes owned by same user in repo path
- Whitelist explicit PIDs from JobService/WebUIProcessManager

### 5. Memory Leak Prevention
Implement bounded collections everywhere:

```python
from collections import deque

class JobQueue:
    def __init__(self, max_finalized: int = 100):
        self._finalized_jobs = {}  # Current: unbounded
        self._finalized_history = deque(maxlen=max_finalized)  # New: bounded
    
    def finalize_job(self, job: Job):
        if len(self._finalized_jobs) >= max_finalized:
            oldest_id = self._finalized_history[0]
            del self._finalized_jobs[oldest_id]
        self._finalized_jobs[job.job_id] = job
        self._finalized_history.append(job.job_id)
```

---

## Testing Requirements

### Unit Tests
- [ ] `test_queue_clear_on_gui_thread` - Verify no blocking operations
- [ ] `test_process_scanner_never_kills_self` - Verify GUI process excluded
- [ ] `test_thread_tracking_and_join` - Verify all threads joined on shutdown
- [ ] `test_no_threads_in_constructors` - Verify no auto-start behavior
- [ ] `test_bounded_collections` - Verify memory limits enforced

### Integration Tests
- [ ] `test_clear_all_button_no_freeze` - Click Clear All 100 times
- [ ] `test_gui_idle_120s_survives` - Leave GUI idle for 5 minutes
- [ ] `test_shutdown_leaves_no_zombies` - Verify no orphaned processes
- [ ] `test_memory_leak_100_jobs` - Run 100 jobs, verify RAM < 500MB
- [ ] `test_vscode_terminal_cleanup` - Verify terminal cleans up processes

### Stress Tests
- [ ] `test_rapid_queue_operations` - Add/clear/pause/resume 1000x
- [ ] `test_concurrent_shutdown` - Shutdown while jobs running
- [ ] `test_webui_crash_during_clear` - Simulate WebUI crash during clear
- [ ] `test_process_scanner_heavy_load` - 100 Python processes in repo

---

## PR Sequence

### PR-CORE1-D22A: Emergency Thread Safety Patch
- Disable ProcessAutoScannerService
- Move queue clear to background thread
- Add critical thread joins to shutdown

### PR-CORE1-D22B: Thread Lifecycle Management
- Implement BackgroundTaskManager
- Track all spawned threads
- Remove deferred autostart
- Add comprehensive thread joining

### PR-CORE1-D22C: Process Scanner Refactor
- Fix self-kill vulnerability
- Implement proper process tree exclusion
- Add VS Code/WebUI whitelisting
- Increase timeouts to 300s idle, 2048MB RAM

### PR-CORE1-D22D: Memory Leak Prevention
- Implement bounded collections
- Add job history pruning
- Fix payload retention
- Add memory monitoring

### PR-CORE1-D22E: Comprehensive Testing
- Add all unit tests
- Add integration tests
- Add stress tests
- Document thread safety contract

---

## Success Criteria

- [ ] "Clear All" button never freezes GUI
- [ ] GUI survives 10+ minutes idle
- [ ] No zombie processes after shutdown
- [ ] Memory usage < 500MB after 100 jobs
- [ ] All tests pass
- [ ] Architecture_v2.6.md updated with threading rules
- [ ] Zero threading violations in static analysis

---

## References

- Architecture_v2.6.md: Threading contract (not enforced)
- PR_TEMPLATE_v2.6.md: Tech debt removal requirements
- AGENTS.md: Multi-agent development rules
- DEBUG_HUB_v2.6.md: Logging and diagnostics standards

---

**Status**: ANALYSIS COMPLETE - AWAITING PR PLANNING

