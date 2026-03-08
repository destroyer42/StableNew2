# Thread Management v2.6

**Status**: CANONICAL  
**Phase**: PR-THREAD-001 Implementation Complete  
**Last Updated**: December 25, 2024

---

## 1. Executive Summary

StableNew v2.6 implements **centralized thread lifecycle management** via the ThreadRegistry pattern to eliminate zombie threads and orphaned background processes.

**Key Changes**:
- All background threads MUST use `ThreadRegistry.spawn()` instead of raw `threading.Thread()`
- Daemon threads are **prohibited** except in specific approved cases
- AppController shutdown sequence now includes thread registry cleanup
- Pre-commit hooks enforce thread management guardrails

**Problem Solved**: Prior to v2.6, daemon threads would become zombies after GUI shutdown, continuing to write diagnostic files and consume resources indefinitely.

---

## 2. ThreadRegistry Architecture

### 2.1 Core Components

| Component | Purpose | Location |
|-----------|---------|----------|
| `ThreadRegistry` | Singleton managing all background threads | `src/utils/thread_registry.py` |
| `TrackedThread` | Metadata for each managed thread | `src/utils/thread_registry.py` |
| `get_thread_registry()` | Convenience function to access singleton | `src/utils/thread_registry.py` |
| `shutdown_all_threads()` | Convenience wrapper for shutdown | `src/utils/thread_registry.py` |

### 2.2 ThreadRegistry Class

```python
class ThreadRegistry:
    """
    Singleton managing all background thread lifecycle.
    
    Responsibilities:
    - Spawn threads with metadata tracking
    - Track thread lifecycle (spawned_at, purpose, alive status)
    - Clean shutdown: join all threads with timeout
    - Report orphaned daemon threads
    - Detect shutdown-after-shutdown attempts
    """
```

**Key Methods**:

| Method | Signature | Purpose |
|--------|-----------|---------|
| `spawn()` | `spawn(target, name, args, kwargs, daemon, purpose) -> Thread` | Create and track a thread |
| `shutdown_all()` | `shutdown_all(timeout=10.0) -> dict` | Join all threads with timeout |
| `get_active_threads()` | `get_active_threads() -> list[TrackedThread]` | Get currently tracked threads (auto-cleans dead ones) |
| `unregister()` | `unregister(thread) -> None` | Remove thread from tracking |
| `is_shutdown_requested()` | `is_shutdown_requested() -> bool` | Check if shutdown initiated |
| `dump_status()` | `dump_status() -> str` | Get human-readable thread status |

### 2.3 TrackedThread Dataclass

```python
@dataclass
class TrackedThread:
    thread: threading.Thread
    name: str
    spawned_at: float  # time.monotonic()
    purpose: str = ""
```

---

## 3. Usage Patterns

### 3.1 Spawning Threads (Preferred)

**DO THIS** (v2.6+):

```python
from src.utils.thread_registry import get_thread_registry

registry = get_thread_registry()

def worker_function(arg1, arg2):
    """Background worker."""
    print(f"Processing {arg1}, {arg2}")

thread = registry.spawn(
    target=worker_function,
    args=(val1, val2),
    name="MyWorkerThread",
    daemon=False,  # Explicit, required
    purpose="Processes background tasks for feature X"
)

# Thread is automatically started and tracked
```

**DON'T DO THIS** (deprecated):

```python
# ❌ Raw threading.Thread usage
thread = threading.Thread(target=worker_function, daemon=True)
thread.start()
```

### 3.2 Shutting Down Threads

**AppController Integration**:

```python
def shutdown(self):
    """Enhanced shutdown with thread registry cleanup."""
    logger.info("AppController shutdown initiated...")
    
    # 1. Stop services
    self._stop_watchdog()
    
    # 2. Shutdown thread registry (join all threads)
    from src.utils.thread_registry import shutdown_all_threads
    thread_stats = shutdown_all_threads(timeout=10.0)
    logger.info(f"Thread shutdown: {thread_stats}")
    
    # 3. Close stores
    if self._history_store:
        self._history_store.close()
    
    # 4. Shutdown runner
    self.single_node_runner.stop()
    
    logger.info("AppController shutdown complete")
```

**Shutdown Statistics**:

