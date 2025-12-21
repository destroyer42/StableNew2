# Verification Checklist - Matrix & Stage Flag Fixes

**Status**: Fixes Applied, Awaiting Manual Verification  
**Date**: 2025  

---

## Quick Summary

Three bugs fixed in this session:
1. ✅ Matrix config not loading from pack_data section → FIXED
2. ✅ Matrix filenames colliding (all using `{seed}.png`) → FIXED
3. ✅ Stage flags corrupting (adetailer → img2img) → FIXED

All code changes applied. Now need to verify fixes work in live GUI.

---

## Verification Steps

### 1. Stage Flag Persistence Test ⏳

**Purpose**: Verify sidebar default fix resolved stage flag corruption

**Steps**:
1. Restart GUI (to load new sidebar defaults)
2. Open Pipeline Tab
3. Enable **adetailer** checkbox ONLY
4. Disable img2img, upscale (leave txt2img enabled)
5. Click **"Apply Config"** button
6. Click **"Load Config"** button
7. Check checkboxes

**Expected Result**:
- ✅ txt2img: ENABLED
- ✅ img2img: DISABLED (was incorrectly enabling before)
- ✅ adetailer: ENABLED (was incorrectly disabling before)
- ✅ upscale: DISABLED

**Check Saved JSON**:
```json
{
  "pipeline": {
    "txt2img_enabled": true,
    "img2img_enabled": false,    // Must be false!
    "adetailer_enabled": true,   // Must be true!
    "upscale_enabled": false
  }
}
```

**Status**: ⏳ PENDING - Requires GUI restart

---

### 2. Matrix Expansion Test ⏳

**Purpose**: Verify matrix config loading and NJR generation

**Setup**:
- Use existing pack with matrix enabled
- Matrix limit = 4
- Batch size = 1

**Steps**:
1. Open Pipeline Tab
2. Load pack with matrix
3. Click "Add to Job"
4. Check Preview Panel

**Expected Result**:
- ✅ Preview shows 4 NJRs (one per matrix combination)
- ✅ Each NJR has different `matrix_slot_values`
- ✅ Job count = 4 (not 0)

**Status**: ⏳ PENDING - Requires pack with matrix

---

### 3. Matrix Filename Uniqueness Test ⏳ → ✅ CODE FIXED

**Purpose**: Verify filename collision fix prevents overwrites

**IMPORTANT**: Previous fix was incomplete - it modified the job builder layer but the runner was ignoring those settings. The REAL fix is now in place: modified `pipeline_runner.py` to incorporate matrix slot values directly into filename construction.

**Setup**:
- Pack with matrix enabled (2 slots: job=[wizard, knight], environment=[forest, castle])
- Matrix limit = 4
- Batch size = 2 (creates 2 images per prompt)
- Seed = 12345 (fixed seed)

**Steps**:
1. Load pack with matrix
2. Add to Queue
3. Run job
4. Check output directory

**Expected Result**:
- ✅ 8 unique PNG files (4 matrix combos × 2 batch_size)
- ✅ Filenames include matrix values:
  - `txt2img_p00_00_wizard_forest_batch0.png`
  - `txt2img_p00_00_wizard_forest_batch1.png`
  - `txt2img_p00_00_wizard_castle_batch0.png`
  - `txt2img_p00_00_wizard_castle_batch1.png`
  - `txt2img_p00_00_knight_forest_batch0.png`
  - `txt2img_p00_00_knight_forest_batch1.png`
  - `txt2img_p00_00_knight_castle_batch0.png`
  - `txt2img_p00_00_knight_castle_batch1.png`
- ✅ NO files overwritten

**Check Manifest Files**:
- ✅ 8 txt2img manifests (one per image)
- ✅ Each manifest has unique filename in `output_paths`

**Code Changes Applied**:
- ✅ `src/pipeline/pipeline_runner.py` lines 186-202 (txt2img)
- ✅ `src/pipeline/pipeline_runner.py` lines 245-258 (adetailer)
- ✅ `src/pipeline/pipeline_runner.py` lines 288-301 (upscale)

**Status**: ⏳ CODE COMPLETE - Awaiting manual verification

---

### 4. Multi-Stage Matrix Run Test ⏳

**Purpose**: Verify stage flags work correctly with matrix expansion

**Setup**:
- Pack with matrix enabled (limit=2)
- Enable: txt2img + adetailer + upscale
- Batch size = 1

**Steps**:
1. Load pack
2. Enable txt2img, adetailer, upscale checkboxes
3. Apply config
4. Add to Queue and run
5. Check output directory and manifests

**Expected Result**:
- ✅ 2 txt2img images (unique filenames with matrix values)
- ✅ 2 adetailer images (processed from txt2img outputs)
- ✅ 2 upscale images (processed from adetailer outputs)
- ✅ Total: 6 images across 3 stages
- ✅ Manifest files show correct stage chain: txt2img → adetailer → upscale

