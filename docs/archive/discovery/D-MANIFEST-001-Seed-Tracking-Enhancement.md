# D-MANIFEST-001: Enhanced Seed Tracking in Manifests

**Status**: Discovery  
**Priority**: High  
**Impact**: Cannot reproduce images, learning workflow blocked  
**Estimated Implementation**: 4-6 hours

---

## Problem Statement

Image manifests (JSON metadata files) are not capturing complete seed information needed for reproducibility. Current issues:

1. **Seeds showing -1**: Manifests show `requested_seed: -1` instead of actual user input
2. **Missing original values**: No field for user's original seed/subseed input
3. **Subseed not captured**: `actual_subseed` is -1 instead of real value used
4. **Batch manifests missing**: Only one manifest per txt2img stage, not one per batch image

### Current Manifest Structure

```json
{
  "name": "txt2img_p03_v01_batch0",
  "stage": "txt2img",
  "requested_seed": -1,           // ❌ Should be user input or generated seed
  "actual_seed": 1234567890,      // ✅ Correct (from WebUI response)
  "actual_subseed": -1,           // ❌ Should be real subseed
  "subseed_strength": 0.0         // ❌ Missing user input value
}
```

### Required Manifest Structure

```json
{
  "name": "txt2img_p03_v01_batch0",
  "stage": "txt2img",
  "seeds": {
    "original_seed": -1,          // ✅ User's input (-1 = random)
    "original_subseed": -1,       // ✅ User's subseed input
    "original_subseed_strength": 0.0,  // ✅ User's strength
    "final_seed": 1234567890,     // ✅ Actual seed used by SD
    "final_subseed": 987654321,   // ✅ Actual subseed used
    "final_subseed_strength": 0.0 // ✅ Final strength value
  },
  "batch_index": 0,               // ✅ Which image in batch
  "batch_total": 2                // ✅ Total images in batch
}
```

---

## Root Cause Analysis

### Issue 1: Seed = -1 in Manifests

**Location**: `src/pipeline/executor.py:1273-1278`

```python
metadata = {
    "requested_seed": config.get("seed", -1),    # ❌ Gets -1 from config
    "actual_seed": gen_info.get("seed"),         # ✅ Gets real seed from response
    "actual_subseed": gen_info.get("subseed"),   # ❌ Gets -1 or None
}
```

**Problem**: 
- `config.get("seed", -1)` retrieves the value sent to WebUI
- If user specified -1 (random), that's what gets stored
- Should store BOTH user input (-1) AND final generated seed

**WebUI Behavior**:
- When seed = -1 sent → WebUI generates random seed
- Response includes the actual seed used: `response["info"]["seed"]`
- We capture this in `actual_seed` ✅
- But `requested_seed` should be "original_seed" to clarify it's user input

### Issue 2: Subseed Not Captured

**WebUI Response Structure**:
```json
{
  "images": ["base64..."],
  "info": {
    "seed": 1234567890,
    "subseed": 987654321,      // ✅ WebUI returns this
    "subseed_strength": 0.0
  }
}
```

**Current Code** (`src/pipeline/executor.py:1233`):
```python
gen_info = self._extract_generation_info(response)
# gen_info should contain subseed from WebUI response
```

**Problem**: Either `_extract_generation_info()` isn't parsing subseed, or it's being lost before manifest creation.

### Issue 3: Only One Manifest Per Stage

**Location**: `src/pipeline/executor.py:1244-1298`

```python
for idx, img_base64 in enumerate(response["images"]):
    # Loop creates multiple images
    # But only ONE manifest is saved (outside loop or last iteration)
    metadata = {...}
    self.logger.save_manifest(run_dir, safe_name, metadata)  # ✅ Called per image
```

**Analysis**: The code DOES loop and call `save_manifest()` for each image. Need to verify:
- Is `save_manifest()` actually writing files?
- Are filenames unique per batch image?
- Is there a conditional preventing manifest creation?

---

## Investigation Checklist

### 1. Verify `_extract_generation_info()` Parsing

**File**: `src/pipeline/executor.py` (search for method definition)

**Check**:
```python
def _extract_generation_info(self, response):
    # Does this extract:
    # - seed ✅
    # - subseed ❓
    # - subseed_strength ❓
    info = response.get("info", {})
    if isinstance(info, str):
        info = json.loads(info)
    return {
        "seed": info.get("seed"),
        "subseed": info.get("subseed"),        # ❓ Is this line present?
        "subseed_strength": info.get("subseed_strength"),  # ❓
    }
```

