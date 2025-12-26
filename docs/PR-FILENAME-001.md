# PR-FILENAME-001: Human-Readable Filename Convention

**Status**: 🟡 Specification (Awaiting Approval)  
**Priority**: MEDIUM  
**Effort**: MEDIUM (2-3 days)  
**Phase**: Post-Phase 4 Quality-of-Life Enhancement  
**Date**: 2025-12-25

---

## Context & Motivation

### Problem Statement

Current filename convention has several user-hostile issues:

1. **Zero-Based Indexing**: Files use `p00`, `p01`, `batch0`, `batch1` but GUI shows "Prompt 1", "Prompt 2", etc.
   - **User confusion**: File `p00` doesn't match "Prompt 1" in GUI
   - **Mental overhead**: Users must translate indices constantly

2. **Manifest Batch Number Missing**: txt2img manifests don't include batch numbers in filename
   - **Critical bug**: Multiple batches overwrite same manifest file
   - **Data loss**: Only last batch's metadata is preserved

3. **Redundant Stage Labels**: Filenames have stage at both start and end
   - Current: `txt2img_p00_00_a3f2b1c9_batch0_txt2img.png`
   - **Visual clutter**: Redundant suffix makes names harder to scan

4. **Hash Instead of Pack Name**: 8-char hash doesn't identify source
   - Current: `txt2img_p00_00_a3f2b1c9_batch0.png`
   - **Lost context**: Once moved from folder, can't identify which pack generated it
   - **Debugging pain**: No way to trace image back to prompt pack

5. **No Collision Failsafe**: If duplicate filenames somehow occur
   - **Data loss risk**: Files silently overwrite each other
   - **No recovery**: Lost images with no warning

### Current Architecture

**Filename Generation**: `src/utils/file_io.py::build_safe_image_name()`
```python
def build_safe_image_name(
    base_prefix: str,  # e.g., "txt2img_p00_00"
    matrix_values: dict[str, Any] | None = None,
    seed: int | None = None,
    batch_index: int | None = None,
    max_length: int = 120,
) -> str:
    # Returns: "txt2img_p00_00_a3f2b1c9_batch0"
```

**Usage Sites**:
- `src/pipeline/pipeline_runner.py` (lines 239, 310, 404, 494)
- `src/pipeline/executor.py` (lines 2990, 3169, 3450)

**Current Format**:
```
txt2img_p00_00_a3f2b1c9_batch0_txt2img.png     # Image
txt2img_p00_00_a3f2b1c9_txt2img.json           # Manifest (no batch number!)
```

### User Impact

**Scenario**: User generates 2 prompts with 3 variants each, 2 batches per variant

**Current Output** (confusing):
```
txt2img_p00_00_a3f2b1c9_batch0.png  ← GUI shows "Prompt 1, Variant 1, Batch 1"
txt2img_p00_00_a3f2b1c9_batch1.png  ← GUI shows "Prompt 1, Variant 1, Batch 2"
txt2img_p01_00_b4c3d2e1_batch0.png  ← GUI shows "Prompt 2, Variant 1, Batch 1"
```

**User confusion**:
- "Where is Prompt 1?" → Must remember p00 = Prompt 1
- "What pack made this?" → Hash `a3f2b1c9` is meaningless
- "Why two txt2img labels?" → Redundancy

**Proposed Output** (intuitive):
```
txt2img_p01_v01_FantasyHero_batch1.png  ← Matches GUI "Prompt 1, Variant 1, Batch 1"
txt2img_p01_v01_FantasyHero_batch2.png  ← Matches GUI "Prompt 1, Variant 1, Batch 2"
txt2img_p02_v01_SciFiCity_batch1.png   ← Matches GUI "Prompt 2, Variant 1, Batch 1"
```

**User benefits**:
- ✅ Prompt numbers match GUI exactly
- ✅ Pack name identifies source (first 10 chars)
- ✅ Variant numbers clear (v01, v02, v03...)
- ✅ No redundant labels
- ✅ Manifest batch numbers prevent overwrites

---

## Goals & Non-Goals

### ✅ Goals

1. **1-Based Indexing**
   - Prompt index: `p01` instead of `p00` (matches GUI "Prompt 1")
   - Variant index: `v01` instead of `00` (clearer semantics)
   - Batch index: `batch1` instead of `batch0` (matches GUI "Batch 1")

2. **Pack Name Instead of Hash**
   - Replace 8-char hash with first 10 chars of prompt pack name
   - Sanitize for filesystem safety (underscore replacement)
   - Fallback to hash if pack name unavailable