```python
stats = registry.shutdown_all(timeout=10.0)
# Returns:
# {
#     "total": 5,       # Total threads tracked
#     "joined": 4,      # Successfully joined
#     "timeout": 0,     # Threads that timed out
#     "orphaned": 1,    # Daemon threads still alive
#     "duration": 2.3   # Shutdown duration in seconds
# }
```

### 3.3 Checking Shutdown State

Services should respect shutdown requests:

```python
registry = get_thread_registry()

while not registry.is_shutdown_requested():
    # Do work
    process_batch()
    time.sleep(1.0)
```

### 3.4 Thread Purpose Documentation

Always provide a `purpose` string:

```python
registry.spawn(
    target=scan_processes,
    name="ProcessScanner",
    purpose="Monitors stray Python processes and kills them after 300s idle"
)
```

This helps with debugging and thread lifecycle analysis.

---

## 4. Guardrails & Enforcement

### 4.1 Pre-commit Hooks

Two hooks enforce thread management rules:

| Hook | Script | Purpose |
|------|--------|---------|
| `no-daemon-threads` | `scripts/check_daemon_threads.py` | Blocks commits with `daemon=True` |
| `require-thread-registry` | `scripts/check_thread_registry_usage.py` | Ensures `threading.Thread()` uses ThreadRegistry |

**Installation**:

```bash
pip install pre-commit
pre-commit install
```

**Manual Run**:

```bash
pre-commit run --all-files
```

### 4.2 Exempt Files

Certain files are exempt from guardrails:

```python
EXEMPT_FILES = {
    "src/utils/thread_registry.py",  # ThreadRegistry itself
    "scripts/check_*.py",             # Pre-commit scripts
    "tests/",                         # Test files (for testing thread behavior)
}
```

### 4.3 Approved Daemon Thread Patterns

If a specific daemon thread usage is approved:

```python
# In scripts/check_daemon_threads.py
ALLOWED_DAEMON_PATTERNS = [
    "src/utils/single_instance.py:96",  # Socket listener (approved legacy)
]
```

---

## 5. Migration Checklist

For converting legacy code to ThreadRegistry:

### Step 1: Find Violations

```bash
python scripts/check_daemon_threads.py
```

### Step 2: Convert Each Thread

**Before**:
```python
thread = threading.Thread(target=worker, daemon=True, name="Worker")
thread.start()
```

**After**:
```python
from src.utils.thread_registry import get_thread_registry

registry = get_thread_registry()
thread = registry.spawn(
    target=worker,
    name="Worker",
    daemon=False,
    purpose="Description of what this thread does"
)
```

### Step 3: Add Shutdown Checks

If the thread loops indefinitely, add shutdown checks:

```python
def worker():
    registry = get_thread_registry()
    while not registry.is_shutdown_requested():
        # Do work
        time.sleep(1.0)
```

### Step 4: Update Shutdown Sequence

Ensure `shutdown_all_threads()` is called during app shutdown:

```python
def cleanup():
    from src.utils.thread_registry import shutdown_all_threads
    stats = shutdown_all_threads(timeout=10.0)
    logger.info(f"Threads shut down: {stats}")
```

### Step 5: Test

```bash
pytest tests/utils/test_thread_registry.py -v
pytest tests/integration/test_clean_shutdown.py -v
```

---

## 6. Known Thread Sources

| Module | Threads | Status | Notes |
|--------|---------|--------|-------|
| `AppController` | ProcessAutoScanner, Watchdog | ✅ Migrated | PR-SCANNER-001, PR-WATCHDOG-001 |
| `SingleNodeRunner` | Queue worker thread | ✅ Migrated | PR-SHUTDOWN-001 |
| `SystemWatchdogV2` | Heartbeat monitor | ✅ Migrated | PR-WATCHDOG-001 |
| `DiagnosticsBundleV2` | Async ZIP builder | ✅ Migrated | PR-SHUTDOWN-001 |
| `WebuiProcessManager` | WebUI subprocess monitor | ⚠️ Legacy | Has 4 daemon threads |
| `GUIController` | GUI worker thread | ⚠️ Legacy | Uses daemon threads |
| `ThumbnailWidget` | Image loader thread | ⚠️ Legacy | Daemon thread |
| `SingleInstanceChecker` | Socket listener | ⚠️ Legacy | Daemon thread |

