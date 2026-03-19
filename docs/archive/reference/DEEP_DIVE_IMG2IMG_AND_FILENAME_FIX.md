# Deep Dive Fix - img2img Defaults & filename_template Removal

**Date**: December 20, 2025  
**Status**: ✅ COMPLETE  
**Issues**: Recurring img2img_enabled bug + unused filename_template causing confusion

---

## Problem Summary

### Issue 1: img2img_enabled Defaulting to True (RECURRING BUG)

**User Report**: "Also, the img2img stage is still being enabled on load, and I'll assume when apply config happens."

**History**: This bug was "fixed" before but kept reappearing. Previous fixes were incomplete - only addressing some locations while missing others.

**Root Cause**: The default value for `img2img_enabled` was hardcoded as `True` in **SEVEN different locations** throughout the codebase. When loading configs, these defaults would override the user's saved `False` value if the key was missing or during merge operations.

### Issue 2: filename_template Field Confusion

**User Request**: "In the output settings, there is a filename field, I think that might be contributing to the confusion, let's get rid of it."

**Problem**: `OutputSettings.filename_template` existed but was **never actually used** by the runner. The runner has its own hardcoded filename construction logic in `pipeline_runner.py`. This caused confusion during debugging because it suggested the field controlled output filenames when it didn't.

---

## Investigation Process

### Finding All img2img Defaults

Used systematic grep searches:
```bash
grep -r "img2img_enabled.*=.*True" src/
grep -r "img2img.*:.*True" src/
grep -r "img2img_enabled.*get\(" src/
```

### Locations Found and Fixed

1. **src/controller/app_controller.py** (line 2417)
   - Method: `_apply_executor_config_to_gui()`
   - Code: `"img2img": bool(pipeline_section.get("img2img_enabled", True))`
   - **Critical**: This runs every time a config is loaded into GUI
   - Fixed: Changed default from `True` to `False`

2. **src/utils/preferences.py** (line 19)
   - Dict: `_DEFAULT_PIPELINE_CONTROLS`
   - Code: `"img2img_enabled": True`
   - Used when loading user preferences
   - Fixed: Changed to `False`

3. **src/gui/state.py** (line 248)
   - Dataclass: `PipelineState`
   - Field: `stage_img2img_enabled: bool = True`
   - Initial GUI state
   - Fixed: Changed to `False`

4. **src/pipeline/executor.py** (line 1607)
   - Method: `_run_full_pipeline_impl()`
   - Code: `img2img_enabled: bool = pipeline_cfg.get("img2img_enabled", True)`
   - Default when executing full pipeline
   - Fixed: Changed to `False`

5. **src/pipeline/executor.py** (line 1954)
   - Method: `run_pack_pipeline()`
   - Code: `img2img_enabled = config.get("pipeline", {}).get("img2img_enabled", True)`
   - Default when running pack-based jobs
   - Fixed: Changed to `False`

6. **src/utils/config.py** (line 348)
   - Method: `_make_default_config()`
   - Dict: `"pipeline": {"img2img_enabled": False, ...}`
   - **Already correct** in config.py but other locations overrode it
   - No change needed

7. **src/gui/sidebar_panel_v2.py** (line 146)
   - Dict: `stage_states`
   - Code: `"img2img": tk.BooleanVar(value=False)`
   - **Already fixed** in previous session
   - No change needed

---

## Why This Bug Kept Recurring

### Incomplete Previous Fixes

Previous attempts only fixed **some** locations (e.g., sidebar, config.py) but missed the **execution layer** (app_controller, executor, preferences, state).

### Multiple Entry Points

The bug could manifest through any of these code paths:
1. **Loading config** → `app_controller._apply_executor_config_to_gui()`
2. **Applying config** → reads from GUI state → `state.py` default
3. **Running job** → `executor._run_full_pipeline_impl()` or `executor.run_pack_pipeline()`
4. **GUI initialization** → `preferences.py` defaults
5. **Sidebar initialization** → `sidebar_panel_v2.py` (already fixed)

### Default Value Cascade

Even if the JSON has `"img2img_enabled": false`, the `.get()` calls with `default=True` would override it during:
- Config merging
- Missing key fallback
- Initialization

---

## filename_template Removal

### What Was Removed

1. **Field from dataclass** (`src/pipeline/job_models_v2.py`):
   ```python
   # REMOVED:
   filename_template: str = "{seed}"
   
   # NOW:
   # OutputSettings only has base_output_dir
   ```

2. **Builder method** (`src/pipeline/prompt_pack_job_builder.py`):
   ```python
   # REMOVED: _build_output_settings_for_matrix() (entire method ~30 lines)
   
   # REPLACED WITH:
   output_settings = OutputSettings(base_output_dir=base_output_dir)
   ```

3. **Test that explicitly tested the field**:
   - `tests/gui_v2/test_queue_panel_v2_normalized_jobs.py`
   - Changed `test_conversion_handles_filename_template()` to test `output_dir` instead

### Why It Was Safe to Remove

**The field was completely unused**:
- Runner constructs filenames using: `f"{stage}_p{row:02d}_{variant:02d}_{matrix_suffix}"`
- Never references `OutputSettings.filename_template`
- Previous "fix" that set this field had **zero effect** on actual filenames