**Action**: If missing, add subseed extraction.

### 2. Check Manifest Save Logic

**File**: `src/pipeline/execution_logger.py` or `executor.py` (logger class)

**Search for**: `def save_manifest(`

**Check**:
- Does it write one JSON file per call?
- Is filename based on `safe_name` parameter?
- Are there any conditions that skip saving?

### 3. Verify NJR Seed Values

**File**: `src/pipeline/job_models_v2.py`

**Check NormalizedJobRecord**:
```python
@dataclass
class NormalizedJobRecord:
    seed: int | None = None        # User's input seed
    subseed: int | None = None     # User's input subseed
    subseed_strength: float = 0.0  # User's strength
```

**Action**: Ensure these fields are populated from prompt pack or defaults.

### 4. Trace Seed Flow

1. **User Input** → PromptPack or GUI
2. **Job Creation** → NormalizedJobRecord.seed = user_value
3. **Pipeline Build** → payload["seed"] = njr.seed
4. **WebUI Call** → Sends seed=-1 or seed=123456
5. **WebUI Response** → Returns actual seed used
6. **Manifest** → Should store BOTH input and final

---

## Implementation Plan

### Phase 1: Seed/Subseed Extraction (1 hour)

**File**: `src/pipeline/executor.py`

**1.1. Enhance `_extract_generation_info()`**:
```python
def _extract_generation_info(self, response: dict) -> dict:
    """Extract generation parameters from WebUI response."""
    info = response.get("info", {})
    if isinstance(info, str):
        import json
        info = json.loads(info)
    
    return {
        "seed": info.get("seed"),
        "subseed": info.get("subseed"),
        "subseed_strength": info.get("subseed_strength", 0.0),
        "sampler_name": info.get("sampler_name"),
        "steps": info.get("steps"),
        "cfg_scale": info.get("cfg_scale"),
        # Add any other useful fields
    }
```

**1.2. Update Manifest Creation** (line ~1273-1278):
```python
metadata = {
    "name": safe_name,
    "stage": "txt2img",
    "seeds": {
        "original_seed": config.get("seed", -1),           # User input
        "original_subseed": config.get("subseed", -1),     # User subseed
        "original_subseed_strength": config.get("subseed_strength", 0.0),
        "final_seed": gen_info.get("seed"),                # WebUI actual
        "final_subseed": gen_info.get("subseed", -1),      # WebUI actual
        "final_subseed_strength": gen_info.get("subseed_strength", 0.0),
    },
    "batch_index": idx,              # Which image in this batch
    "batch_total": len(response["images"]),
    # ... rest of metadata
}
```

### Phase 2: Verify Manifest Files (30 minutes)

**Check**: Are manifests being written to disk?

**Location**: `output/{timestamp}_{pack}/manifests/`

**Expected Files**:
```
txt2img_p03_v01_batch0.json
txt2img_p03_v01_batch1.json
```

**Verification**:
1. Run job with batch_size=2
2. Check manifests folder
3. Confirm 2 JSON files created
4. Open and verify seed structure

### Phase 3: Img2Img Stage Seeds (1 hour)

**File**: `src/pipeline/executor.py` (img2img method ~1400-1500)

**Apply same seed tracking**:
```python
# In img2img generation loop
metadata = {
    "seeds": {
        "original_seed": config.get("seed", -1),
        "original_subseed": config.get("subseed", -1),
        "original_subseed_strength": config.get("subseed_strength", 0.0),
        "final_seed": gen_info.get("seed"),
        "final_subseed": gen_info.get("subseed", -1),
        "final_subseed_strength": gen_info.get("subseed_strength", 0.0),
    },
    "input_image": source_image,  # Track which txt2img output was used
    "batch_index": idx,
    # ... rest
}
```

### Phase 4: Upscale/Refiner Stages (1 hour)

**Apply to all stage types**:
- Upscale
- Refiner
- Any custom stages

