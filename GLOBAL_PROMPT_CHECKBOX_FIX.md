# Global Prompt Checkbox Fix - Complete

## Issue
Global positive and global negative prompts were being applied to all txt2img generations, even when their respective checkboxes were unchecked in the GUI.

## Root Cause
1. **Executor was using a single flag**: The executor was reading only `apply_global_negative_txt2img` and using it for both positive and negative prompts
2. **Checkboxes not wired to config**: The GUI had separate checkboxes and getter methods (`get_global_positive_config()` and `get_global_negative_config()`), but these were never called to populate the pipeline config
3. **Default behavior**: Because the flags weren't being set, they defaulted to `True`, causing prompts to always be applied

## Solution

### Part 1: Executor Fix (Previously Completed)
**File**: `src/pipeline/executor.py` (lines 2488-2511)

Changed from single flag to separate flags:
```python
# OLD (broken):
apply_global = config.get("pipeline", {}).get("apply_global_negative_txt2img", True)
# Used same flag for both positive and negative

# NEW (fixed):
apply_global_positive = pipeline_section.get("apply_global_positive_txt2img", True)
apply_global_negative = pipeline_section.get("apply_global_negative_txt2img", True)
# Separate flags for each type
```

### Part 2: Config Wiring (This Fix)
**File**: `src/controller/app_controller.py`

#### Added New Method: `_add_global_prompt_flags()`
Location: After `_collect_current_stage_configs()`, before `_build_config_snapshot_with_override()`

```python
def _add_global_prompt_flags(self, config: dict[str, Any]) -> None:
    """Add global prompt application flags from sidebar checkboxes to config.
    
    Args:
        config: Configuration dict to modify (modifies in-place)
    """
    # Get sidebar reference from main window
    if not self.main_window:
        return
    
    sidebar = getattr(self.main_window, "sidebar_panel_v2", None)
    if not sidebar:
        return
    
    # Get global prompt configurations from sidebar
    try:
        global_positive_config = sidebar.get_global_positive_config()
        global_negative_config = sidebar.get_global_negative_config()
        
        # Add flags to pipeline section
        pipeline_section = config.setdefault("pipeline", {})
        pipeline_section["apply_global_positive_txt2img"] = global_positive_config.get("enabled", False)
        pipeline_section["apply_global_negative_txt2img"] = global_negative_config.get("enabled", True)
        
    except Exception as e:
        # Fallback: if anything goes wrong, default to safe values
        self._append_log(f"[controller] Failed to read global prompt flags: {e}")
        pipeline_section = config.setdefault("pipeline", {})
        pipeline_section.setdefault("apply_global_positive_txt2img", False)
        pipeline_section.setdefault("apply_global_negative_txt2img", True)
```

#### Modified: `_build_config_snapshot_with_override()`
Added calls to `_add_global_prompt_flags()` in both branches:

1. **Override disabled path** (line ~3973):
   ```python
   merged_config = {**base_config, **pack_config}
   # Add global prompt flags from sidebar checkboxes
   self._add_global_prompt_flags(merged_config)  # ← Added
   self._append_log("[controller] Override disabled: using pack config as-is")
   ```

2. **Override enabled path** (line ~3995):
   ```python
   final_config = ConfigMergerV2().merge_pipeline(...)
   
   # Add global prompt flags from sidebar checkboxes
   self._add_global_prompt_flags(final_config)  # ← Added
   
   self._append_log("[controller] Override enabled: merged current stage configs")
   ```

## Data Flow

```
┌─────────────────────────────────────────────────────────────────────────┐
│ GUI (sidebar_panel_v2.py)                                               │
│  ├─ global_positive_enabled_var (BooleanVar)                           │
│  ├─ global_negative_enabled_var (BooleanVar)                           │
│  ├─ get_global_positive_config() → {"enabled": bool, "text": str}      │
│  └─ get_global_negative_config() → {"enabled": bool, "text": str}      │
└─────────────────────────────────────────────────────────────────────────┘
                                    ↓
┌─────────────────────────────────────────────────────────────────────────┐
│ Controller (app_controller.py)                                          │
│  ├─ _add_global_prompt_flags(config)                                   │
│  │   ├─ Gets sidebar reference                                          │
│  │   ├─ Calls get_global_positive_config()                             │
│  │   ├─ Calls get_global_negative_config()                             │
│  │   └─ Sets flags in config["pipeline"]:                              │
│  │       ├─ apply_global_positive_txt2img = enabled                    │
│  │       └─ apply_global_negative_txt2img = enabled                    │
│  └─ _build_config_snapshot_with_override()                             │
│      └─ Calls _add_global_prompt_flags() on final config               │
└─────────────────────────────────────────────────────────────────────────┘
                                    ↓
┌─────────────────────────────────────────────────────────────────────────┐
│ Config Dict                                                             │
│  {                                                                      │
│    "pipeline": {                                                        │
│      "apply_global_positive_txt2img": bool,  ← From checkbox            │
│      "apply_global_negative_txt2img": bool   ← From checkbox            │
│    }                                                                    │
│  }                                                                      │
└─────────────────────────────────────────────────────────────────────────┘
                                    ↓
┌─────────────────────────────────────────────────────────────────────────┐
│ Executor (executor.py)                                                  │
│  ├─ run_txt2img_stage(config)                                          │
│  │   ├─ Reads apply_global_positive_txt2img                            │
│  │   ├─ Reads apply_global_negative_txt2img                            │
│  │   ├─ _merge_stage_positive(..., apply_global_positive)              │
│  │   └─ _merge_stage_negative(..., apply_global_negative)              │
│  └─ Result: Prompts only applied if checkbox enabled                   │
└─────────────────────────────────────────────────────────────────────────┘
```

## Test Results

All 4 checkbox combinations tested and verified:

| Positive Checkbox | Negative Checkbox | Config Flags Set Correctly |
|-------------------|-------------------|----------------------------|
| ✅ ON             | ✅ ON             | ✅ Both True               |
| ❌ OFF            | ❌ OFF            | ✅ Both False              |
| ✅ ON             | ❌ OFF            | ✅ True, False             |
| ❌ OFF            | ✅ ON             | ✅ False, True             |

## Files Modified

1. **src/controller/app_controller.py**
   - Added `_add_global_prompt_flags()` method
   - Modified `_build_config_snapshot_with_override()` to call new method

2. **src/pipeline/executor.py** (Previously fixed)
   - Changed to use separate `apply_global_positive_txt2img` and `apply_global_negative_txt2img` flags

## Verification Commands

```bash
# Run verification test
python test_checkbox_fix.py

# Validate syntax
python -m py_compile src/controller/app_controller.py
python -m py_compile src/pipeline/executor.py
```

## User-Visible Behavior

**Before Fix:**
- Global positive prompt: ALWAYS prepended (e.g., "masterpiece, best quality, ...")
- Global negative prompt: ALWAYS appended (e.g., "low quality, worst quality, nsfw, ...")
- Checkboxes had no effect

**After Fix:**
- Global positive prompt: Only prepended when checkbox is ✅ CHECKED
- Global negative prompt: Only appended when checkbox is ✅ CHECKED
- Checkboxes now control prompt application as expected

## Default Checkbox States
(From `src/gui/sidebar_panel_v2.py`, lines 201, 203):
- `global_positive_enabled_var`: Default = `False` (OFF)
- `global_negative_enabled_var`: Default = `True` (ON)

This means by default:
- No global positive terms added (user must opt-in)
- Global negative terms added (safety/NSFW prevention active by default)

---

**Status**: ✅ Complete and Tested
**Date**: 2024-12-22
