# D-FILENAME-001: Variant Index Not Incrementing in Filenames

**Status**: Discovery  
**Priority**: High  
**Impact**: User cannot distinguish between randomized variants  
**Estimated Implementation**: 3-4 hours

---

## Problem Statement

When using randomization matrix with a limit > 1, multiple variants are generated from a single prompt row. However, all variants are being saved with `v01` in the filename instead of incrementing (`v01`, `v02`, `v03`, etc.). This makes it impossible to identify which variant corresponds to which randomization.

### Current Behavior

For a prompt with 3 randomized variants:
```
txt2img_p03_v01_SDXL_batch0.png
txt2img_p03_v01_SDXL_batch1.png  
txt2img_p03_v01_SDXL_batch2.png
```

All show `v01` even though they're different variants.

### Expected Behavior

```
txt2img_p03_v01_SDXL_batch0.png  (variant 1)
txt2img_p03_v02_SDXL_batch0.png  (variant 2)
txt2img_p03_v03_SDXL_batch0.png  (variant 3)
```

Each variant should have an incrementing variant number.

---

## Root Cause Analysis

### Data Flow

1. **PromptPackNormalizedJobBuilder** creates NormalizedJobRecord objects
   - Location: `src/pipeline/prompt_pack_job_builder.py`
   - When randomization expands a single prompt entry into multiple variants
   - Each variant should get a unique `variant_index` (0, 1, 2...)

2. **RunPlan** extracts variant_id from NJR
   - Location: `src/pipeline/run_plan.py:54`
   - Code: `variant_id=getattr(njr, "variant_index", 0) or 0`
   - Directly reads NJR's variant_index field

3. **PipelineRunner** builds filename using variant_id
   - Location: `src/pipeline/pipeline_runner.py:236`
   - Code: `base_prefix = f"{stage.stage_name}_p{prompt_row+1:02d}_v{stage.variant_id+1:02d}"`
   - Uses variant_id from stage (which came from NJR)

### Investigation Points

**CHECK 1**: Does `PromptPackNormalizedJobBuilder.build_jobs()` assign variant_index correctly?

```python
# src/pipeline/prompt_pack_job_builder.py
# Need to verify: When _expand_with_randomization() creates N variants,
# does each NJR get variant_index = 0, 1, 2, ... N-1?
```

**CHECK 2**: Is variant_index being preserved through job creation?

```python
# src/controller/job_service.py:346
# When Job object is created from NJR via _job_from_njr()
# Does it preserve the variant_index in the NJR snapshot?
```

**CHECK 3**: Is NJR deserialization corrupting variant_index?

```python
# When queue state is saved/restored
# Does variant_index survive serialization round-trip?
```

---

## Investigation Results

### File: `src/pipeline/prompt_pack_job_builder.py`

**Line ~200-300**: `_expand_with_randomization()` method

Likely findings:
- Creates multiple NJRs from single entry when randomizer limit > 1
- **BUG HYPOTHESIS**: All NJRs created in loop get same variant_index (probably 0)
- **FIX**: Loop should increment variant_index for each variant created

Expected code pattern:
```python
# CURRENT (BUGGY):
for iteration in range(limit):
    njr = self._build_njr_from_entry(
        entry=entry,
        variant_index=0,  # ❌ Always 0!
        ...
    )
    
# SHOULD BE:
for variant_idx in range(limit):
    njr = self._build_njr_from_entry(
        entry=entry,
        variant_index=variant_idx,  # ✅ Increments: 0, 1, 2...
        ...
    )
```

### File: `src/pipeline/job_models_v2.py`

**NormalizedJobRecord dataclass** (line ~500-600):
- Has `variant_index: int = 0` field
- Has `variant_total: int = 1` field
- These should be set during job creation

---

## Affected Code Locations

### Primary Bug Location
- **`src/pipeline/prompt_pack_job_builder.py`**
  - Method: `_expand_with_randomization()` or similar
  - Issue: Not incrementing variant_index when creating multiple variants
  - Fix: Pass loop index as variant_index

