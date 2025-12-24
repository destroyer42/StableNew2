# Critical Bugfixes - Dec 23, 2025

## Issues Identified by Codex

### Issue #1: Missing `is_acquired()` Method - CONFIRMED ✅

**Problem:**
`SingleInstanceLock` class did not have an `is_acquired()` method, but two critical shutdown paths tried to call it:

1. **main.py finally block** (line 490):
```python
finally:
    if single_instance_lock.is_acquired():  # ❌ AttributeError!
        single_instance_lock.release()
```

2. **graceful_exit.py** (line 34):
```python
if single_instance_lock and single_instance_lock.is_acquired():  # ❌ AttributeError!
    try:
        single_instance_lock.release()
    except Exception:
        pass
```

**Impact:**
- Any run that reached the finally clause would throw `AttributeError`
- Lock would never be released on shutdown
- Cleanup paths completely broken
- Lock file/port would leak, preventing future app starts

**Root Cause:**
The method was never implemented when `SingleInstanceLock` was created, but callers assumed it existed.

### Issue #2: Reprocessing Guard Logic Flaw - CONFIRMED ✅

**Problem:**
In [pipeline_runner.py](src/pipeline/pipeline_runner.py), lines 131-136 had flawed logic:

```python
# OLD BROKEN LOGIC:
for stage in plan.jobs:
    # REPROCESSING: Skip stages before start_stage
    if start_stage and stage.stage_name != start_stage and not current_stage_paths:
        # Haven't reached start_stage yet and no output from prev stages
        continue
    if start_stage and stage.stage_name == start_stage:
        # Reached start_stage, clear the flag so we don't skip subsequent stages
        start_stage = None
```

**The Flaw:**
When `input_image_paths` is provided (line 125):
```python
current_stage_paths = list(input_images)  # Now NOT empty!
```

So the guard condition `not current_stage_paths` is **False**, meaning pre-start stages are **NOT skipped**!

**Impact:**
- Reprocessing jobs would regenerate images instead of using provided inputs
- txt2img/img2img stages would run before adetailer/upscale
- Defeating the entire purpose of reprocessing
- User's 160 existing images would be thrown away and regenerated

**Example Failure:**
```
User: "Reprocess these 160 images starting from adetailer stage"
Expected: Use 160 existing images → adetailer → upscale
Actual: txt2img (generates new images!) → img2img → adetailer → upscale
```

## Solutions Implemented

### Fix #1: Add `is_acquired()` Method

**File:** [src/utils/single_instance.py](src/utils/single_instance.py)

Added the missing method after `acquire()`:
```python
def is_acquired(self) -> bool:
    """Check if this instance currently holds the lock.
    
    Returns:
        True if the lock is currently held by this instance, False otherwise
    """
    return self._socket is not None
```

Also fixed `release()` to properly clean up:
```python
def release(self) -> None:
    """Release the lock so another instance can start."""
    
    # Stop accept thread first
    self._stop_accepting.set()
    if self._accept_thread and self._accept_thread.is_alive():
        self._accept_thread.join(timeout=2.0)
    
    # Close and clear the socket
    if self._socket is not None:
        try:
            self._socket.close()
        except Exception:
            pass
        self._socket = None
    
    self._accept_thread = None
```

**Result:**
- ✅ Shutdown paths work correctly
- ✅ Lock properly released on exit
- ✅ No AttributeError on shutdown
- ✅ `is_acquired()` returns False after `release()`

### Fix #2: Reprocessing Guard Logic

**File:** [src/pipeline/pipeline_runner.py](src/pipeline/pipeline_runner.py)

Completely rewrote the guard logic to use a state flag:

```python
# NEW CORRECT LOGIC:
# Track whether we've reached the start_stage (for reprocessing mode)
reached_start_stage = (start_stage is None)  # If no start_stage, begin immediately

for stage in plan.jobs:
    # REPROCESSING: Skip stages before start_stage
    if not reached_start_stage:
        if stage.stage_name == start_stage:
            # We've reached the start stage, process this and all subsequent stages
            reached_start_stage = True
        else:
            # Skip this stage - we haven't reached start_stage yet
            logger.info(f"⏭️  [REPROCESS] Skipping stage '{stage.stage_name}' (before start_stage '{start_stage}')")
            continue
```