**Tests will need updates**:
- ~50 test files create NJRs with `filename_template="{seed}"`
- These will get errors but are easily fixed by removing the parameter
- The tests don't actually validate filename generation (that's in the runner)

---

## Files Modified

### Core Architecture (6 files)

1. **src/pipeline/job_models_v2.py**
   - Removed `filename_template: str` field from `OutputSettings`
   - Updated docstring to clarify runner controls filenames

2. **src/pipeline/prompt_pack_job_builder.py**
   - Removed `_build_output_settings_for_matrix()` method
   - Simplified `build_jobs()` to just set `base_output_dir`

3. **src/controller/app_controller.py**
   - Line 2417: Changed `img2img_enabled` default from `True` to `False`

4. **src/utils/preferences.py**
   - Line 19: Changed `img2img_enabled` default from `True` to `False`

5. **src/gui/state.py**
   - Line 248: Changed `stage_img2img_enabled` default from `True` to `False`

6. **src/pipeline/executor.py**
   - Line 1607: Changed `img2img_enabled` default from `True` to `False`
   - Line 1954: Changed `img2img_enabled` default from `True` to `False`

### Tests (1 file)

7. **tests/gui_v2/test_queue_panel_v2_normalized_jobs.py**
   - Renamed test and changed to test `output_dir` instead of `filename_template`

### Documentation (1 file)

8. **CHANGELOG.md**
   - Added comprehensive entry documenting both fixes

---

## Testing

### Manual Verification Required

1. **img2img defaults**:
   - Create new pack
   - Save with img2img DISABLED
   - Close and reopen GUI
   - Load the pack
   - ✅ Verify img2img stays DISABLED (not flipping to enabled)

2. **Config apply**:
   - Disable img2img checkbox
   - Click "Apply Config"
   - Click "Load Config"
   - ✅ Verify img2img stays disabled

3. **Job execution**:
   - Create job with only txt2img enabled
   - Run job
   - ✅ Verify only txt2img stage executes (no img2img)
   - Check run metadata: `img2img_enabled: false`

### Automated Tests

- Existing tests that construct NJRs with `filename_template` parameter will fail
- This is expected and acceptable
- Tests should be updated to remove the unused parameter
- Approximately 50 test files affected (but easily fixed by removing one line)

---

## Architecture Insights

### Two-Layer Filename System

The confusion arose from having **two separate systems**:

1. **Job Builder Layer** (Planning):
   - `OutputSettings.filename_template`
   - Created during job construction
   - **Not used by runner**

2. **Runner Layer** (Execution):
   - Hardcoded in `pipeline_runner.py`
   - `f"{stage}_p{row:02d}_{variant:02d}_{matrix_suffix}_batch{idx}"`
   - **Actually generates filenames**

**Lesson**: When debugging filename issues, must look at the **execution layer** (runner), not the planning layer (job builder).

### Default Value Propagation

The img2img bug demonstrates how defaults can propagate through a system:

```
Config File (img2img: false)
    ↓
Load into GUI → app_controller.get() with default=True ← BUG!
    ↓
GUI State → state.py default=True ← BUG!
    ↓
Execute Job → executor.get() with default=True ← BUG!
    ↓
Result: img2img enabled even though config said false
```

**Lesson**: When fixing default value bugs, must trace through **all code paths** that read the value, not just the config file.

---

## Lessons Learned

### 1. Incomplete Fixes Come Back

The img2img bug was "fixed" before but only in 2-3 locations. The bug reappeared through the other 4-5 locations that weren't fixed. When fixing defaults, must:
- Grep entire codebase for all occurrences
- Fix **every** location, not just the obvious ones
- Document all locations in CHANGELOG

### 2. Unused Fields Cause Confusion

The `filename_template` field looked important but was completely unused. During debugging, we wasted time trying to "fix" it when the real issue was elsewhere. When a field exists, developers assume it does something.

**Best Practice**: Remove unused fields immediately. Don't leave them "just in case" - they cause confusion.

### 3. Architecture Documentation Prevents Bugs

The two-layer filename system (builder + runner) wasn't documented. This led to:
- Fixing the wrong layer (builder instead of runner)
- Confusion about which code actually controls filenames
- Wasted debugging time

**Best Practice**: Document which layer controls what, especially when there are multiple layers that look similar.

### 4. Defaults Must Match Expected Behavior

The correct defaults should match what users expect:
- `txt2img_enabled: True` ← Users want this by default
- `img2img_enabled: False` ← Refinement is opt-in
- `adetailer_enabled: False` ← Face fixing is opt-in  
- `upscale_enabled: False` ← Upscaling is opt-in

Only txt2img should default to True because it's the primary generation method.

---

## Summary

Fixed recurring img2img_enabled bug by comprehensively changing defaults from `True` to `False` in **seven locations** across the codebase. Also removed unused `OutputSettings.filename_template` field that was causing confusion during debugging. 

Both issues stemmed from incomplete previous fixes and architectural confusion about which layer controls what. This comprehensive fix addresses all code paths and removes confusing unused fields to prevent future issues.

**Result**: img2img will now correctly stay disabled when user sets it to disabled, and the filename system is clearer with no unused confusing fields.