3. **Remove Redundant Stage Label**
   - Keep stage prefix: `txt2img_`, `adetailer_`, `upscale_`
   - Remove suffix: ~~`_txt2img`~~, ~~`_adetailer`~~, ~~`_upscale`~~

4. **Add Batch Number to Manifests**
   - Manifests must include batch index: `_batch1.json`, `_batch2.json`
   - Prevents overwrites when batch_size > 1

5. **Collision Failsafe**
   - Check if file exists before saving
   - Append `_copy1`, `_copy2`, etc. to avoid overwrites
   - Log warning when collision occurs (indicates bug)

6. **Maintain Uniqueness**
   - Every image/manifest must have unique filename
   - No overwrites across prompts, variants, batches, stages

### ❌ Non-Goals

1. **Rename Existing Files**: This PR only affects new runs (no migration)
2. **Change Folder Structure**: Output directory organization unchanged
3. **Metadata Format Changes**: Manifest JSON schema unchanged
4. **UI Changes**: GUI display logic unchanged (already shows 1-based)

---

## Proposed Changes

### Change 1: Update `build_safe_image_name()` Signature

**File**: `src/utils/file_io.py`

**Before**:
```python
def build_safe_image_name(
    base_prefix: str,
    matrix_values: dict[str, Any] | None = None,
    seed: int | None = None,
    batch_index: int | None = None,
    max_length: int = 120,
) -> str:
```

**After**:
```python
def build_safe_image_name(
    base_prefix: str,
    matrix_values: dict[str, Any] | None = None,
    seed: int | None = None,
    batch_index: int | None = None,
    pack_name: str | None = None,  # NEW: Prompt pack name for human readability
    max_length: int = 120,
    use_one_based_indexing: bool = True,  # NEW: Convert batch to 1-based
) -> str:
    """
    Build a safe, filesystem-compatible image name with human-readable identifiers.
    
    Args:
        base_prefix: Prefix with prompt/variant indices (e.g., "txt2img_p01_v01")
        matrix_values: Optional matrix slot values for hash uniqueness
        seed: Optional seed value for hash uniqueness
        batch_index: Optional batch index (0-based internally, converted to 1-based in filename)
        pack_name: Optional prompt pack name (first 10 chars used, sanitized)
        max_length: Maximum filename length (default 120)
        use_one_based_indexing: Convert batch_index to 1-based in filename (default True)
    
    Returns:
        Safe filename string (without extension)
    
    Example (new format):
        build_safe_image_name(
            "txt2img_p01_v01",
            pack_name="Fantasy_Heroes_v2",
            batch_index=0
        )
        → "txt2img_p01_v01_FantasyHer_batch1"
    """
```

**Implementation**:
```python
def build_safe_image_name(
    base_prefix: str,
    matrix_values: dict[str, Any] | None = None,
    seed: int | None = None,
    batch_index: int | None = None,
    pack_name: str | None = None,
    max_length: int = 120,
    use_one_based_indexing: bool = True,
) -> str:
    """Build a safe, filesystem-compatible image name with human-readable identifiers."""
    # Start with sanitized base prefix
    safe_prefix = get_safe_filename(base_prefix)
    
    # Build identifier: prefer pack name over hash
    identifier = ""
    if pack_name and pack_name.strip():
        # Sanitize and truncate pack name to 10 chars max
        safe_pack = get_safe_filename(pack_name.strip())[:10]
        if safe_pack:
            identifier = safe_pack
    
    # Fallback to hash if no pack name
    if not identifier:
        hash_input_parts = [safe_prefix]
        if matrix_values:
            matrix_str = "_".join(f"{k}={v}" for k, v in sorted(matrix_values.items()))
            hash_input_parts.append(matrix_str)
        if seed is not None:
            hash_input_parts.append(f"seed={seed}")
        hash_input = "|".join(hash_input_parts)
        identifier = hashlib.md5(hash_input.encode("utf-8")).hexdigest()[:8]
    
    # Build batch suffix with 1-based indexing
    batch_suffix = ""
    if batch_index is not None:
        display_index = batch_index + 1 if use_one_based_indexing else batch_index
        batch_suffix = f"_batch{display_index}"
    
    # Calculate space: prefix + "_" + identifier + batch_suffix + ".png"
    reserved = len("_") + len(identifier) + len(batch_suffix) + len(".png")
    max_prefix_len = max_length - reserved
    
    if len(safe_prefix) > max_prefix_len:
        safe_prefix = safe_prefix[:max_prefix_len]
    
    # Build final name
    final_name = f"{safe_prefix}_{identifier}{batch_suffix}"
    
    return final_name
```