**Key Improvements:**
1. **Independent of `current_stage_paths`**: Guard logic no longer depends on whether paths exist
2. **State-based**: Uses `reached_start_stage` flag to track progress
3. **Clear semantics**: Skip until start_stage is reached, then process all subsequent stages
4. **Proper logging**: Shows which stages are skipped and why

**Result:**
- ✅ Pre-start stages properly skipped regardless of `current_stage_paths`
- ✅ Reprocessing uses provided images, doesn't regenerate
- ✅ Works correctly for all start_stage values (img2img, adetailer, upscale)
- ✅ Normal mode (no start_stage) processes all stages

## Testing

Created [test_critical_bugfixes.py](test_critical_bugfixes.py) with comprehensive tests:

### Test Results:
```
Testing SingleInstanceLock.is_acquired()...
------------------------------------------------------------
1. Before acquire():
   ✓ is_acquired() returns False

2. After acquire():
   ✓ is_acquired() returns True

3. After release():
   ✓ is_acquired() returns False

✅ SingleInstanceLock.is_acquired() method works correctly!

Testing reprocessing guard logic...
------------------------------------------------------------

1. Reprocessing with start_stage='adetailer':
   Skipped: ['txt2img', 'img2img']
   Processed: ['adetailer', 'upscale']
   ✓ Correctly skipped pre-start stages

2. Normal mode (no start_stage):
   Skipped: []
   Processed: ['txt2img', 'img2img', 'adetailer', 'upscale']
   ✓ All stages processed when no start_stage

3. Reprocessing with start_stage='img2img':
   Skipped: ['txt2img']
   Processed: ['img2img', 'adetailer', 'upscale']
   ✓ Correctly skipped txt2img only

✅ Reprocessing guard logic works correctly!

🎉 ALL TESTS PASSED - Both critical bugs are fixed!
```

## Files Modified

1. **src/utils/single_instance.py**
   - Added `is_acquired()` method (returns `self._socket is not None`)
   - Fixed `release()` to properly clean up socket and set to `None`

2. **src/pipeline/pipeline_runner.py**
   - Replaced flawed guard logic (lines 120-136)
   - Added `reached_start_stage` flag
   - Independent of `current_stage_paths` state
   - Clear skip logging with emoji

## Impact Assessment

### Before Fixes:
- ❌ App would crash on shutdown with AttributeError
- ❌ Lock would leak, preventing restart
- ❌ Reprocessing would regenerate images instead of using provided ones
- ❌ 160 images → regenerate all → waste compute/time

### After Fixes:
- ✅ Clean shutdown with proper lock release
- ✅ No AttributeError on exit paths
- ✅ Reprocessing correctly uses provided images
- ✅ 160 images → adetailer → upscale (as intended)
- ✅ Proper stage skipping with logging

## Architecture Compliance

Both fixes maintain full v2.6 architecture compliance:
- ✅ No PipelineConfig usage
- ✅ NormalizedJobRecord-only execution
- ✅ Clean shutdown paths
- ✅ Proper reprocessing semantics
- ✅ State management via flags, not mutations

## Verification Steps

1. **Test shutdown paths:**
   ```bash
   python -m src.main
   # Close GUI normally
   # Check logs - should see no AttributeError
   ```

2. **Test reprocessing:**
   ```python
   # Select 160 images
   # Set start_stage="adetailer"
   # Click "Reprocess Images"
   # Check logs - should see:
   #   "⏭️  [REPROCESS] Skipping stage 'txt2img'"
   #   "⏭️  [REPROCESS] Skipping stage 'img2img'"
   #   "Running stage: adetailer"
   ```

3. **Run tests:**
   ```bash
   python test_critical_bugfixes.py
   # Should show all green checkmarks
   ```

## Credit

Issues identified by: **Codex** (code reviewer agent)  
Fixes implemented by: **GitHub Copilot**  
Verification: Automated tests + manual review

---

**Status:** ✅ Both critical bugs confirmed and fixed  
**Testing:** ✅ All automated tests passing  
**Ready for:** Production deployment
