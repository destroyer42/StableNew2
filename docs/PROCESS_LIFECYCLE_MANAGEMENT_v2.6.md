# Process Lifecycle Management v2.6
## Critical Systems Documentation: Preventing Runaway Process Spawning

**Status:** CANONICAL  
**Last Updated:** 2025-12-25  
**Incident:** Recurring zombie CMD.exe + python.exe spawn loops causing memory leaks

---

## 1. Problem Statement

### 1.1 Symptom
StableNew experiences runaway process spawning where:
- **14-26+ zombie Python processes** accumulate in Task Manager
- **11+ CMD.exe parent processes** spawn continuously
- Processes respawn immediately when killed
- Memory leak compounds over time (GBs)
- **THIS HAS HAPPENED 2-3 TIMES BEFORE**

### 1.2 Root Cause Analysis

**PRIMARY CAUSE: Incomplete Process Tree Cleanup**
- When WebUI process is terminated, `_kill_process_tree()` only kills `python.exe` processes
- **CMD.exe parents are NEVER killed** → they respawn children indefinitely
- Windows creates process hierarchies: `cmd.exe` → `python.exe` → child workers

**SECONDARY CAUSE: Auto-Restart Logic Without Parent Tracking**
- WebUI has `auto_restart_on_crash` capability
- No tracking of CMD.exe parents when restart triggered
- Each restart leaves orphaned CMD shells

**TERTIARY CAUSE: Missing Thread/Process Lifecycle Auditing**
- Many threads use raw `threading.Thread()` without tracking
- No global process registry for CMD parents
- `shutdown()` methods exist but aren't always called
- No detection of runaway spawning until system overwhelmed

### 1.3 Attack Vectors (How Zombies Spawn)

1. **WebUI Launch via `.bat` files**
   - User launches `webui-user.bat` or `launch.py`
   - Creates CMD shell → spawns Python → creates worker processes
   - CMD shell persists even after Python exits

2. **Connection Loss Auto-Restart**
   - StableNew detects WebUI connection timeout
   - Triggers `restart_webui()` → spawns new process
   - Old CMD parents not cleaned up first

3. **Crash Recovery Attempts**
   - WebUI crashes during job execution
   - `auto_restart_on_crash` logic fires
   - New CMD + Python spawned, old not killed

4. **Shutdown Without Cleanup**
   - StableNew GUI crashes or force-closed
   - `shutdown()` never called → processes orphaned
   - Orphaned processes continue spawning (if auto-restart enabled)

---

## 2. Current Implementation Analysis

### 2.1 Process Spawn Points

| Location | Method | Creates What | Parent Tracking? |
|----------|--------|--------------|------------------|
| `src/api/webui_process_manager.py:199` | `start()` | `subprocess.Popen` for WebUI | ❌ NO - only tracks Python PID |
| `src/utils/webui_discovery.py:175` | `launch_webui_safely()` | `subprocess.Popen` with `CREATE_NEW_CONSOLE` | ❌ NO |
| `scripts/launch_webui.py:57` | `launch_webui()` | `subprocess.Popen` with shell/console | ❌ NO |

**Critical Finding:** All three spawn methods create processes, but NONE track CMD.exe parents!

### 2.2 Process Cleanup Points

| Location | Method | Kills What | Kills CMD Parents? |
|----------|--------|------------|-------------------|
| `src/api/webui_process_manager.py:571-760` | `_kill_process_tree()` | Python children + WebUI process | ❌ NO |
| `src/api/webui_process_manager.py:762` | `_taskkill_tree()` | Uses Windows `taskkill /T` | ✅ YES (but only as fallback) |
| `src/api/webui_process_manager.py:340-410` | `stop_webui()` | Terminates main process | ❌ NO CMD cleanup |

**Critical Gap:** `_kill_process_tree()` has extensive Python cleanup logic but **zero CMD.exe handling**!

### 2.3 Restart Logic Audit

```python
# src/api/webui_process_manager.py:425-520
def restart_webui(self, ...) -> bool:
    self.stop_webui()  # ← Only kills Python processes, not CMD parents!
    try:
        self.start()   # ← Spawns NEW CMD parent without cleaning old ones
    except Exception:
        return False
    # ... health check logic
```

**Problem:** `restart_webui()` calls `stop_webui()` which calls `_kill_process_tree()`, but that method doesn't kill CMD parents → new CMD spawned while old CMD still alive!

---

## 3. Comprehensive Fix Strategy

### 3.1 Short-Term Fixes (IMMEDIATE)

#### Fix 1: Add CMD.exe Parent Tracking & Cleanup
**File:** `src/api/webui_process_manager.py`