---

### Change 2: Update Caller in `pipeline_runner.py`

**File**: `src/pipeline/pipeline_runner.py`

**Line ~234**: Update txt2img filename generation
```python
# OLD
prompt_row = getattr(njr, "prompt_pack_row_index", 0) or 0
base_prefix = f"{stage.stage_name}_p{prompt_row:02d}_{stage.variant_id:02d}"
image_name = build_safe_image_name(
    base_prefix=base_prefix,
    matrix_values=matrix_values,
    seed=seed,
    max_length=100
)

# NEW
prompt_row = getattr(njr, "prompt_pack_row_index", 0) or 0
variant_id = stage.variant_id
pack_name = getattr(njr, "prompt_pack_name", None) or getattr(njr, "pack_name", None)

# 1-based indexing for human readability
base_prefix = f"{stage.stage_name}_p{prompt_row+1:02d}_v{variant_id+1:02d}"

image_name = build_safe_image_name(
    base_prefix=base_prefix,
    matrix_values=matrix_values,
    seed=seed,
    pack_name=pack_name,
    batch_index=None,  # Set later per-batch
    max_length=100
)
```

**Line ~310**: Update img2img filename generation (same pattern)
**Line ~404**: Update adetailer filename generation (same pattern)  
**Line ~494**: Update upscale filename generation (same pattern)

---

### Change 3: Update Executor Manifest Saving

**File**: `src/pipeline/executor.py`

**Line ~2989-2990**: Add batch number to txt2img manifests

**OLD**:
```python
manifest_dir = output_dir / "manifests"
manifest_dir.mkdir(exist_ok=True, parents=True)
manifest_name = f"{image_name}_txt2img"  # Missing batch number!
manifest_path = manifest_dir / f"{manifest_name}.json"
```

**NEW**:
```python
manifest_dir = output_dir / "manifests"
manifest_dir.mkdir(exist_ok=True, parents=True)

# Include batch number to prevent overwrites
# image_name already includes batch suffix (e.g., "txt2img_p01_v01_FantasyHer_batch1")
manifest_name = image_name  # Already has all needed info, no redundant suffix
manifest_path = manifest_dir / f"{manifest_name}.json"
```

**Repeat for**:
- Line ~3169 (img2img manifests)
- Line ~3450 (upscale manifests)
- Line ~1831 (adetailer manifests)

---

### Change 4: Add Collision Failsafe

**File**: `src/utils/file_io.py`

**New Function**:
```python
def get_unique_output_path(
    base_path: Path,
    max_attempts: int = 100
) -> Path:
    """
    Ensure output path is unique by appending _copy1, _copy2, etc. if needed.
    
    Args:
        base_path: Desired output path
        max_attempts: Maximum collision resolution attempts
    
    Returns:
        Unique path that doesn't exist
    
    Raises:
        ValueError: If max_attempts exceeded (indicates serious bug)
    """
    if not base_path.exists():
        return base_path
    
    logger = logging.getLogger(__name__)
    logger.warning(
        "[COLLISION] Output file already exists: %s (this indicates a filename generation bug)",
        base_path
    )
    
    stem = base_path.stem
    suffix = base_path.suffix
    parent = base_path.parent
    
    for i in range(1, max_attempts + 1):
        candidate = parent / f"{stem}_copy{i}{suffix}"
        if not candidate.exists():
            logger.warning("[COLLISION] Using unique filename: %s", candidate.name)
            return candidate
    
    raise ValueError(
        f"Could not find unique filename after {max_attempts} attempts for {base_path}. "
        "This indicates a serious filename generation bug."
    )
```

**Update Image Save Logic**:

**File**: `src/pipeline/executor.py`

**Lines where images are saved** (search for `Image.open` and `.save()`):

```python
# OLD
image_path = stage_dir / f"{image_name}.png"
image.save(image_path, "PNG")

# NEW
from src.utils.file_io import get_unique_output_path

image_path = stage_dir / f"{image_name}.png"
image_path = get_unique_output_path(image_path)  # Failsafe
image.save(image_path, "PNG")
```

**Repeat for**:
- txt2img stage (~line 2980)
- img2img stage (~line 3155)
- adetailer stage (~line 1820)
- upscale stage (~line 3435)

