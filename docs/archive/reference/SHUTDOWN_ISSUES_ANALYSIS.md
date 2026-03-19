# Shutdown Issue Analysis & Fixes

**Date**: 2025-12-25  
**Issues**: SingleInstanceLock thread timeout, Shutdown watchdog false alarm

---

## Issue 1: SingleInstanceLock-Accept Thread Not Shutting Down

### Root Cause

**File**: `src/utils/single_instance.py` line 119

The `_accept_loop()` thread checks `self._stop_accepting` flag but uses a 1-second socket timeout. When `release()` is called, it only waits 2.0 seconds for the thread to join (line 119), but the thread might be blocked in `accept()` for up to 1 second before checking the stop flag.

**Timeline**:
1. `release()` called, sets `_stop_accepting` flag
2. Thread may be in middle of 1-second `accept()` timeout
3. `join(timeout=2.0)` waits maximum 2 seconds
4. If thread takes 2+ seconds to notice flag → timeout
5. Thread abandoned (but will eventually exit on its own)

### Why It's Mostly Harmless

The thread **will** exit cleanly on its own once it checks the flag (within 1 second). It's just that the 2-second join timeout is too aggressive given the 1-second socket timeout.

### Fix

Increase join timeout from 2.0s to 3.0s (allows 3 full check cycles):

```python
# src/utils/single_instance.py line 119
self._accept_thread.join(timeout=3.0)  # Was 2.0
```

---

## Issue 2: Shutdown Watchdog False Alarm

### Root Cause

**File**: `src/controller/app_controller.py` line 3041

The shutdown watchdog spawns a separate thread that sleeps for 8 seconds, then checks if `_shutdown_completed` flag is set. The problem:

1. Watchdog thread spawned at start of shutdown
2. Sleeps for 8 seconds
3. Wakes up and checks `_shutdown_completed`
4. If not set → logs ERROR (even if shutdown is still in progress normally)

**Current shutdown time**: ~8+ seconds due to:
- WebUI shutdown (variable time)
- Thread joins (10 second timeout)
- Single instance lock thread timeout (2→10 seconds)
- History store writer shutdown
- Learning hooks shutdown

### Why It Triggers

The 8-second watchdog timeout is too short for normal shutdown. Typical shutdown takes:
- SingleInstanceLock thread join: 2-3 seconds
- Other thread joins: 1-5 seconds
- WebUI shutdown: 0-2 seconds
- Total: ~5-10 seconds

So the watchdog often triggers even for normal shutdowns.

### Why It's Mostly Harmless

The watchdog only logs an ERROR. It doesn't force exit unless `STABLENEW_HARD_EXIT_ON_SHUTDOWN_HANG=1` is set (which it isn't by default). So it's just a noisy warning.

### Fix Option 1: Increase Watchdog Timeout

```python
# src/controller/app_controller.py line 3204
timeout = float(os.environ.get("STABLENEW_SHUTDOWN_WATCHDOG_DELAY", "15"))  # Was 8
```

This gives 15 seconds for normal shutdown before alarming.

### Fix Option 2: Disable Watchdog Thread Entirely

The watchdog was useful during Phase 1-2 development to catch shutdown hangs, but now that shutdown is stable, it may not be needed. The `STABLENEW_HARD_EXIT_ON_SHUTDOWN_HANG` env var provides a manual override if needed.

**Recommendation**: Increase timeout to 15 seconds (Option 1) to reduce false alarms while keeping the safety net for genuine hangs.

---

## Summary of Actions

### Required Fixes

1. **SingleInstanceLock thread timeout**:
   - Increase `join(timeout=2.0)` to `join(timeout=3.0)`
   - File: `src/utils/single_instance.py` line 119

2. **Shutdown watchdog false alarm**:
   - Increase default timeout from 8s to 15s
   - File: `src/controller/app_controller.py` line 3204

### Optional Improvements

3. **Better logging**:
   - Change watchdog ERROR to WARNING if shutdown is still in progress
   - Only ERROR if shutdown genuinely hung (> 30 seconds)

4. **Shutdown progress tracking**:
   - Log which step shutdown is on when watchdog triggers
   - Helps diagnose actual hangs vs slow-but-normal shutdown

---

## Risk Assessment

**Issue Severity**: LOW

**Impact**:
- ✅ No data loss
- ✅ No resource leaks (threads exit cleanly)
- ✅ No user-facing errors (just log noise)
- ⚠️ Slightly delayed shutdown (1-2 seconds)
- ⚠️ Confusing ERROR logs

**User Impact**: Minimal. Shutdown completes successfully, just takes 8-10 seconds instead of 5-6 seconds.

---

## Testing

After fixes, verify:
1. Shutdown completes without ERROR logs
2. No thread timeout warnings
3. Shutdown time: 5-8 seconds (reasonable)
4. All threads join cleanly

---

## Implementation

See PR below for actual code changes.
