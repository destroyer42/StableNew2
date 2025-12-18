# PR-GUI-001: Fix Prompt Pack Multi-Row Loading and Output Settings Sync

**Status:** READY FOR IMPLEMENTATION  
**Priority:** HIGH  
**Type:** Bug Fix  
**Estimated Effort:** 3-5 hours

---

## Problem Statement

Three critical issues prevent proper prompt pack functionality:

1. **Only first prompt used from multi-prompt packs** - Pack with 10 prompts creates only 1 job
2. **Batch Size field doesn't load from pack config** - "Load Config" button skips output settings
3. **Apply Config doesn't save output settings** - "Apply Config" button doesn't capture batch_size, etc.

**Impact:** Users cannot use multi-prompt packs effectively, and output settings don't persist across sessions.

---

## Root Cause Analysis

### Issue 1: Single Prompt Extraction

**File:** `src/controller/app_controller.py:801-809`

```python
def _read_pack_prompts(self, pack: PromptPackInfo) -> tuple[str, str]:
    try:
        prompts = read_prompt_pack(pack.path)  # ✓ Reads all 10 prompts
    except Exception:
        prompts = []
    if not prompts:
        return "", ""
    first = prompts[0]  # ❌ ONLY RETURNS FIRST
    return first.get("positive", "").strip(), first.get("negative", "").strip()
```

**Problem:** Method returns only first prompt, ignoring remaining 9.

### Issue 2: Missing Output Panel Sync (Load)

**File:** `src/controller/app_controller.py:3429-3465`

`on_pipeline_pack_load_config()` applies config to:
- ✓ Stage cards (txt2img, img2img, upscale, adetailer)
- ✓ Randomizer panel
- ❌ **Output settings panel** (missing)

### Issue 3: Missing Output Panel Query (Save)

**File:** `src/controller/app_controller.py:3505-3547`

`on_pipeline_pack_apply_config()` gathers config from:
- ✓ Stage cards
- ✓ Randomizer panel
- ❌ **Output settings panel** (missing)

---

## Solution Design

### Fix 1: Iterate Over All Prompts

**Location:** `src/controller/app_controller.py:on_pipeline_add_packs_to_job()`

**Change:** Replace single `_read_pack_prompts()` call with iteration over all prompt rows.

**Logic:**
```python
for pack_id in pack_ids:
    pack = self._find_pack_by_id(pack_id)
    all_prompts = read_prompt_pack(pack.path)  # Get all prompts
    
    for row_index, prompt_row in enumerate(all_prompts):
        entry = PackJobEntry(
            pack_id=pack_id,
            prompt_text=prompt_row.get("positive", ""),
            negative_prompt_text=prompt_row.get("negative", ""),
            pack_row_index=row_index,  # ← Set row index
            # ... other fields
        )
        entries.append(entry)
```

### Fix 2: Load Config → Output Panel

**Location:** `src/controller/app_controller.py:on_pipeline_pack_load_config()`

**Change:** After applying to stage cards, extract pipeline section and update output panel.

**Logic:**
```python
pipeline_section = pack_config.get("pipeline", {})
output_panel = getattr(self.main_window, "output_settings_panel_v2", None)
if output_panel and hasattr(output_panel, "apply_from_overrides"):
    output_overrides = {
        "batch_size": pipeline_section.get("images_per_prompt", 1),
        "output_dir": pipeline_section.get("output_dir", "output"),
        "filename_pattern": pipeline_section.get("filename_pattern", "{seed}"),
        # ... other output settings
    }
    output_panel.apply_from_overrides(output_overrides)
```

### Fix 3: Apply Config ← Output Panel

**Location:** `src/controller/app_controller.py:on_pipeline_pack_apply_config()`

**Change:** Before saving, query output panel for current widget values.

**Logic:**
```python
output_panel = getattr(self.main_window, "output_settings_panel_v2", None)
if output_panel and hasattr(output_panel, "get_output_overrides"):
    output_overrides = output_panel.get_output_overrides()
    if "pipeline" not in current_config:
        current_config["pipeline"] = {}
    current_config["pipeline"]["images_per_prompt"] = output_overrides.get("batch_size", 1)
    current_config["pipeline"]["output_dir"] = output_overrides.get("output_dir", "output")
    # ... map other fields
```

---

## Implementation Plan

### Step 1: Update Multi-Prompt Iteration

**File:** `src/controller/app_controller.py`

**Method:** `on_pipeline_add_packs_to_job()`

**Lines:** ~3537-3569

**Actions:**
1. Remove call to `_read_pack_prompts()`
2. Call `read_prompt_pack(pack.path)` directly to get all prompts
3. Add `for` loop iterating over `enumerate(all_prompts)`
4. Inside loop, create `PackJobEntry` with `pack_row_index=row_index`
5. Preserve existing `config_snapshot`, `stage_flags`, `randomizer_metadata` logic

### Step 2: Add Output Panel Load Sync

**File:** `src/controller/app_controller.py`

**Method:** `on_pipeline_pack_load_config()`

**Lines:** ~3429-3465 (after existing stage card application)

**Actions:**
1. Extract `pipeline_section = pack_config.get("pipeline", {})`
2. Get panel reference: `output_panel = getattr(self.main_window, "output_settings_panel_v2", None)`
3. Check method exists: `hasattr(output_panel, "apply_from_overrides")`
4. Build `output_overrides` dict mapping pipeline keys to output panel keys
5. Call `output_panel.apply_from_overrides(output_overrides)`

### Step 3: Add Output Panel Save Query

**File:** `src/controller/app_controller.py`

**Method:** `on_pipeline_pack_apply_config()`