---

## Testing Plan

### Unit Tests

**File**: `tests/utils/test_filename_generation.py` (new)

```python
import pytest
from src.utils.file_io import build_safe_image_name


def test_one_based_indexing():
    """Verify 1-based indexing for batch numbers."""
    name = build_safe_image_name(
        base_prefix="txt2img_p01_v01",
        batch_index=0,  # Internal 0-based
        pack_name="TestPack"
    )
    assert "batch1" in name  # External 1-based
    assert "batch0" not in name


def test_pack_name_truncation():
    """Verify pack name truncated to 10 chars."""
    name = build_safe_image_name(
        base_prefix="txt2img_p01_v01",
        pack_name="VeryLongPromptPackName_v2.5"
    )
    # Should be truncated to ~10 chars
    parts = name.split("_")
    pack_part = parts[2]  # txt2img_p01_v01_<PACK>
    assert len(pack_part) <= 10


def test_pack_name_sanitization():
    """Verify special characters sanitized."""
    name = build_safe_image_name(
        base_prefix="txt2img_p01_v01",
        pack_name="Fantasy/Heroes:v2!"
    )
    # Should be safe filename
    assert "/" not in name
    assert ":" not in name
    assert "!" not in name


def test_fallback_to_hash_when_no_pack():
    """Verify hash used when pack name unavailable."""
    name = build_safe_image_name(
        base_prefix="txt2img_p01_v01",
        pack_name=None,
        seed=12345
    )
    # Should contain 8-char hex hash
    parts = name.split("_")
    hash_part = parts[2]
    assert len(hash_part) == 8
    assert all(c in "0123456789abcdef" for c in hash_part.lower())


def test_no_redundant_stage_suffix():
    """Verify stage name only appears once (prefix)."""
    name = build_safe_image_name(
        base_prefix="txt2img_p01_v01",
        pack_name="TestPack"
    )
    # Count occurrences of "txt2img"
    occurrences = name.count("txt2img")
    assert occurrences == 1, f"Expected 1 occurrence of 'txt2img', found {occurrences}"
```

**File**: `tests/utils/test_collision_failsafe.py` (new)

```python
import pytest
from pathlib import Path
from src.utils.file_io import get_unique_output_path


def test_no_collision_returns_original(tmp_path):
    """Verify original path returned when no collision."""
    test_file = tmp_path / "test.png"
    result = get_unique_output_path(test_file)
    assert result == test_file


def test_collision_appends_copy(tmp_path):
    """Verify _copy1 appended on collision."""
    test_file = tmp_path / "test.png"
    test_file.touch()  # Create collision
    
    result = get_unique_output_path(test_file)
    assert result.name == "test_copy1.png"
    assert not result.exists()


def test_multiple_collisions(tmp_path):
    """Verify _copy2, _copy3, etc. on multiple collisions."""
    test_file = tmp_path / "test.png"
    test_file.touch()
    (tmp_path / "test_copy1.png").touch()
    (tmp_path / "test_copy2.png").touch()
    
    result = get_unique_output_path(test_file)
    assert result.name == "test_copy3.png"


def test_max_attempts_exceeded(tmp_path):
    """Verify ValueError when max attempts exceeded."""
    test_file = tmp_path / "test.png"
    test_file.touch()
    
    # Create 100 collision files
    for i in range(1, 101):
        (tmp_path / f"test_copy{i}.png").touch()
    
    with pytest.raises(ValueError, match="Could not find unique filename"):
        get_unique_output_path(test_file, max_attempts=100)
```

### Integration Tests

**File**: `tests/pipeline/test_filename_convention.py` (new)

