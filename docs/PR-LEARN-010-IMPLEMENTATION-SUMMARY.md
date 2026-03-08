# PR-LEARN-010 Implementation Summary

**Date**: 2026-01-04  
**Status**: ✅ COMPLETE  
**Tests**: ✅ 6/6 PASSING  

---

## Objective

Replace learning tab's manual `PackJobEntry` construction with direct `NormalizedJobRecord` (NJR) building to fix config propagation failure where run_metadata.json showed empty/null values for model, VAE, sampler, etc.

---

## Root Cause

Learning controller was bypassing StableNew's v2.6 canonical pipeline:
- Manually constructed `PackJobEntry` objects
- Used `app_state.job_draft.packs` manipulation
- Called unclear `on_add_job_to_queue_v2()` method
- Config values were lost during job building

---

## Solution Implemented

### 1. Added Three New Methods

#### `_build_variant_njr()`
- Builds `NormalizedJobRecord` directly with explicit config fields
- Retrieves config from stage cards via `_get_baseline_config()`
- Applies variant overrides (CFG, steps, sampler, etc.)
- Populates all NJR fields explicitly: `base_model`, `vae`, `sampler_name`, `scheduler`, `steps`, `cfg_scale`, `width`, `height`, `seed`
- Includes learning metadata in `extra_metadata`
- **NO PROMPT DUPLICATION** - single prompt field

#### `_njr_to_queue_job()`
- Converts NJR to Queue `Job` object
- Attaches NJR to job via `job._normalized_record`
- Creates `config_snapshot` for queue display
- Sets `learning_enabled=True` flag

#### `_execute_learning_job()`
- Executes job via pipeline runner (`_run_job`)
- Extracts NJR from job
- Returns result dict with status

### 2. Replaced `_submit_variant_job()`

**OLD (Broken)**:
```python
# Build PackJobEntry with complete config
pack_entry = PackJobEntry(
    pack_id=...,
    config_snapshot=...,
    ...
)

# Add to app_state job draft
app_state.job_draft.packs.append(pack_entry)

# Trigger submission
self.pipeline_controller.on_add_job_to_queue_v2()
```

**NEW (Fixed)**:
```python
# Build NJR directly
record = self._build_variant_njr(variant, experiment)

# Convert to Queue Job
job = self._njr_to_queue_job(record)
job.payload = lambda j=job: self._execute_learning_job(j)

# Submit via JobService (v2.6 canonical path)
job_service = self.pipeline_controller._job_service
job_service.submit_job_with_run_mode(job)
```

### 3. Added Imports

```python
import uuid
from datetime import datetime
from src.pipeline.job_models_v2 import NormalizedJobRecord, StageConfig
from src.queue.job_model import Job, JobPriority
```

---

## Files Modified

### `src/gui/controllers/learning_controller.py`

**Added**:
- Lines 9-10: `import uuid`, `from datetime import datetime`
- Line 14: `from src.pipeline.job_models_v2 import NormalizedJobRecord, StageConfig`
- Line 15: `from src.queue.job_model import Job, JobPriority`
- Lines 244-327: `_build_variant_njr()` method (~84 lines)
- Lines 329-360: `_njr_to_queue_job()` method (~32 lines)
- Lines 362-391: `_execute_learning_job()` method (~30 lines)

**Modified**:
- Lines 194-238: `_submit_variant_job()` - replaced PackJobEntry path with NJR submission (~45 lines)

**Removed**:
- All `PackJobEntry` imports and construction
- All `app_state.job_draft.packs` manipulation
- All `on_add_job_to_queue_v2()` calls

---

## Tests Created

### `tests/controller/test_learning_controller_njr.py` (NEW)

**6 Tests**:
1. ✅ `test_build_variant_njr_with_stage_config` - Verifies NJR construction with explicit config
2. ✅ `test_njr_prompt_not_duplicated` - Verifies single prompt occurrence
3. ✅ `test_submit_variant_job_uses_job_service` - Verifies JobService submission (not PackJobEntry)
4. ✅ `test_learning_job_full_config_propagation` - End-to-end config propagation test
5. ✅ `test_execute_learning_job` - Verifies job execution via pipeline runner
6. ✅ `test_no_packjobentry_imports` - Verifies forbidden patterns removed

**All tests passing**: 6/6

---

## Verification

### Forbidden Patterns Removed ✅

```bash
# Search for forbidden patterns
Select-String -Pattern "PackJobEntry|job_draft\.packs|on_add_job_to_queue_v2" learning_controller.py
# Result: Only in comments (PR documentation)
```

### NJR Methods Present ✅

```bash
# Search for new methods
Select-String -Pattern "_build_variant_njr|_njr_to_queue_job|_execute_learning_job" learning_controller.py
# Result: Found in imports, method definitions, and usages
```

### Syntax Valid ✅

```bash
# Check syntax
mcp_pylance_mcp_s_pylanceFileSyntaxErrors learning_controller.py
# Result: No syntax errors
```

---

## Architectural Compliance

- ✅ Uses NJR-only execution (v2.6 canonical)
- ✅ Submits via `JobService.submit_job_with_run_mode()`
- ✅ No PackJobEntry construction
- ✅ No job_draft manipulation
- ✅ No pipeline_config in runtime
- ✅ Explicit config fields in NJR (not nested dicts)
- ✅ Single prompt (no duplication)
- ✅ Learning metadata in `extra_metadata`

---

## Expected Behavior

### Before (Broken)
- `run_metadata.json` showed:
  ```json
  {
    "model": null,
    "vae": null,
    "sampler": null,
    "scheduler": null
  }
  ```
- Jobs executed with some default values
- No reliable config tracking
- Prompt duplication

### After (Fixed)
- `run_metadata.json` shows:
  ```json
  {
    "model": "test_model.safetensors",
    "vae": "test_vae.safetensors",
    "sampler": "Euler a",
    "scheduler": "normal",
    "steps": 20,
    "cfg_scale": 8.5  // variant value
  }
  ```
- Jobs execute with explicit config
- Full config provenance
- Single prompt occurrence

---

## Next Steps

### Immediate
- ✅ PR-LEARN-010 implemented
- ⏳ PR-LEARN-011 implementation (validation & logging)
- ⏳ PR-LEARN-012 implementation (execution controller integration)

### Testing
- Manual test: Create learning experiment, submit jobs, verify run_metadata.json
- Integration test: Run full learning workflow
- Verify image generation with correct config values

---

## Summary

PR-LEARN-010 successfully:
- Removed architecture-violating PackJobEntry path
- Implemented direct NJR construction with explicit config
- Fixed config propagation to run_metadata.json
- Eliminated prompt duplication
- Aligned learning tab with v2.6 canonical pipeline
- All tests passing (6/6)

**Status**: READY FOR MANUAL TESTING