**Add to `WebUIProcessManager.__init__`:**
```python
self._cmd_parent_pid: int | None = None  # Track CMD.exe parent if exists
```

**Modify `start()` method (after Popen creation):**
```python
# After: self._process = subprocess.Popen(...)
self._pid = self._process.pid

# NEW: Detect CMD parent using psutil
try:
    import psutil
    child_proc = psutil.Process(self._pid)
    parent_proc = child_proc.parent()
    if parent_proc and 'cmd' in parent_proc.name().lower():
        self._cmd_parent_pid = parent_proc.pid
        logger.info(f"Detected CMD parent PID {self._cmd_parent_pid} for WebUI process {self._pid}")
    else:
        self._cmd_parent_pid = None
except Exception as exc:
    logger.debug(f"Could not detect CMD parent: {exc}")
    self._cmd_parent_pid = None
```

**Modify `_kill_process_tree()` to kill CMD parents FIRST:**
```python
def _kill_process_tree(self, pid: int | None) -> None:
    if pid is None:
        return
    
    killed_pids = []
    
    if os.name == "nt":
        try:
            import psutil
            
            # STEP 1: Kill CMD parent first (if tracked)
            if self._cmd_parent_pid:
                try:
                    cmd_proc = psutil.Process(self._cmd_parent_pid)
                    logger.warning(f"Killing CMD parent PID {self._cmd_parent_pid} ({cmd_proc.name()})")
                    cmd_proc.kill()
                    killed_pids.append(self._cmd_parent_pid)
                    self._cmd_parent_pid = None
                except psutil.NoSuchProcess:
                    logger.info(f"CMD parent {self._cmd_parent_pid} already dead")
                except Exception as exc:
                    logger.error(f"Failed to kill CMD parent {self._cmd_parent_pid}: {exc}")
            
            # STEP 2: Find ALL CMD.exe processes that might be WebUI-related
            logger.warning("Scanning for orphaned CMD.exe parents...")
            webui_dir = self._config.working_dir
            
            for proc in psutil.process_iter(['pid', 'name', 'cmdline', 'cwd']):
                try:
                    if 'cmd' in proc.info['name'].lower():
                        cmdline = proc.info.get('cmdline') or []
                        cwd = proc.info.get('cwd', '')
                        cmdline_str = ' '.join(cmdline).lower()
                        
                        # Check if CMD is running WebUI-related batch files
                        webui_keywords = ['webui', 'launch', 'stable-diffusion', 'run.bat']
                        is_webui_cmd = any(kw in cmdline_str for kw in webui_keywords)
                        
                        # Check if CMD working dir matches WebUI dir
                        if webui_dir and cwd:
                            try:
                                if Path(cwd).resolve() == Path(webui_dir).resolve():
                                    is_webui_cmd = True
                            except Exception:
                                pass
                        
                        if is_webui_cmd:
                            logger.warning(f"Killing orphaned CMD PID {proc.pid}: {cmdline_str[:80]}")
                            proc.kill()
                            killed_pids.append(proc.pid)
                
                except (psutil.NoSuchProcess, psutil.AccessDenied):
                    pass
            
            # STEP 3: Now kill Python processes (existing logic)
            # ... [keep existing Python cleanup code]
```

#### Fix 2: Add Runaway Process Detection
**File:** `src/services/watchdog_system_v2.py`

**Add new check:**
```python
def _check_runaway_processes(self) -> None:
    """Detect if WebUI-related processes are spawning out of control."""
    try:
        import psutil
        
        # Count python.exe processes
        python_count = 0
        cmd_count = 0
        webui_dir = self._config.working_dir if hasattr(self, '_config') else None
        
        for proc in psutil.process_iter(['name', 'cwd']):
            name = proc.info.get('name', '').lower()
            if 'python' in name:
                python_count += 1
            if 'cmd' in name:
                cwd = proc.info.get('cwd', '')
                if webui_dir and cwd and Path(cwd).resolve() == Path(webui_dir).resolve():
                    cmd_count += 1
        
        # THRESHOLDS: 
        # Normal: 1-3 Python processes (GUI + workers)
        # Warning: 5-10 processes
        # CRITICAL: 10+ processes = runaway spawn
        
        if python_count > 10 or cmd_count > 3:
            logger.error(
                f"RUNAWAY PROCESS DETECTION: {python_count} Python + {cmd_count} CMD processes! "
                "Triggering emergency cleanup..."
            )
            self._trigger_emergency_cleanup(python_count, cmd_count)
            return "runaway_processes_detected"
    
    except ImportError:
        pass  # psutil not available
    except Exception as exc:
        logger.debug(f"Runaway process check failed: {exc}")
    
    return None

def _trigger_emergency_cleanup(self, python_count: int, cmd_count: int) -> None:
    """Emergency process cleanup when runaway spawning detected."""
    from src.api.webui_process_manager import _GLOBAL_WEBUI_PROCESS_MANAGER
    
    if _GLOBAL_WEBUI_PROCESS_MANAGER:
        logger.warning("Forcing WebUI process manager shutdown...")
        try:
            _GLOBAL_WEBUI_PROCESS_MANAGER.stop_webui(grace_seconds=2.0)
        except Exception as exc:
            logger.error(f"Emergency cleanup failed: {exc}")
    
    # Create diagnostic bundle
    self._create_diagnostic_bundle("runaway_processes", severity="critical")
```