```python
import pytest
from pathlib import Path
from src.pipeline.job_models_v2 import NormalizedJobRecord
from src.pipeline.pipeline_runner import PipelineRunner


@pytest.mark.integration
def test_txt2img_batch_manifests_unique(tmp_path):
    """Verify each batch gets unique manifest filename."""
    # Setup NJR with batch_size=2
    njr = NormalizedJobRecord(
        job_id="test_job",
        prompt_pack_name="FantasyHeroes",
        prompt_pack_row_index=0,
        config={
            "txt2img": {
                "batch_size": 2,
                # ... other config
            }
        },
        stages=[...],
    )
    
    runner = PipelineRunner(...)
    result = runner.run(njr)
    
    # Check manifests
    manifest_dir = tmp_path / "manifests"
    manifests = list(manifest_dir.glob("*.json"))
    
    assert len(manifests) == 2, "Expected 2 manifests for batch_size=2"
    
    # Verify batch numbers in filenames
    names = [m.stem for m in manifests]
    assert any("batch1" in n for n in names)
    assert any("batch2" in n for n in names)


@pytest.mark.integration
def test_filename_matches_gui_indexing(tmp_path):
    """Verify filename prompt/variant numbers match GUI 1-based display."""
    njr = NormalizedJobRecord(
        job_id="test_job",
        prompt_pack_name="SciFiCity",
        prompt_pack_row_index=0,  # First prompt (internal 0-based)
        config={...},
        stages=[...],
    )
    
    runner = PipelineRunner(...)
    result = runner.run(njr)
    
    # Find generated image
    images = list((tmp_path / "txt2img").glob("*.png"))
    assert len(images) > 0
    
    first_image = images[0].stem
    
    # Verify 1-based indexing
    assert "p01" in first_image, "Expected p01 for first prompt (GUI shows 'Prompt 1')"
    assert "v01" in first_image, "Expected v01 for first variant"
    assert "batch1" in first_image, "Expected batch1 for first batch"
    
    # Verify pack name present
    assert "SciFiCity" in first_image or "SciFiCity"[:10] in first_image


@pytest.mark.integration
def test_no_redundant_stage_labels(tmp_path):
    """Verify stage name only appears once in filename."""
    njr = NormalizedJobRecord(...)
    runner = PipelineRunner(...)
    result = runner.run(njr)
    
    images = list((tmp_path / "txt2img").glob("*.png"))
    for image in images:
        # Count "txt2img" occurrences
        count = image.stem.count("txt2img")
        assert count == 1, f"Expected 1 'txt2img' in {image.name}, found {count}"
```

---

## Verification Criteria

### ✅ Success Criteria

1. **1-Based Indexing**
   - [ ] First prompt generates `p01` (not `p00`)
   - [ ] First variant generates `v01` (not `00`)
   - [ ] First batch generates `batch1` (not `batch0`)

2. **Pack Name Integration**
   - [ ] Pack name appears in filename (first 10 chars, sanitized)
   - [ ] Fallback to hash when pack name unavailable
   - [ ] Special characters properly sanitized

3. **No Redundant Labels**
   - [ ] Stage name appears once (prefix only)
   - [ ] No `_txt2img`, `_adetailer`, `_upscale` suffixes

4. **Manifest Batch Numbers**
   - [ ] txt2img manifests include batch number: `_batch1.json`, `_batch2.json`
   - [ ] img2img manifests include batch number
   - [ ] adetailer manifests include batch number
   - [ ] upscale manifests include batch number
   - [ ] No overwrites when batch_size > 1

5. **Collision Failsafe**
   - [ ] Duplicate filenames get `_copy1`, `_copy2`, etc.
   - [ ] Warning logged when collision occurs
   - [ ] ValueError raised if 100+ collisions

6. **Backward Compatibility**
   - [ ] Old test fixtures still work (0-based internally)
   - [ ] Existing tests pass (may need updates)
   - [ ] No breaking changes to NJR structure

### ❌ Failure Criteria

Any of:
- Batch manifests still overwriting (batch number missing)
- Prompt numbers don't match GUI (still 0-based)
- Hash appears instead of pack name (when pack name available)
- Redundant stage labels still present
- Files overwrite on collision (failsafe not working)
- Tests fail after changes

---

## Example Before/After

### Scenario: 2 prompts, 1 variant each, 2 batches per variant

**Pack Name**: "Fantasy_Medieval_Heroes_v2"

**Before** (current):
```
txt2img/
  txt2img_p00_00_a3f2b1c9_batch0_txt2img.png
  txt2img_p00_00_a3f2b1c9_batch1_txt2img.png
  txt2img_p01_00_b4c3d2e1_batch0_txt2img.png
  txt2img_p01_00_b4c3d2e1_batch1_txt2img.png

manifests/
  txt2img_p00_00_a3f2b1c9_txt2img.json        ← OVERWRITTEN (no batch number!)
  txt2img_p01_00_b4c3d2e1_txt2img.json        ← OVERWRITTEN (no batch number!)
```

**Issues**:
- ❌ `p00` doesn't match GUI "Prompt 1"
- ❌ Hash `a3f2b1c9` meaningless
- ❌ Redundant `_txt2img` suffix
- ❌ Manifests missing batch numbers (data loss!)