### Secondary Verification Needed
- **`src/pipeline/job_models_v2.py`**: Ensure NJR has correct default
- **`src/controller/job_service.py`**: Verify NJR→Job preserves variant_index
- **`src/services/queue_store_v2.py`**: Verify variant_index survives serialization

---

## Implementation Plan

### Phase 1: Investigation (30 minutes)
1. **Read `prompt_pack_job_builder.py`** lines 1-500
2. **Identify** where multiple NJRs are created from single entry
3. **Confirm** variant_index is not being incremented
4. **Check** if variant_total is being set correctly

### Phase 2: Fix Variant Index Assignment (1 hour)
1. **Modify** the loop that creates variant NJRs
2. **Pass** variant_index as loop iteration counter (0, 1, 2...)
3. **Set** variant_total to the limit value
4. **Ensure** both fields are passed to NJR constructor

Example fix:
```python
variants_list = []
for variant_idx in range(randomizer_limit):
    njr = NormalizedJobRecord(
        job_id=generate_job_id(),
        variant_index=variant_idx,        # ✅ Unique per variant
        variant_total=randomizer_limit,   # ✅ Total variants for this prompt
        batch_index=batch_idx,
        batch_total=batch_runs,
        # ... other fields
    )
    variants_list.append(njr)
```

### Phase 3: Testing (1 hour)
1. **Create test prompt pack** with randomization limit = 3
2. **Queue jobs** and verify filenames show v01, v02, v03
3. **Check manifests** to ensure variant info is correct
4. **Verify GUI display** shows variant numbers in queue panel

### Phase 4: Edge Cases (30 minutes)
1. **Test**: Single variant (limit=1) → should show v01
2. **Test**: Combined with batch_runs > 1 → v01_b01, v01_b02, etc.
3. **Test**: Config variants + randomizer → both indices shown
4. **Verify**: Queue state save/restore preserves variant_index

---

## Success Criteria

✅ **Filenames show correct variant numbers**:
   - Single prompt with 3 variants → `v01`, `v02`, `v03`
   - Each variant has unique identifier in filename

✅ **GUI displays correct variant info**:
   - Queue panel shows `[row=3, v=2]` correctly
   - Each variant is distinguishable

✅ **Manifests include variant metadata**:
   - `variant_index` and `variant_total` fields present
   - Values match filename numbering

✅ **Backward compatibility**:
   - Jobs without randomization still work (variant_index=0)
   - Old queue state loads correctly (defaults to 0)

---

## Testing Strategy

### Unit Tests
```python
def test_randomizer_assigns_variant_indices():
    """Test that multiple variants get unique indices."""
    builder = PromptPackNormalizedJobBuilder()
    entry = PackJobEntry(
        pack_id="test",
        row_index=0,
        randomizer_limit=3,  # Create 3 variants
    )
    
    njrs = builder._expand_with_randomization(entry)
    
    assert len(njrs) == 3
    assert njrs[0].variant_index == 0
    assert njrs[1].variant_index == 1
    assert njrs[2].variant_index == 2
    assert all(njr.variant_total == 3 for njr in njrs)
```

### Integration Test
1. Load prompt pack with randomization
2. Set limit to 3
3. Queue 1 prompt → expect 3 jobs
4. Run jobs
5. Verify output filenames have v01, v02, v03

---

## Risk Assessment

**Low Risk**: 
- Isolated change to job builder
- Clear data flow
- Easy to test
- No breaking changes (only affects new jobs)

**Potential Issues**:
- Need to ensure variant_index defaults to 0 for non-randomized jobs
- Queue state serialization must handle new field values
- GUI display logic already uses variant_index (just needs correct values)

---

## Dependencies

**Blocked by**: None

**Blocks**:
- User ability to distinguish variants
- Learning system variant tracking
- Reproducibility of specific variants

**Related PRs**:
- GUI display shows variant info (already implemented)
- Filename template includes variant (already implemented)
- Just needs correct variant_index values

---

## Next Steps

1. ✅ Create this discovery document
2. ⏳ Read `prompt_pack_job_builder.py` to confirm hypothesis
3. ⏳ Implement fix with variant_index loop counter
4. ⏳ Test with 3-variant randomization
5. ⏳ Update any documentation about variant numbering
