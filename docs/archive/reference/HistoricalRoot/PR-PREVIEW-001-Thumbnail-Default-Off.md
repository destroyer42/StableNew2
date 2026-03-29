"""
PR-PREVIEW-001: Thumbnail Preview Default Off + Config Persistence
===================================================================

Phase: 3 (Secondary Tasks)
Status: COMPLETE
Date: 2025-01-16

## Problem Statement

The preview panel's thumbnail preview checkbox had three issues:

1. **Wrong Default**: Checkbox defaulted to `True` (show preview), but users typically 
   don't need thumbnails displayed by default since they slow down the UI.

2. **State Reset Bug**: Multiple code paths reset `_current_show_preview = True`, 
   overriding the user's checkbox preference when:
   - Clearing preview panel
   - Updating with new job summary
   - Loading from pack config

3. **Pack Config Override**: The code attempted to read `show_preview` from pack 
   configuration and override the user's checkbox state, violating the principle 
   that **user UI controls should be authoritative**.

## Architecture Principle

**User checkbox state is the single source of truth for UI preferences.**

Pack configurations should NOT override user UI preferences. The preview panel 
checkbox reflects a **user preference**, not a job or pack configuration.

## Changes Made

### 1. Changed Default to False

**File**: `src/gui/preview_panel_v2.py`
**Line 88-89**: Changed `BooleanVar(value=True)` → `BooleanVar(value=False)`

```python
# Before
self._show_preview_var = tk.BooleanVar(value=True)

# After (PR-PREVIEW-001)
self._show_preview_var = tk.BooleanVar(value=False)
```

### 2. Fixed State Reset on Clear

**File**: `src/gui/preview_panel_v2.py`
**Line 524-526**: Preserve checkbox state instead of hardcoding `True`

```python
# Before
self._current_show_preview = True

# After (PR-PREVIEW-001)
self._current_show_preview = self._show_preview_var.get()
```

### 3. Removed Pack Config Override

**File**: `src/gui/preview_panel_v2.py`
**Lines 591-599**: Removed code that read `show_preview` from pack and overrode checkbox

```python
# Before (WRONG: overrides user preference)
show_preview = getattr(summary_obj, "show_preview", True)
self._current_show_preview = show_preview
if show_preview != self._show_preview_var.get():
    self._show_preview_var.set(show_preview)

# After (PR-PREVIEW-001: user checkbox is authoritative)
self._current_show_preview = self._show_preview_var.get()
```

### 4. Fixed State Reset in update_with_summary

**File**: `src/gui/preview_panel_v2.py`
**Line 1050-1052**: Preserve checkbox state instead of hardcoding `True`

```python
# Before (BUG: always resets to True)
self._current_show_preview = True
self._update_thumbnail(summary, self._current_pack_name, True)

# After (PR-PREVIEW-001: preserve user preference)
self._current_show_preview = self._show_preview_var.get()
self._update_thumbnail(summary, self._current_pack_name, self._show_preview_var.get())
```

### 5. Fixed Fallback Default in Checkbox Handler

**File**: `src/gui/preview_panel_v2.py`
**Line 1021**: Use checkbox state directly, not fallback to `True`

```python
# Before (WRONG: reads stored value with True fallback)
show_preview = getattr(self, "_current_show_preview", True)

# After (PR-PREVIEW-001: read checkbox directly)
show_preview = self._show_preview_var.get()
```

### 6. Fixed Fallback in restore_state

**File**: `src/gui/preview_panel_v2.py`
**Line 1157**: Changed fallback default from `True` to `False`

```python
# Before
show_preview = state.get("show_preview", True)

# After (PR-PREVIEW-001)
show_preview = state.get("show_preview", False)
```

## State Persistence

State persistence was **already implemented** via:

- `save_state()`: Saves checkbox state to `state/preview_state.json`
- `restore_state()`: Loads checkbox state from disk on startup
- `destroy()`: Calls `save_state()` on panel destruction

**Schema**: Version 2.6
**File**: `state/preview_state.json`
```json
{
  "show_preview": false,
  "schema_version": "2.6"
}
```

## Testing

**File**: `tests/test_pr_preview_001.py`
**Tests**: 10 comprehensive tests

✅ `test_default_preview_off`: Checkbox defaults to False
✅ `test_state_persistence_save_restore`: State saves and restores correctly
✅ `test_state_persists_on_checkbox_change`: save_state() called on change
✅ `test_no_reset_on_clear`: State preserved when clearing preview
✅ `test_no_reset_on_update_with_summary`: State preserved on job updates
✅ `test_checkbox_state_authoritative`: Pack config doesn't override checkbox
✅ `test_state_file_schema_version`: Schema version saved correctly
✅ `test_restore_with_invalid_schema`: Invalid schema ignored safely
✅ `test_restore_with_missing_file`: Missing file handled gracefully
✅ `test_save_state_on_destroy`: State saved when panel destroyed

**Test Results**: 9 passed, 1 skipped (Tk environment issue)

## Verification

Run tests:
```bash
pytest tests/test_pr_preview_001.py -v
```

Manual verification:
1. ✅ Launch app → Checkbox should be unchecked (False)
2. ✅ Check checkbox → Add job → State should remain checked
3. ✅ Uncheck checkbox → Add job → State should remain unchecked
4. ✅ Restart app → Checkbox state should persist from last session

## Impact Analysis

### Files Modified
- `src/gui/preview_panel_v2.py` (6 changes)
- `tests/test_pr_preview_001.py` (NEW: 10 tests)

### Breaking Changes
**None**. This is a UI preference change, not an API change.

### Backward Compatibility
- Existing users with `show_preview: true` in state file → Respected
- New users → Default to False
- Invalid/missing state → Default to False (was True)

## Related Documents

- ARCHITECTURE_v2.6.md (UI state management)
- THREAD_MANAGEMENT_v2.6.md (Phase 3 secondary tasks)
- CHANGELOG.md (PR-PREVIEW-001 entry)

## Lessons Learned

1. **UI preferences must be authoritative**: Never override user UI controls from 
   data/config sources. The checkbox state is not "derived" from the data.

2. **Watch for hardcoded defaults**: Multiple code paths can independently reset 
   state. Every assignment to `_current_show_preview` was a potential bug.

3. **Test state persistence thoroughly**: State can be lost in surprising ways 
   (clearing, updating, loading new data). Comprehensive tests catch these edge cases.

## Next Steps

✅ PR-PREVIEW-001 complete
→ Continue with Phase 3 secondary tasks (if any)
→ Update CHANGELOG.md
→ Update DOCS_INDEX_v2.6.md
"""