**Create helper function**:
```python
def _build_seed_metadata(self, config: dict, gen_info: dict) -> dict:
    """Build consistent seed tracking structure for all stages."""
    return {
        "original_seed": config.get("seed", -1),
        "original_subseed": config.get("subseed", -1),
        "original_subseed_strength": config.get("subseed_strength", 0.0),
        "final_seed": gen_info.get("seed"),
        "final_subseed": gen_info.get("subseed", -1),
        "final_subseed_strength": gen_info.get("subseed_strength", 0.0),
    }
```

Use in all stages:
```python
metadata["seeds"] = self._build_seed_metadata(config, gen_info)
```

### Phase 5: Testing (2 hours)

**Test Case 1: Random Seed**
```python
# Input: seed = -1
# Expected manifest:
{
  "seeds": {
    "original_seed": -1,        # User said "random"
    "final_seed": 1234567890    # WebUI generated this
  }
}
```

**Test Case 2: Fixed Seed**
```python
# Input: seed = 42
# Expected manifest:
{
  "seeds": {
    "original_seed": 42,     # User specified
    "final_seed": 42         # WebUI used exactly this
  }
}
```

**Test Case 3: Batch Generation**
```python
# Input: batch_size = 3
# Expected: 3 manifest files
# - txt2img_p01_v01_batch0.json
# - txt2img_p01_v01_batch1.json
# - txt2img_p01_v01_batch2.json
```

**Test Case 4: Subseed Variation**
```python
# Input: subseed = 999, subseed_strength = 0.5
# Expected manifest:
{
  "seeds": {
    "original_subseed": 999,
    "original_subseed_strength": 0.5,
    "final_subseed": 999,
    "final_subseed_strength": 0.5
  }
}
```

---

## File Modifications Required

### Primary Changes

**1. `src/pipeline/executor.py`**
- Line ~1100: Enhance `_extract_generation_info()`
- Line ~1273: Update txt2img manifest structure
- Line ~1400: Update img2img manifest structure
- Add: `_build_seed_metadata()` helper method

**2. `src/utils/image_metadata.py`** (if exists)
- Update any manifest validation schemas
- Add seed structure documentation

### Secondary Changes

**3. `src/learning/learning_record.py`**
- Update to consume new seed structure
- Use `final_seed` for reproducibility

**4. `tests/test_manifest_structure.py`** (create if missing)
- Test manifest schema
- Verify seed fields present
- Test batch manifest creation

---

## Backward Compatibility

**Legacy Manifests** (old format):
```json
{
  "requested_seed": -1,
  "actual_seed": 123
}
```

**Migration Strategy**:
- New manifests use `seeds.original_seed` and `seeds.final_seed`
- Old manifest readers should check both formats:
  ```python
  if "seeds" in manifest:
      seed = manifest["seeds"]["final_seed"]
  else:
      seed = manifest.get("actual_seed") or manifest.get("requested_seed")
  ```

**Fallback Defaults**:
- Missing `final_subseed` → default to -1
- Missing `original_seed` → try old `requested_seed` field

---

## Success Criteria

✅ **All manifests contain complete seed data**:
- original_seed (user input)
- final_seed (WebUI actual)
- original_subseed and final_subseed
- subseed_strength values

✅ **One manifest per batch image**:
- batch_size=3 → 3 manifest files
- Each has unique batch_index

✅ **Reproducibility verified**:
- Load manifest
- Use final_seed to regenerate
- Output matches original

✅ **Learning workflow enabled**:
- Can extract seed from any image
- Can reproduce variants
- Can track seed evolution through stages

---

## Risk Assessment

**Medium Risk**:
- Changes to manifest structure (but backward compatible)
- Affects all pipeline stages
- Testing needed for all stage types

**Mitigation**:
- Use nested `seeds` object (doesn't break old parsers)
- Keep old fields temporarily for transition period
- Comprehensive testing before deployment

---

## Dependencies

**Requires**:
- Working WebUI response parsing
- File I/O for manifests
- JSON serialization

**Enables**:
- Image reproducibility
- Learning system integration
- Debug/troubleshooting workflows

---

## Next Steps

1. ✅ Create this discovery document
2. ⏳ Read `_extract_generation_info()` implementation
3. ⏳ Check if subseeds are being parsed
4. ⏳ Implement `_build_seed_metadata()` helper
5. ⏳ Update all stage manifest creation
6. ⏳ Test with batch generation
7. ⏳ Verify manifest files on disk
8. ⏳ Update learning system to use new structure
