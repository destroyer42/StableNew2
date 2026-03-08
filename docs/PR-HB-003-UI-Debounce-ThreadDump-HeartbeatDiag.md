# PR-HB-003 — UI Update Debounce + Working Thread Dump + Heartbeat Tick Diagnostic

**Status:** ✅ COMPLETE  
**Date:** January 2, 2026  
**Tracking:** Fixes WebUI connection freeze (PR-HB-002 follow-up)

## Intent

Prevent heartbeat stalls by debouncing/coalescing UI updates (preview/jobs/history) into a single periodic UI tick.

Make "ui_heartbeat_stall" bundles actionable by fixing thread dump capture and adding an explicit heartbeat log line with the current operation label.

## Changes Made

### 1. UI Update Debouncing System ✅

**File:** `src/controller/app_controller.py`

Added debouncing infrastructure to prevent rapid UI updates from blocking heartbeat:

- **New fields:**
  - `_ui_preview_dirty`: Flag for pending preview refresh
  - `_ui_job_list_dirty`: Flag for pending job list refresh
  - `_ui_history_dirty`: Flag for pending history refresh
  - `_ui_debounce_pending`: Flag to prevent multiple timers
  - `_ui_debounce_delay_ms`: Coalescing window (150ms)

- **New methods:**
  - `_mark_ui_dirty(preview, jobs, history)`: Mark components needing refresh
  - `_schedule_debounced_ui_update()`: Schedule timer-based refresh
  - `_apply_pending_ui_updates()`: Central sink for coalesced updates

**Behavior:**
- Multiple rapid `_mark_ui_dirty()` calls within 150ms → single `_apply_pending_ui_updates()`
- Prevents preview refresh storms from blocking heartbeat
- Updates `last_ui_heartbeat_ts` during each apply

### 2. Replace Direct Refresh Calls ✅

**File:** `src/controller/app_controller.py`

Changed `on_pipeline_add_packs_to_job()` to use debounced refresh:

**Before:**
```python
self._refresh_preview_from_state_async()
```

**After:**
```python
self._mark_ui_dirty(preview=True)
```

This coalesces rapid pack additions into a single preview refresh.

### 3. Fixed Thread Dump Capture ✅

**File:** `src/utils/diagnostics_bundle_v2.py`

**Issues Fixed:**
- ❌ Old code tried to access `frame.f_code` on `FrameSummary` objects
- ❌ Thread dump failure could crash bundle creation

**New Implementation:**
- ✅ Uses `sys._current_frames()` for real frame objects
- ✅ Uses `traceback.format_stack(frame)` for text dump
- ✅ Uses `traceback.extract_stack(frame)` for structured JSON
- ✅ Maps thread IDs to names via `threading.enumerate()`
- ✅ Wraps capture in try/except - never prevents bundle creation
- ✅ Writes both `metadata/thread_dump.txt` and `metadata/thread_dump.json`

**JSON Structure:**
```json
{
  "<thread_id>": {
    "thread_id": 12345,
    "name": "MainThread",
    "daemon": false,
    "alive": true,
    "stack_frames": [
      {
        "filename": "app_controller.py",
        "lineno": 4850,
        "function": "on_pipeline_add_packs_to_job",
        "line": "entries.append(entry)"
      }
    ]
  }
}
```

### 4. Heartbeat Tick Diagnostic ✅

**File:** `src/gui/main_window_v2.py`

Enhanced `_install_ui_heartbeat()` to log diagnostics:

- Logs every 20 ticks (5 seconds at 250ms interval)
- Logs immediately when `current_operation_label` changes
- Format: `[UI] heartbeat tick #<count> op=<operation_or_idle>`

**Example Logs:**
```
[UI] heartbeat tick #20 op=idle
[UI] heartbeat tick #23 op=Adding 5 pack(s) to job
[UI] heartbeat tick #40 op=Adding 5 pack(s) to job
[UI] heartbeat tick #45 op=idle
```

### 5. Watchdog Context Improvements ✅

**File:** `src/services/watchdog_system_v2.py`

Added comprehensive stall context fields:

- `ui_age_s`: Explicit age of last UI heartbeat (seconds)
- `ui_heartbeat_age_s`: Legacy field (kept for compatibility)
- `current_operation_label`: Operation in progress when stall occurred
- `last_ui_action`: Last UI action taken
- `ui_stall_threshold_s`: Threshold that triggered stall (30s)
- `last_ui_heartbeat_ts`: Timestamp of last heartbeat

**Example Context:**
```json
{
  "ui_age_s": 35.2,
  "current_operation_label": "Adding 5 pack(s) to job",
  "last_ui_action": "on_pipeline_add_packs_to_job(['pack1', 'pack2', 'pack3'])",
  "ui_stall_threshold_s": 30.0,
  "watchdog_reason": "ui_heartbeat_stall"
}
```

## Tests Added

### Test 1: UI Debounce ✅
**File:** `tests/gui/test_ui_debounce.py`

