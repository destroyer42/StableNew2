# Matrix Filename Collision Fix - Runner Layer

**Issue**: All matrix-expanded jobs were overwriting each other  
**Status**: ✅ FIXED (Runner Layer)  
**Date**: December 20, 2025  
**Related PR**: PR-GUI-003-C (Matrix Runtime Integration)

---

## Problem Summary

When running a pack with matrix expansion enabled (e.g., 4 matrix combinations × 2 batch_size = 8 images expected), all images were overwriting each other, resulting in only 2 final images instead of 8.

**Symptoms**:
- Expected: 8 unique images  
- Actual: 2 images (only batch0 and batch1 survived)
- All matrix variants used identical filenames: `txt2img_p00_00_batch0.png`, `txt2img_p00_00_batch1.png`
- Matrix expansion WAS working (8 NJRs created with unique `matrix_slot_values`)
- Prompt randomization WAS working (different prompts per variant)
- BUT: Runner ignored matrix values when generating output filenames

---

## Root Cause

The runner (`pipeline_runner.py`) was constructing filenames **without considering matrix slot values**:

```python
# BEFORE (WRONG):
image_name = f"{stage.stage_name}_p{prompt_row:02d}_{stage.variant_id:02d}"
# Result: "txt2img_p00_00" for ALL matrix variants → overwrites!
```

Even though:
1. ✅ Matrix expansion created 8 NJRs correctly
2. ✅ Each NJR had unique `matrix_slot_values` (`{"job": "wizard", "environment": "forest"}`)
3. ✅ Prompts were correctly randomized per matrix combination
4. ❌ **Runner completely ignored `matrix_slot_values` when building filenames**

---

## Why Previous Fix Didn't Work

**Previous Attempt** (earlier in session): Added `_build_output_settings_for_matrix()` method to `prompt_pack_job_builder.py` that generated `OutputSettings` with matrix-aware `filename_template`.

**Why it Failed**: The `OutputSettings.filename_template` (e.g., `"{seed}_wizard_forest"`) was **never actually used** by the runner. The runner has its own hardcoded filename construction logic that completely ignores `OutputSettings`.

**Correct Approach**: Must fix the runner's filename construction code directly.

---

## Solution

Modified `pipeline_runner.py` to include matrix slot values in the filename for **all pipeline stages** (txt2img, adetailer, upscale):

### txt2img Stage (Lines 186-202)

```python
# Build filename with matrix slot values if present to prevent overwrites
base_name = f"{stage.stage_name}_p{prompt_row:02d}_{stage.variant_id:02d}"
if hasattr(njr, 'matrix_slot_values') and njr.matrix_slot_values:
    # Add matrix suffix: e.g., "txt2img_p00_00_wizard_forest"
    matrix_suffix = "_".join(str(v).replace(" ", "_") for v in njr.matrix_slot_values.values())
    image_name = f"{base_name}_{matrix_suffix}"
else:
    image_name = base_name

# Result for matrix variant {"job": "wizard", "environment": "forest"}:
# "txt2img_p00_00_wizard_forest"
```

### adetailer Stage (Lines 245-258)

```python
# Build base name with matrix suffix if present
base_name = f"{stage.stage_name}_p{prompt_row:02d}_{stage.variant_id:02d}"
if hasattr(njr, 'matrix_slot_values') and njr.matrix_slot_values:
    matrix_suffix = "_".join(str(v).replace(" ", "_") for v in njr.matrix_slot_values.values())
    base_name = f"{base_name}_{matrix_suffix}"

# Then add image index for batch processing
for img_idx, input_path in enumerate(current_stage_paths):
    image_name = f"{base_name}_img{img_idx:02d}"
    # Result: "adetailer_p00_00_wizard_forest_img00"
```

### upscale Stage (Lines 288-301)

Same approach as adetailer, ensuring consistent naming throughout the pipeline.

---

## Expected Results

### Without Matrix
```
txt2img_p00_00_batch0.png
txt2img_p00_00_batch1.png
```

### With Matrix (4 combinations × 2 batch_size = 8 images)
```
txt2img_p00_00_wizard_forest_batch0.png
txt2img_p00_00_wizard_forest_batch1.png
txt2img_p00_00_wizard_castle_batch0.png
txt2img_p00_00_wizard_castle_batch1.png
txt2img_p00_00_knight_forest_batch0.png
txt2img_p00_00_knight_forest_batch1.png
txt2img_p00_00_knight_castle_batch0.png
txt2img_p00_00_knight_castle_batch1.png
```

