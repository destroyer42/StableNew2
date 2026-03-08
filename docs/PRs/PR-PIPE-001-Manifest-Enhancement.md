# PR-PIPE-001 – Manifest Enhancement: Model, VAE, Actual Seed

## Context

The current manifest files generated during pipeline execution are missing critical metadata required for the learning/rating module:

1. **Model** - Not recorded, making it impossible to correlate image quality with model choice
2. **VAE** - Not recorded, critical for understanding color/saturation differences
3. **Actual Seed** - Manifests store the *requested* seed (`-1` for random), not the *resolved* seed returned by WebUI
4. **Job ID** - Manifests are not linked back to their parent job for aggregation
5. **Stage Duration** - No timing data per stage for performance analysis

Without this data, the learning module cannot:
- Suggest optimal model/VAE combinations
- Reproduce successful generations (seed is always -1)
- Analyze which configurations produce faster results
- Link manifests to job history for unified views

The WebUI API returns the actual seed in the `info` field of txt2img/img2img responses, but this is currently discarded.

## Non-Goals

- Changing the manifest file format or location
- Adding learning/rating logic (that's a separate module)
- Modifying how manifests are read/displayed in the GUI
- Adding thumbnail generation to manifests
- Changing the NormalizedJobRecord structure (manifests are post-execution artifacts)

## Invariants

- All new manifest fields are optional and backward-compatible
- Existing manifest reading code must not break on old manifests
- Model/VAE values must match exactly what was sent to WebUI (no normalization)
- If seed resolution fails, store the original request seed with a flag
- Stage timing uses `time.monotonic()` for accuracy (not wall clock)
- Manifest writes must not block the pipeline on failure (log and continue)

## Allowed Files

- `src/pipeline/executor.py` - Add model/VAE/seed extraction and timing
- `src/api/client.py` - Expose seed from response info (if not already)
- `src/utils/logger.py` - Validate manifest fields (optional)
- `tests/pipeline/test_manifest_enhancement.py` (new)
- `tests/pipeline/test_executor_manifest_fields.py` (new)

## Do Not Touch

- `src/pipeline/job_models_v2.py` - NJR structure unchanged
- `src/queue/job_history_store.py` - History format unchanged
- `src/gui/*` - Display changes are PR-PIPE-005/007
- `src/controller/*` - Controller logic unchanged
- Any existing test files (create new ones)

## Interfaces

### Manifest Metadata Schema (Enhanced)

```python
# txt2img manifest after this PR
{
    "name": str,
    "stage": "txt2img",
    "timestamp": str,                    # Existing
    "original_prompt": str,              # Existing
    "final_prompt": str,                 # Existing
    "config": dict,                      # Existing
    "path": str,                         # Existing
    
    # NEW FIELDS
    "job_id": str | None,                # Parent job ID for linking
    "model": str | None,                 # Model name used (exact WebUI name)
    "vae": str | None,                   # VAE name used (or "Automatic" if not set)
    "requested_seed": int,               # Original seed from config (-1 for random)
    "actual_seed": int | None,           # Resolved seed from WebUI response
    "actual_subseed": int | None,        # Resolved subseed from WebUI response
    "stage_duration_ms": int | None,     # Time spent in this stage
    "generation_info": dict | None,      # Raw WebUI info dict (optional, for debugging)
}
```

### Seed Extraction Function

```python
def _extract_generation_info(self, response: dict[str, Any]) -> dict[str, Any]:
    """
    Extract generation metadata from WebUI response.
    
    Args:
        response: Raw WebUI API response with 'info' field
        
    Returns:
        Dict with extracted seed, subseed, and any other useful fields
        Returns empty dict if extraction fails
    """
```

### Error Behavior

- If WebUI response lacks `info` field: log warning, set `actual_seed=None`
- If `info` is string (JSON): parse it, extract fields
- If `info` parsing fails: log error, continue with `actual_seed=None`
- If model/VAE lookup fails: use value from config as-is
- Stage timing failure: set `stage_duration_ms=None`

## Implementation Steps (Order Matters)

### Step 1: Add Seed Extraction Helper to Executor

In `src/pipeline/executor.py`, add method to parse WebUI response info:

```python
def _extract_generation_info(self, response: dict[str, Any]) -> dict[str, Any]:
    """Extract seed and other metadata from WebUI response."""
    info = response.get("info")
    if info is None:
        return {}
    
    # WebUI returns info as JSON string
    if isinstance(info, str):
        try:
            info = json.loads(info)
        except json.JSONDecodeError:
            logger.warning("Failed to parse WebUI info as JSON")
            return {}
    
    if not isinstance(info, dict):
        return {}
    
    return {
        "seed": info.get("seed"),
        "subseed": info.get("subseed"),
        "all_seeds": info.get("all_seeds"),
        "all_subseeds": info.get("all_subseeds"),
    }
```

### Step 2: Track Stage Timing in txt2img

Wrap txt2img execution with timing:

```python
def _run_txt2img_impl(self, ...):
    stage_start = time.monotonic()
    # ... existing code ...
    response = self._generate_images("txt2img", payload)
    stage_duration_ms = int((time.monotonic() - stage_start) * 1000)
    
    # Extract actual seed from response
    gen_info = self._extract_generation_info(response)
```

### Step 3: Enhance txt2img Manifest Metadata

Update the metadata dict creation (~line 1035):

```python
metadata = {
    "name": image_name,
    "stage": "txt2img",
    "timestamp": timestamp,
    "prompt": prompt,
    "config": self._clean_metadata_payload(payload),
    "path": str(image_path),
    
    # NEW: Essential tracking fields
    "job_id": getattr(self, "_current_job_id", None),
    "model": config.get("model") or config.get("sd_model_checkpoint"),
    "vae": config.get("vae") or "Automatic",
    "requested_seed": config.get("seed", -1),
    "actual_seed": gen_info.get("seed"),
    "actual_subseed": gen_info.get("subseed"),
    "stage_duration_ms": stage_duration_ms,
}
```

### Step 4: Apply Same Pattern to img2img Stage

Update `run_img2img` method (~line 1159) with same enhancements:
- Add stage timing
- Extract generation info from response
- Add new fields to manifest metadata

### Step 5: Apply Same Pattern to ADetailer Stage

Update `run_adetailer` method (~line 1455) with same enhancements.

### Step 6: Apply Same Pattern to Upscale Stage

Update `run_upscale_stage` method (~line 2983) with same enhancements.
Note: Upscale may not return seed info; set to `None` if not applicable.

### Step 7: Store Current Job ID in Executor Context

In `run_njr` or `run_pipeline`, store the job_id:

```python
def run_njr(self, njr: NormalizedJobRecord, cancel_token=None):
    self._current_job_id = njr.job_id
    try:
        # ... existing pipeline execution ...
    finally:
        self._current_job_id = None
```

### Step 8: Write Tests

Create `tests/pipeline/test_manifest_enhancement.py`:
- Test seed extraction from valid response
- Test seed extraction from malformed response
- Test manifest contains all new fields
- Test timing is recorded
- Test model/VAE are captured

## Acceptance Criteria

1. **Given** a txt2img job with `seed=-1`, **when** the job completes, **then** the manifest contains `actual_seed` with the resolved positive integer seed from WebUI.

2. **Given** a job configured with model `epicrealismXL_v5`, **when** the job completes, **then** the manifest contains `"model": "epicrealismXL_v5"`.

3. **Given** a job with no VAE specified, **when** the job completes, **then** the manifest contains `"vae": "Automatic"`.

4. **Given** a txt2img stage that takes 45 seconds, **when** the manifest is written, **then** `stage_duration_ms` is approximately 45000 (±500ms).

5. **Given** a multi-stage pipeline (txt2img → adetailer → upscale), **when** all stages complete, **then** each stage's manifest contains its individual `stage_duration_ms`.

6. **Given** a WebUI response with malformed `info` field, **when** extracting generation info, **then** `actual_seed=None` and no exception is raised.

7. **Given** an existing manifest without new fields, **when** reading the manifest, **then** no errors occur (backward compatibility).

## Test Plan

### New Test File: `tests/pipeline/test_manifest_enhancement.py`

```bash
pytest tests/pipeline/test_manifest_enhancement.py -v
```

**Test Cases:**

1. `test_extract_generation_info_valid_response` - Parse seed from valid JSON info
2. `test_extract_generation_info_string_info` - Parse seed when info is JSON string
3. `test_extract_generation_info_missing_info` - Return empty dict when info missing
4. `test_extract_generation_info_malformed_json` - Handle parse errors gracefully
5. `test_txt2img_manifest_contains_model` - Verify model in manifest
6. `test_txt2img_manifest_contains_vae` - Verify VAE in manifest
7. `test_txt2img_manifest_contains_actual_seed` - Verify resolved seed
8. `test_txt2img_manifest_contains_duration` - Verify timing recorded
9. `test_txt2img_manifest_contains_job_id` - Verify job linkage
10. `test_adetailer_manifest_contains_new_fields` - Same for adetailer
11. `test_upscale_manifest_contains_new_fields` - Same for upscale

**Expected State:**
- Before PR: Tests do not exist
- After PR: All tests pass

### Integration Verification

```bash
# Run a real generation and inspect manifest
python -c "
import json
from pathlib import Path

manifest_path = Path('output').glob('*/manifests/*_txt2img.json')
for m in list(manifest_path)[-1:]:
    data = json.loads(m.read_text())
    print(f'Model: {data.get(\"model\")}')
    print(f'VAE: {data.get(\"vae\")}')
    print(f'Requested Seed: {data.get(\"requested_seed\")}')
    print(f'Actual Seed: {data.get(\"actual_seed\")}')
    print(f'Duration: {data.get(\"stage_duration_ms\")}ms')
"
```

## Rollback

```bash
git revert <commit-hash>
```

Rollback is safe because:
- New manifest fields are additive only
- No existing code reads these fields yet (PR-PIPE-005/007 add readers)
- Old manifests remain valid

## Dependencies

- None (this is the foundation PR)

## Dependents

- PR-PIPE-005 (History Panel) uses model/duration from manifests
- PR-PIPE-007 (Seed Display) uses actual_seed from manifests
- Learning/Rating module (future) requires all new fields