- ✅ `test_debounce_coalesces_multiple_calls`: Rapid marks → single apply
- ✅ `test_dirty_flags_cleared_after_apply`: Flags reset properly
- ✅ `test_multiple_dirty_types_handled`: Preview/jobs/history all work
- ✅ `test_debounce_updates_heartbeat_timestamp`: Timestamp advances
- ✅ `test_debounce_handles_exceptions_gracefully`: Errors don't crash

### Test 2: Thread Dump ✅
**File:** `tests/utils/test_diagnostics_thread_dump.py`

- ✅ `test_thread_dump_files_exist_in_bundle`: Both .txt and .json present
- ✅ `test_thread_dump_contains_mainthread_stack`: MainThread included
- ✅ `test_thread_dump_json_structure`: Correct field structure
- ✅ `test_thread_dump_failure_does_not_prevent_bundle`: Error resilience
- ✅ `test_capture_thread_dump_directly`: Direct function test

### Test 3: Watchdog Context ✅
**File:** `tests/services/test_watchdog_ui_stall_context.py`

- ✅ `test_watchdog_includes_ui_age_s`: Field present and correct
- ✅ `test_watchdog_includes_current_operation_label`: Operation tracked
- ✅ `test_watchdog_includes_ui_stall_threshold_s`: Threshold included
- ✅ `test_watchdog_context_comprehensive`: All fields present

## Architecture Impact

### Debouncing Flow
```
UI Event → _mark_ui_dirty(preview=True)
          ↓
    Schedule timer (150ms)
          ↓
    _apply_pending_ui_updates()
          ↓
    _refresh_preview_from_state()
          ↓
    Update last_ui_heartbeat_ts
```

### Thread Dump Flow
```
Stall Detected → build_diagnostics_bundle()
                 ↓
          _capture_thread_dump()
                 ↓
        sys._current_frames()
                 ↓
        threading.enumerate() (names)
                 ↓
        traceback.format_stack() (text)
                 ↓
        traceback.extract_stack() (JSON)
                 ↓
        Write thread_dump.txt + thread_dump.json
```

## Scope Boundaries (Enforced)

✅ No changes to PromptPack sourcing  
✅ No changes to Runner purity  
✅ Only touched controller/UI glue + diagnostics  
✅ No forbidden file modifications

## Rollback Plan

To revert PR-HB-003:

1. **Remove debouncing:**
   - Delete `_mark_ui_dirty()`, `_schedule_debounced_ui_update()`, `_apply_pending_ui_updates()`
   - Delete debouncing fields from `__init__`
   - Restore `self._refresh_preview_from_state_async()` in `on_pipeline_add_packs_to_job()`

2. **Revert thread dump:**
   - Restore old `_capture_thread_dump()` (before PR-HB-003 marker)
   - Remove try/except wrapper in bundle creation

3. **Remove heartbeat logging:**
   - Restore simple `_install_ui_heartbeat()` without logging

4. **Revert watchdog context:**
   - Remove `ui_age_s` field (keep legacy `ui_heartbeat_age_s`)

5. **Delete tests:**
   - `tests/gui/test_ui_debounce.py`
   - `tests/utils/test_diagnostics_thread_dump.py`
   - `tests/services/test_watchdog_ui_stall_context.py`

## Verification

### Manual Testing
1. **Debouncing:**
   - Add 10 packs rapidly → only 1 preview refresh visible
   - GUI remains responsive during bulk operations

2. **Thread Dump:**
   - Trigger stall → bundle contains `thread_dump.txt` with MainThread stack
   - Check `thread_dump.json` has correct structure

3. **Heartbeat:**
   - Monitor logs → see `[UI] heartbeat tick` messages every 5 seconds
   - Perform operation → see operation label in logs

4. **Watchdog:**
   - Trigger stall → bundle metadata includes `ui_age_s`, `current_operation_label`, `ui_stall_threshold_s`

### Automated Testing
```bash
pytest tests/gui/test_ui_debounce.py -v
pytest tests/utils/test_diagnostics_thread_dump.py -v
pytest tests/services/test_watchdog_ui_stall_context.py -v
```

## Related PRs

- **PR-HB-002:** Async WebUI resource refresh (fixed initial freeze)
- **PR-HB-001:** Initial heartbeat stall detection
- **PR-CORE1-D21A:** Watchdog system wiring

## Success Metrics

✅ **UI Responsiveness:** No heartbeat stalls during pack addition  
✅ **Diagnostic Quality:** Thread dumps include actionable stack traces  
✅ **Operation Visibility:** Logs show what operation was running during stall  
✅ **Bundle Reliability:** Thread dump errors never prevent bundle creation

## Notes

- Debounce delay of 150ms chosen empirically (balance between responsiveness and coalescing)
- Heartbeat logs at 20-tick interval to avoid log spam (5 seconds)
- Operation label changes trigger immediate log for debugging state transitions
- Thread dump JSON format matches industry standard (filename/lineno/function)