#### Fix 3: Shutdown Sequence Enhancement
**File:** `src/controller/app_controller.py`

**Modify `shutdown()` method:**
```python
def shutdown(self) -> None:
    """Enhanced shutdown with comprehensive process cleanup."""
    logger.info("[controller] shutdown() - Starting comprehensive cleanup")
    
    # STEP 1: Stop watchdog
    if self.watchdog:
        try:
            self.watchdog.stop()
            logger.info("[controller] Watchdog stopped")
        except Exception as exc:
            logger.error(f"Watchdog shutdown failed: {exc}")
    
    # STEP 2: Flush history store
    if hasattr(self, 'history_store') and self.history_store:
        try:
            self.history_store.shutdown()
            logger.info("[controller] History store shut down")
        except Exception as exc:
            logger.error(f"History store shutdown failed: {exc}")
    
    # STEP 3: Kill WebUI processes (including CMD parents)
    if hasattr(self, 'webui_process_manager') and self.webui_process_manager:
        try:
            logger.warning("[controller] Forcing WebUI process cleanup (including CMD parents)...")
            self.webui_process_manager.stop_webui(grace_seconds=5.0)
            logger.info("[controller] WebUI processes cleaned up")
        except Exception as exc:
            logger.error(f"WebUI cleanup failed: {exc}")
    
    # STEP 4: Join all tracked threads
    self._join_tracked_threads(timeout=3.0)
    
    logger.info("[controller] shutdown() complete")
```

### 3.2 Medium-Term Enhancements

#### Enhancement 1: Process Registry
**New File:** `src/utils/process_registry.py`

```python
"""Global process registry for lifecycle tracking."""
import threading
from typing import Dict, Set
import psutil

class ProcessRegistry:
    """Thread-safe registry of all StableNew-managed processes."""
    
    def __init__(self):
        self._lock = threading.Lock()
        self._python_pids: Set[int] = set()
        self._cmd_pids: Set[int] = set()
        self._process_metadata: Dict[int, dict] = {}
    
    def register_process(self, pid: int, process_type: str, metadata: dict = None):
        """Register a managed process."""
        with self._lock:
            if process_type == "python":
                self._python_pids.add(pid)
            elif process_type == "cmd":
                self._cmd_pids.add(pid)
            
            self._process_metadata[pid] = {
                "type": process_type,
                "registered_at": time.time(),
                **(metadata or {})
            }
    
    def kill_all_registered(self) -> int:
        """Emergency kill all registered processes."""
        killed = 0
        with self._lock:
            all_pids = list(self._python_pids | self._cmd_pids)
        
        for pid in all_pids:
            try:
                psutil.Process(pid).kill()
                killed += 1
            except Exception:
                pass
        
        return killed
```

#### Enhancement 2: Startup Safety Checks
**File:** `src/api/webui_process_manager.py`

```python
def start(self) -> subprocess.Popen:
    """Start WebUI with pre-flight safety checks."""
    
    # SAFETY CHECK 1: Detect existing WebUI processes
    existing_webui_pids = self._find_existing_webui_processes()
    if len(existing_webui_pids) > 2:  # Allow 1-2 legitimate processes
        logger.error(
            f"Found {len(existing_webui_pids)} existing WebUI processes! "
            "Refusing to start new process. Kill existing processes first."
        )
        raise RuntimeError("Too many existing WebUI processes detected")
    
    # SAFETY CHECK 2: Verify no runaway CMD parents
    existing_cmd_parents = self._find_webui_cmd_parents()
    if len(existing_cmd_parents) > 1:
        logger.warning(
            f"Found {len(existing_cmd_parents)} CMD parents. Cleaning up before start..."
        )
        self._cleanup_cmd_parents(existing_cmd_parents)
    
    # ... rest of existing start() logic
```

### 3.3 Long-Term Architecture

#### Architectural Change 1: Process Isolation
- Move WebUI into containerized environment (Docker/WSL)
- Process tree isolation prevents zombie accumulation
- StableNew communicates via API only, never spawns WebUI directly

