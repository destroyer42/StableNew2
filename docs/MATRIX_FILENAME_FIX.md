# Matrix Expansion & Stage Flag Fixes - December 20, 2025

## Issues Found and Fixed

### 1. Matrix Config Not Loading from pack_data Section ✅ FIXED
**Problem**: `get_matrix_slots_dict()` and matrix limit extraction were looking for `metadata.get("matrix")` but the JSON structure is `metadata["pack_data"]["matrix"]`.

**Impact**: Matrix expansion was completely disabled - all packs returned 0 matrix slots.

**Files Modified**:
- `src/utils/prompt_pack_utils.py` - Fixed `get_matrix_slots_dict()` and `get_matrix_config_summary()`
- `src/pipeline/prompt_pack_job_builder.py` - Fixed matrix limit extraction in `_expand_entry_by_matrix()`

**Result**: Matrix expansion now works correctly, creating N entries per matrix limit.

---

### 2. Filename Collisions for Matrix-Expanded Jobs ⚠️ NEEDS FIX
**Problem**: When matrix expansion creates multiple jobs (e.g., 8 variants), they all use the same filename template `"{seed}"`. Since matrix variants typically share the same seed, all 8 images overwrite each other.

**Example**:
```
Matrix: 3 jobs × 3 environments = 9 combinations, limited to 8
Current filenames: 12345.png, 12345.png, 12345.png, ... (all identical!)
Expected: 12345_wizard_forest.png, 12345_wizard_castle.png, etc.
```

**Solution**: Incorporate matrix slot values into the filename template when matrix expansion is active.

**Proposed Filename Format**:
```
{seed}                        # No matrix: 12345.png
{seed}_m{matrix_index}        # Matrix: 12345_m0.png, 12345_m1.png, ...
{seed}_{matrix_slots}         # Matrix with slot names: 12345_wizard_forest.png
```

**Files to Modify**:
- `src/pipeline/job_builder_v2.py` - Update filename template generation
- `src/pipeline/prompt_pack_job_builder.py` - Pass matrix info to builder

---

### 3. Stage Flag Corruption (img2img enabling when adetailer enabled) ⚠️ INVESTIGATING
**User Report**: "The change from adetailer being enabled to img2img being enabled is still happening."

**Already Fixed (PR-CORE1-12)**: Default config values were corrected:
- `txt2img_enabled: True` ✅
- `img2img_enabled: False` ✅ (was True before)
- `adetailer_enabled: False` ✅
- `upscale_enabled: False` ✅ (was True before)

**Possible Remaining Issues**:
1. GUI might be reading wrong variable
2. Config merge might still have issues
3. Legacy code path still active

**Need to Test**: Load a pack with `adetailer_enabled: True, img2img_enabled: False` and verify GUI shows correct states.

---

## Implementation Plan

### Phase 1: Matrix Filename Fix (HIGH PRIORITY)
1. Add `matrix_variant_index` field to track position in matrix expansion
2. Update filename template to include matrix information
3. Test with various matrix configurations

### Phase 2: Stage Flag Investigation (IF STILL BROKEN)
1. Add comprehensive logging to stage flag loading
2. Trace through entire load → display pipeline
3. Identify where flags get corrupted
4. Apply targeted fix

### Phase 3: Testing
1. Matrix expansion with multiple slots
2. Filename uniqueness verification
3. Stage flag persistence across save/load
4. Full integration test

---

## Test Cases

### Matrix Filename Uniqueness
```python
# Setup: 2 jobs × 3 environments = 6 combinations, limit=4
# Expected filenames:
12345_m0.png  # wizard + forest
12345_m1.png  # wizard + castle
12345_m2.png  # wizard + dungeon
12345_m3.png  # knight + forest

# Or with slot names:
12345_wizard_forest.png
12345_wizard_castle.png
12345_wizard_dungeon.png
12345_knight_forest.png
```

### Stage Flag Persistence
```python
# Save: txt2img=True, img2img=False, adetailer=True, upscale=True
# Load: Should match exactly
# Current behavior: img2img gets enabled somehow?
```