### Multi-Stage Pipeline with Matrix
```
# txt2img outputs:
txt2img_p00_00_wizard_forest_batch0.png
txt2img_p00_00_wizard_forest_batch1.png

# adetailer outputs (processes both txt2img images):
adetailer_p00_00_wizard_forest_img00.png
adetailer_p00_00_wizard_forest_img01.png

# upscale outputs (processes both adetailer images):
upscale_p00_00_wizard_forest_img00.png
upscale_p00_00_wizard_forest_img01.png
```

---

## Files Modified

**src/pipeline/pipeline_runner.py** (3 sections):

1. **Lines 186-202**: txt2img stage - Added matrix suffix to base filename
2. **Lines 245-258**: adetailer stage - Added matrix suffix before `_img{idx}`
3. **Lines 288-301**: upscale stage - Added matrix suffix before `_img{idx}`

All three stages now check for `njr.matrix_slot_values` and incorporate values into filenames when present.

---

## Architecture Insight

The system has **two separate filename systems**:

1. **Job Builder Layer** (`OutputSettings.filename_template`)
   - Created during job building in `prompt_pack_job_builder.py`
   - Contains template like `"{seed}_wizard_forest"`
   - **NOT USED** by runner in v2.6 architecture

2. **Runner Layer** (hardcoded string formatting in `pipeline_runner.py`)
   - Constructs actual output filenames
   - Uses pattern like `f"{stage_name}_p{row:02d}_{variant:02d}"`
   - **This is what actually determines output filenames**

**Lesson**: Must fix issues at the **execution layer** (runner), not the planning layer (job builder).

---

## Why This Matters

### Two-Layer Filename System is Confusing

The existence of `OutputSettings.filename_template` suggests it's used for filename generation, but in reality it's completely ignored by the runner. This created a "false positive" fix earlier in the session.

### Future Architectural Improvement

Consider refactoring to **actually use** `OutputSettings.filename_template` in the runner, eliminating the duplicate filename construction logic. This would:
- Make the system more maintainable
- Prevent this class of bugs
- Allow centralized filename configuration
- Enable custom filename patterns per job

---

## Testing

### Manual Verification

1. Create pack with matrix enabled (2 slots: job, environment)
2. Set matrix limit = 4 (creates 4 combinations)
3. Set batch_size = 2 (2 images per combination)
4. Run pipeline with txt2img enabled
5. Check output directory:
   - ✅ Should have 8 unique PNG files
   - ✅ Filenames include matrix values (e.g., `_wizard_forest_`)
   - ✅ NO overwrites (all 8 files present)

### Integration Test

Run multi-stage pipeline (txt2img → adetailer → upscale) with matrix:
- ✅ Each stage maintains unique filenames per matrix variant
- ✅ Stage chains work correctly (adetailer processes txt2img outputs)
- ✅ All manifest files created correctly (one per output image)

---

## Related Issues

Fixed in same session:
- **Matrix Config Loading Bug**: `get_matrix_slots_dict()` accessing wrong JSON path
- **Stage Flag Corruption**: Sidebar `stage_states` had wrong defaults

All three bugs were interconnected and discovered through systematic debugging.

---

## Lessons Learned

### Bug Diagnosis Process

1. User reported: "images still being overwritten"
2. Examined actual output directory: Only 2 files instead of 8
3. Looked at filenames: `txt2img_p00_00_batch0.png` (no matrix values!)
4. Traced filename generation: Found runner ignoring `matrix_slot_values`
5. Applied fix at execution layer (runner, not job builder)

### Testing Best Practices

- Always check actual output files, not just test assertions
- Verify filename uniqueness explicitly when testing batch/matrix features
- Test the full pipeline (planning + execution), not just unit tests

### Architecture Awareness

- Understand the difference between planning layer (job builder) and execution layer (runner)
- Fix issues at the correct layer (where the actual behavior happens)
- Be suspicious of "unused" data fields (like `OutputSettings.filename_template`)

---

## Summary

Fixed matrix filename collision bug by modifying the runner to include `matrix_slot_values` in output filenames for all pipeline stages. Previous fix attempted to solve the problem at the job builder layer by setting `OutputSettings.filename_template`, but this field is not actually used by the runner in v2.6 architecture. The correct fix requires modifying the runner's filename construction code directly.