---

## 7. Testing

### 7.1 Unit Tests

**File**: `tests/utils/test_thread_registry.py`

Tests:
- Singleton pattern
- Thread spawning with args/kwargs
- Daemon thread warnings
- Active thread cleanup (dead threads removed)
- Shutdown with timeout
- Orphaned daemon detection
- Shutdown flag behavior

### 7.2 Integration Tests

**File**: `tests/integration/test_clean_shutdown.py`

Tests:
- No orphan threads after shutdown
- Thread count returns to baseline
- No zombie processes
- Daemon threads don't block shutdown
- Idempotent shutdown (safe to call multiple times)
- I/O-bound thread shutdown
- CPU-bound thread shutdown
- Crashed thread cleanup

### 7.3 Running Tests

```bash
# Unit tests
pytest tests/utils/test_thread_registry.py -v

# Integration tests
pytest tests/integration/test_clean_shutdown.py -v

# All thread tests
pytest tests/ -k thread -v
```

---

## 8. Troubleshooting

### 8.1 Thread Won't Shut Down

**Symptom**: `shutdown_all()` reports timeout for a thread.

**Causes**:
1. Thread is blocked on I/O without timeout
2. Thread doesn't check `is_shutdown_requested()`
3. Infinite loop without break condition

**Solution**:
```python
def worker():
    registry = get_thread_registry()
    while not registry.is_shutdown_requested():
        try:
            # I/O with timeout
            data = socket.recv(1024, timeout=1.0)
        except socket.timeout:
            continue  # Check shutdown flag
```

### 8.2 Orphaned Daemon Threads

**Symptom**: `shutdown_all()` reports orphaned daemon threads.

**Solution**: Convert to non-daemon and add shutdown checks (see 8.1).

### 8.3 Pre-commit Hook Failing

**Symptom**: `pre-commit` blocks commit due to daemon threads.

**Solution**:
1. If violation is legitimate, fix the code (see Section 5)
2. If approved, add to `ALLOWED_DAEMON_PATTERNS`

### 8.4 Thread Leaks

**Symptom**: Thread count increases over time.

**Diagnosis**:
```python
registry = get_thread_registry()
print(registry.dump_status())
```

**Solution**:
- Ensure threads exit when work is done
- Call `unregister()` if thread is managed externally
- Check for exception swallowing that keeps threads alive

---

## 9. Performance Considerations

### 9.1 Registry Overhead

**Minimal**:
- ThreadRegistry uses a `threading.Lock()` for thread-safe operations
- Spawning a thread adds ~50 microseconds overhead (negligible)
- `get_active_threads()` auto-cleans dead threads (O(n) where n = tracked threads)

### 9.2 Shutdown Duration

**Factors**:
- Number of threads: more threads = longer shutdown
- Thread join timeout: default 10s per thread (configurable)
- Daemon threads: don't block shutdown

**Optimization**:
- Use shorter timeouts for fast-exiting threads
- Signal threads to stop via `Event()` or `is_shutdown_requested()`
- Avoid long-blocking I/O without timeouts

---

## 10. Future Enhancements

Potential improvements for future versions:

1. **Thread Pooling**: Reuse threads instead of spawning new ones
2. **Thread Priority**: Critical threads vs. background threads
3. **Automatic Timeout Tuning**: Adjust join timeout based on thread history
4. **Thread Health Monitoring**: Alert if thread hasn't checked in
5. **Per-Subsystem Registries**: Separate registries for GUI, runner, services

---

## 11. Related Documents

- [Architecture v2.6](ARCHITECTURE_v2.6.md) - Overall system architecture
- [Governance v2.6](GOVERNANCE_v2.6.md) - PR process and architectural rules
- [Debug Hub v2.6](DEBUG_HUB_v2.6.md) - Diagnostic tools and logging
- [Coding & Testing Standards v2.6](Coding_and_Testing_Standards_v2.6.md) - Code quality rules

---

## 12. Changelog

| Version | Date | Changes |
|---------|------|---------|
| 2.6.0 | Dec 25, 2024 | Initial ThreadRegistry implementation (PR-THREAD-001) |

---

**End of Document**