**Check Stage Execution**:
```
outputs/
├── 12345_wizard_forest.png         (txt2img)
├── 12345_wizard_castle.png         (txt2img)
├── 12345_wizard_forest_ad.png      (adetailer)
├── 12345_wizard_castle_ad.png      (adetailer)
├── 12345_wizard_forest_ad_up.png   (upscale)
└── 12345_wizard_castle_ad_up.png   (upscale)
```

**Status**: ⏳ PENDING - Requires full pipeline run

---

## Code Changes Summary

### Files Modified

1. **src/utils/prompt_pack_utils.py**
   - Lines 52-77: Fixed `get_matrix_slots_dict()` to access `pack_data.matrix`
   - Lines 79-99: Fixed `get_matrix_config_summary()` to access `pack_data.matrix`

2. **src/pipeline/prompt_pack_job_builder.py**
   - Lines 108-120: Fixed matrix limit extraction
   - Lines 406-445: Added `_build_output_settings_for_matrix()` method
   - Line 170: Changed to call `_build_output_settings_for_matrix()`

3. **src/gui/sidebar_panel_v2.py**
   - Lines 143-150: Fixed `stage_states` initialization defaults
   - Changed: `img2img: False`, `upscale: False`, `adetailer: False`

### Tests Created

1. **test_matrix_config_loading.py** - Matrix expansion unit tests
2. **test_matrix_filenames.py** - Filename uniqueness tests
3. **test_pack_config_flags.py** - Stage flag persistence tests (existing)

### Documentation Created

1. **docs/MATRIX_FILENAME_FIX.md** - Technical deep-dive
2. **docs/MATRIX_AND_STAGE_FIXES_SESSION.md** - Session summary
3. **VERIFICATION_CHECKLIST.md** - This document
4. **CHANGELOG.md** - Updated with all fixes

---

## Known Issues (Pre-Fix)

### Issue 1: Matrix Not Expanding ✅ FIXED
- **Symptom**: 0 NJRs created instead of 8
- **Root Cause**: Wrong JSON path (`metadata["matrix"]` vs `metadata["pack_data"]["matrix"]`)
- **Fix**: Updated 2 files to access correct path

### Issue 2: Filename Collisions ✅ FIXED
- **Symptom**: All matrix variants overwrite each other (all use `12345.png`)
- **Root Cause**: All NJRs shared same `OutputSettings` with template `{seed}`
- **Fix**: Added method to append matrix values to filename template

### Issue 3: Stage Flag Corruption ✅ FIXED
- **Symptom**: adetailer enabled → save → img2img becomes enabled instead
- **Root Cause**: Sidebar `stage_states` initialized with wrong defaults (`img2img: True`, `upscale: True`)
- **Fix**: Corrected sidebar initialization defaults

---

## What Changed vs What Didn't

### Changed ✅
- Matrix config extraction now works
- Matrix variants get unique filenames
- Stage flags persist correctly
- Sidebar defaults match expected behavior

### Didn't Change ❌
- JSON structure (still `{pack_data: {...}, preset_data: {...}}`)
- Matrix expansion algorithm (still Cartesian product with limit)
- Stage flag storage locations (still 3 places: sidebar, pipeline_tab, JSON)
- Filename template syntax (still uses `{seed}`, just adds suffix)

---

## Rollback Plan (If Needed)

If fixes cause issues:

1. **Revert sidebar defaults**:
   ```python
   # In src/gui/sidebar_panel_v2.py line 146-147
   "img2img": tk.BooleanVar(value=True),   # Revert to old default
   "upscale": tk.BooleanVar(value=True),   # Revert to old default
   ```

2. **Revert matrix filename enhancement**:
   ```python
   # In src/pipeline/prompt_pack_job_builder.py line 170
   output_settings=OutputSettings()  # Revert to old code
   ```

3. **Revert matrix config path**:
   ```python
   # In src/utils/prompt_pack_utils.py line 62
   matrix_config = metadata.get("matrix", {})  # Revert to old path
   ```

But these fixes should be safe - they address clear bugs without changing core architecture.

---

## Success Criteria

All fixes considered successful when:

- ✅ Stage flags persist through save/load cycle (no adetailer → img2img flip)
- ✅ Matrix expansion creates correct number of NJRs (not 0)
- ✅ Matrix filenames are unique (no overwrites)
- ✅ Manifest files show correct stage execution
- ✅ All existing tests still pass
- ✅ No regressions in non-matrix packs

---

## Next Actions

1. **Restart GUI** - Load new sidebar defaults
2. **Run Verification Test 1** - Stage flag persistence
3. **Run Verification Test 2** - Matrix expansion
4. **Run Verification Test 3** - Filename uniqueness
5. **Run Verification Test 4** - Multi-stage matrix run
6. **Report Results** - Update this checklist with outcomes

---

## Contact Info

If issues arise:
- Check `logs/` directory for error messages
- Review `runs/<job_id>/run_metadata.json` for job details
- Check `outputs/` directory for actual files created
- Examine manifest JSON files for stage execution data

All fixes follow StableNew v2.6 architecture and coding standards.