**After** (proposed):
```
txt2img/
  txt2img_p01_v01_FantasyMed_batch1.png
  txt2img_p01_v01_FantasyMed_batch2.png
  txt2img_p02_v01_FantasyMed_batch1.png
  txt2img_p02_v01_FantasyMed_batch2.png

manifests/
  txt2img_p01_v01_FantasyMed_batch1.json      ✅ Unique per batch
  txt2img_p01_v01_FantasyMed_batch2.json      ✅ Unique per batch
  txt2img_p02_v01_FantasyMed_batch1.json      ✅ Unique per batch
  txt2img_p02_v01_FantasyMed_batch2.json      ✅ Unique per batch
```

**Benefits**:
- ✅ `p01` matches GUI "Prompt 1"
- ✅ `FantasyMed` identifies source pack
- ✅ No redundant suffix
- ✅ All manifests preserved (no overwrites)

---

## Risk Assessment

### Low Risk Areas

✅ **New Utility Function**: `get_unique_output_path()` is additive, no existing code affected
✅ **Filename Changes**: Only affect new runs, no migration of existing files needed
✅ **Logging**: Collision warnings help identify bugs without breaking behavior

### Medium Risk Areas

⚠️ **Filename Convention Changes**: Downstream tools may expect old format
- **Mitigation**: Update all internal references, add tests

⚠️ **1-Based Indexing Logic**: Off-by-one errors possible
- **Mitigation**: Comprehensive unit tests, verify GUI alignment

⚠️ **Pack Name Extraction**: May be None/empty in some code paths
- **Mitigation**: Graceful fallback to hash, test all NJR construction sites

### High Risk Areas

❌ **Manifest Filename Changes**: If manifest loading depends on old format
- **Mitigation**: Verify manifest loading logic doesn't hardcode expectations
- **Check**: Search for manifest filename patterns in codebase

---

## Tech Debt Removed

✅ **Manifest Overwrite Bug**: Fixed critical data loss issue  
✅ **User Confusion**: Filenames now match GUI exactly  
✅ **Lost Context**: Pack name preserves traceability  
✅ **Visual Clutter**: Removed redundant labels  
✅ **Collision Risk**: Added failsafe for filename conflicts

**Net Tech Debt**: -5 issues

---

## Migration Plan

**Phase 1**: Implement core changes
- Update `build_safe_image_name()`
- Update callers in `pipeline_runner.py`
- Add collision failsafe

**Phase 2**: Fix manifest batch numbers
- Update all `executor.py` manifest save locations
- Verify batch numbers included

**Phase 3**: Testing
- Run unit tests
- Run integration tests
- Manual verification with real pack

**Phase 4**: Documentation
- Update CHANGELOG
- Update any docs referencing filenames
- Add migration note (old files unchanged)

---

## Dependencies

### Internal
- ✅ `src/pipeline/job_models_v2.py` - NJR has `prompt_pack_name` field
- ✅ `src/utils/file_io.py` - Existing `get_safe_filename()` helper
- ✅ `src/pipeline/pipeline_runner.py` - Caller of filename generation
- ✅ `src/pipeline/executor.py` - Manifest saving logic

### External
- None

---

## Timeline & Effort

| Task | Effort | Duration |
|------|--------|----------|
| Update `build_safe_image_name()` | 0.5 days | Day 1 AM |
| Update callers (4 sites in runner) | 0.5 days | Day 1 PM |
| Add collision failsafe | 0.5 days | Day 2 AM |
| Fix manifest batch numbers (4 sites) | 0.5 days | Day 2 PM |
| Unit tests | 0.5 days | Day 3 AM |
| Integration tests | 0.5 days | Day 3 PM |
| Manual verification | 0.5 days | Buffer |

**Total**: 3 days

---

## Approval & Sign-Off

**Planner**: GitHub Copilot (Assistant)  
**Executor**: TBD (Codex or Rob)  
**Reviewer**: Rob (Product Owner)

**Approval Status**: 🟡 Awaiting Rob's approval

---

## Next Steps

1. **Rob reviews this PR spec**
2. **Rob approves or requests changes**
3. **Implement Phase 1-4**
4. **Run tests**
5. **Manual verification**
6. **Merge to `cooking` branch**
7. **Monitor for issues**

---

**Document Status**: ✅ Complete  
**Ready for Implementation**: ✅ Yes (pending approval)  
**Estimated Completion**: 2025-12-28 (3 days from approval)
