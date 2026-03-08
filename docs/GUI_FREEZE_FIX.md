# GUI Freeze Bug Fix - Add to Queue Button

**Date**: December 25, 2025  
**Branch**: cooking  
**Status**: FIXED

## Problem

The "Add to Queue" button was causing the GUI to freeze completely:
- GUI would hang/spin when button clicked
- Only 3 jobs would be added before freeze
- Jobs wouldn't run even with auto-run enabled
- GUI became unresponsive and required force-close

## Root Causes Identified

### 1. Synchronous Queue Submission on GUI Thread
The `on_add_to_queue()` method in `app_controller.py` was executing synchronously on the main GUI thread, blocking the UI during job submission.

### 2. GUI State Updates from Background Thread
After submitting jobs, `enqueue_draft_jobs()` was calling GUI-modifying methods (`clear_job_draft()` and `refresh_preview_from_state()`) from the background thread, causing Tkinter threading violations.

### 3. Excessive Queue Update Emissions
For each job submitted, `_emit_queue_updated()` was being called, formatting ALL jobs in the queue. For 80 jobs, this created 1+2+3+...+80 = 3,240 formatting operations and event emissions.

## Solutions Implemented

### 1. Async Queue Submission (app_controller.py)

**File**: `src/controller/app_controller.py`

Modified `on_add_to_queue()` to:
- Dispatch work to background thread immediately
- Add duplicate request protection via `_queue_submit_in_progress` flag
- Return control to GUI thread immediately (non-blocking)

Created `_enqueue_draft_jobs_async()` to:
- Execute `submit_preview_jobs_to_queue()` on background thread
- Dispatch GUI state updates (`clear_job_draft()`, `refresh_preview_from_state()`) back to main thread via `_run_in_gui_thread()`
- Handle errors gracefully and always clear the in-progress flag

### 2. Batch Mode for Queue Updates (job_service.py)

**File**: `src/controller/job_service.py`

Added `_batch_mode` flag that:
- Suppresses per-job queue update emissions when enabled
- Prevents per-job notifications during batch submission
- Defers runner start check until batch complete

Updated methods:
- `enqueue()`: Check batch mode before emitting updates
- `submit_queued()`: Skip per-job notifications and runner checks in batch mode

### 3. Batch Submission in Pipeline Controller (pipeline_controller.py)

**File**: `src/controller/pipeline_controller.py`

Modified `_submit_normalized_jobs()` to:
- Enable batch mode when submitting multiple jobs (>1)
- Submit all jobs without per-job emissions
- Emit single queue update after all jobs submitted
- Start runner once after batch (if auto-run enabled)
- Always disable batch mode in finally block

## Performance Impact

**Before**:
- 80 jobs → 3,240 format operations + 80 event emissions + 80 GUI callbacks
- All blocking on GUI thread
- Result: Complete GUI freeze

**After**:
- 80 jobs → 80 format operations + 1 event emission + 1 GUI callback
- Background thread for submission
- GUI updates marshaled to main thread
- Result: Responsive GUI throughout

## Files Modified

1. `src/controller/app_controller.py`
   - `on_add_to_queue()`: Made async with threading
   - `_enqueue_draft_jobs_async()`: New background worker
   - GUI state updates properly marshaled to main thread

2. `src/controller/job_service.py`
   - Added `_batch_mode` flag
   - Updated `enqueue()` to respect batch mode
   - Updated `submit_queued()` to defer notifications/runner start in batch mode

3. `src/controller/pipeline_controller.py`
   - Updated `_submit_normalized_jobs()` to use batch mode
   - Single queue update after batch
   - Runner started once after all jobs submitted

4. `tests/controller/test_controller_event_api_v2.py`
   - Updated test to wait for background thread completion

## Testing

### Manual Testing
1. Start StableNew GUI
2. Build a preview with 80+ jobs
3. Click "Add to Queue"
4. Verify: GUI remains responsive
5. Verify: All jobs added to queue
6. Verify: Jobs run if auto-run enabled

### Automated Testing
Run: `python tests/controller/test_queue_freeze_fix.py`

Expected: `on_add_to_queue()` returns in < 100ms

## Architectural Alignment

This fix maintains v2.6 architectural principles:
- ✅ NormalizedJobRecord is the sole execution payload
- ✅ No PipelineConfig enters execution
- ✅ Background work stays on background threads
- ✅ GUI updates marshaled to main thread via `_run_in_gui_thread()`
- ✅ Event emissions batched for performance
- ✅ Follows existing patterns (similar to `on_add_to_queue_clicked`)

## Migration Notes

- No API changes - `on_add_to_queue()` signature unchanged
- Behavior is now async - tests must wait for completion
- Batch mode is internal - no external API exposure needed
- Backward compatible - single job submission still works

## Related Issues

This fix resolves the GUI freeze regression introduced in recent queue refactoring PRs (likely CORE1 series that unified queue submission paths).