**Lines:** ~3505-3547 (before saving to pack)

**Actions:**
1. Get panel reference: `output_panel = getattr(self.main_window, "output_settings_panel_v2", None)`
2. Check method exists: `hasattr(output_panel, "get_output_overrides")`
3. Call `output_overrides = output_panel.get_output_overrides()`
4. Ensure `current_config["pipeline"]` exists
5. Map output panel keys to pipeline section keys
6. Update `current_config["pipeline"]` with mapped values

### Step 4: Add Validation Logging

**File:** `src/controller/app_controller.py`

**All three methods**

**Actions:**
1. Add debug log showing number of prompts loaded from pack
2. Add debug log showing which output settings were applied/gathered
3. Add debug log showing final PackJobEntry count

---

## Allowed Files

| File | Purpose | Lines to Modify |
|------|---------|-----------------|
| `src/controller/app_controller.py` | Main controller logic | 3537-3569, 3429-3465, 3505-3547 |

## Forbidden Files

**DO NOT MODIFY:**
- `src/gui/output_settings_panel_v2.py` - Already has required methods
- `src/utils/file_io.py` - `read_prompt_pack()` works correctly
- `src/utils/config_manager.py` - File I/O works correctly
- `src/models/job_models.py` - PackJobEntry already has `pack_row_index` field
- Any pipeline execution files

---

## Testing Requirements

### Unit Tests

**File:** `tests/test_app_controller_pack_config.py` (new)

1. **Test multi-prompt iteration:**
   ```python
   def test_add_pack_with_10_prompts_creates_10_entries():
       # Given: Pack file with 10 prompts
       # When: on_pipeline_add_packs_to_job([pack_id])
       # Then: app_state.job_draft.packs has 10 PackJobEntry objects
       # And: Each has pack_row_index 0-9
       # And: Each has distinct prompt_text
   ```

2. **Test Load Config updates batch_size:**
   ```python
   def test_load_config_updates_output_panel():
       # Given: Pack config with images_per_prompt=5
       # When: on_pipeline_pack_load_config(pack_id)
       # Then: output_panel.batch_size_var.get() == "5"
   ```

3. **Test Apply Config saves batch_size:**
   ```python
   def test_apply_config_saves_output_settings():
       # Given: output_panel.batch_size_var.set("7")
       # When: on_pipeline_pack_apply_config([pack_id])
       # Then: Saved JSON has pipeline.images_per_prompt == 7
   ```

### Integration Test

**File:** `tests/integration/test_pack_config_roundtrip.py` (new)

```python
def test_pack_config_full_roundtrip():
    """Test save → load → save cycle preserves all settings."""
    # 1. Set GUI widgets (output panel + stage cards)
    # 2. Apply config to pack
    # 3. Clear GUI widgets
    # 4. Load config from pack
    # 5. Verify all widgets restored
    # 6. Apply config again
    # 7. Verify JSON unchanged
```

### Manual Testing Checklist

- [ ] Load pack with 10 prompts
- [ ] Preview shows "Jobs: 10" (not "Jobs: 1")
- [ ] Set batch_size=3 in GUI
- [ ] Click "Apply Config"
- [ ] Verify pack JSON has `"images_per_prompt": 3`
- [ ] Set batch_size=1 in GUI
- [ ] Click "Load Config"
- [ ] Verify GUI shows batch_size=3
- [ ] Click "Add to Job"
- [ ] Queue 10 jobs (not 1)
- [ ] Run queue
- [ ] Verify 30 total images generated (10 prompts × 3 batch)

---

## Risk Mitigation

| Risk | Mitigation |
|------|------------|
| Breaking existing single-prompt packs | Iteration handles 1-prompt packs correctly (loop once) |
| `output_settings_panel_v2` not found | Defensive `getattr()` + `hasattr()` checks |
| Old pack configs without `pipeline` section | Use `.get()` with defaults, create section if missing |
| `pack_row_index` field doesn't exist | Field exists in `PackJobEntry` model (confirmed) |

---

## Success Criteria

1. ✅ Pack with 10 prompts creates 10 jobs
2. ✅ Each job uses different prompt from pack
3. ✅ Batch size multiplies job count correctly
4. ✅ "Load Config" populates all output settings
5. ✅ "Apply Config" saves all output settings
6. ✅ Round-trip (save → load) preserves all values
7. ✅ Existing single-prompt packs still work
8. ✅ No regressions in stage card config sync

---

## Rollback Plan

If issues arise post-deployment:

1. Revert `src/controller/app_controller.py` to previous commit
2. Clear user's pack config cache (instruct users to delete `packs/*.json` configs)
3. Fall back to single-prompt behavior

---

## Documentation Updates

**File:** `docs/PROMPT_PACK_LIFECYCLE_v2.6.md`

**Section:** "Adding Packs to Job Queue"

**Add:**
- Explanation of multi-prompt iteration
- How `pack_row_index` maps to prompt rows
- Batch size multiplier behavior

---

## Dependencies

None - all required infrastructure exists.

---

## Estimated Timeline

| Phase | Duration |
|-------|----------|
| Code implementation | 2 hours |
| Unit tests | 1 hour |
| Integration tests | 1 hour |
| Manual testing | 30 min |
| Code review | 30 min |
| **Total** | **5 hours** |

---

## Approval Required

- [x] Technical design reviewed
- [ ] Code changes implemented
- [ ] Tests passing
- [ ] Manual testing complete
- [ ] Ready for merge

---

**PR Created:** December 17, 2025  
**Author:** GitHub Copilot (Sonnet 4.5)  
**Reviewer:** TBD