#### Architectural Change 2: Process Supervision
- Integrate with `supervisor` or Windows Service Manager
- External watchdog monitors process count
- Auto-cleanup when thresholds exceeded

#### Architectural Change 3: Telemetry & Alerts
- Real-time process count monitoring dashboard
- Alert when process count exceeds thresholds
- Automatic diagnostic bundle creation

---

## 4. Testing & Validation

### 4.1 Zombie Detection Test
```python
# tests/process_lifecycle/test_zombie_detection.py

def test_detect_zombie_cmd_parents():
    """Verify CMD parents are detected and killed."""
    # 1. Start WebUI via batch file
    # 2. Verify CMD parent PID tracked
    # 3. Call stop_webui()
    # 4. Verify CMD parent killed
    # 5. Verify no orphaned CMD processes
```

### 4.2 Restart Stability Test
```python
def test_restart_doesnt_accumulate_processes():
    """Verify restart doesn't leave zombies."""
    initial_count = count_webui_processes()
    
    for i in range(10):
        manager.restart_webui()
        time.sleep(2)
    
    final_count = count_webui_processes()
    assert final_count <= initial_count + 2  # Allow some variance
```

### 4.3 Emergency Cleanup Test
```python
def test_runaway_process_emergency_cleanup():
    """Simulate runaway spawning and verify cleanup."""
    # 1. Spawn 20 WebUI processes manually
    # 2. Trigger watchdog check
    # 3. Verify emergency cleanup activated
    # 4. Verify process count reduced to < 3
```

---

## 5. Documentation Requirements

### 5.1 Code Comments
Every process spawn point MUST have comment block:
```python
# PROCESS LIFECYCLE: This creates a subprocess
# Parent tracking: YES/NO
# Cleanup handled by: [method name]
# Known risks: [description]
```

### 5.2 Architecture Docs
Update:
- `ARCHITECTURE_v2.6.md` - Add Process Lifecycle section
- `DEBUG HUB v2.6.md` - Add "Zombie Processes" troubleshooting
- `KNOWN_PITFALLS_QUEUE_TESTING.md` - Document process cleanup pitfalls

### 5.3 Runbooks
Create:
- `docs/runbooks/ZOMBIE_PROCESS_RECOVERY.md` - Step-by-step cleanup guide
- `docs/runbooks/PROCESS_AUDIT_CHECKLIST.md` - Pre-release process audit

---

## 6. Monitoring & Alerting

### 6.1 Metrics to Track
- `stablenew.processes.python.count` - Python process count
- `stablenew.processes.cmd.count` - CMD process count
- `stablenew.processes.webui_restarts` - Restart frequency
- `stablenew.processes.orphaned_detected` - Orphan detection events

### 6.2 Alert Thresholds
- **WARNING:** Python count > 5 OR CMD count > 2
- **CRITICAL:** Python count > 10 OR CMD count > 3
- **EMERGENCY:** Process count doubles in < 5 minutes

---

## 7. Prevention Checklist

Before releasing ANY changes that spawn processes:

- [ ] Process spawn tracked in registry
- [ ] Parent PID (CMD/shell) tracked
- [ ] Cleanup method explicitly tested
- [ ] Shutdown sequence includes cleanup
- [ ] Restart logic cleans up before spawning
- [ ] Emergency cleanup tested
- [ ] Documentation updated
- [ ] Runaway detection threshold configured

---

## 8. Incident Response

### If Zombie Processes Detected:

1. **IMMEDIATE:** Kill all processes:
   ```powershell
   Get-Process python, cmd | Where-Object {$cmdline = (Get-CimInstance Win32_Process -Filter "ProcessId = $($_.Id)").CommandLine; $cmdline -like "*webui*" -or $cmdline -like "*launch*"} | Stop-Process -Force
   ```

2. **Investigate:** Check logs for:
   - Last WebUI restart timestamp
   - Process spawn events
   - Any auto-restart triggers

3. **Root Cause:** Determine what triggered spawning loop

4. **Fix:** Apply appropriate fix from Section 3

5. **Document:** Update this file with new findings

---

## 9. Version History

| Version | Date | Changes | Author |
|---------|------|---------|--------|
| 1.0 | 2025-12-25 | Initial documentation after 3rd zombie incident | GitHub Copilot |

---

## 10. References

- **Process Management Best Practices:** https://docs.python.org/3/library/subprocess.html
- **Windows Process Creation Flags:** https://learn.microsoft.com/en-us/windows/win32/procthread/process-creation-flags
- **PSUtil Process Management:** https://psutil.readthedocs.io/en/latest/#processes

---

**END OF DOCUMENT**
