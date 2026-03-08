# D-GUI-003: Job History Panel Display Issues

**Status**: Discovery  
**Priority**: High  
**Impact**: Job history unusable for tracking completed jobs  
**Estimated Implementation**: 4-5 hours

---

## Problem Statement

The Job History panel has multiple critical display issues making it unusable:

1. **Prompt vs Pack Name**: Some rows show full prompt text, others show pack name, some show hash
2. **Duration Alternates**: Every other row shows wrong duration (1s vs 1m 28s pattern)
3. **Seed Shows "Random"**: Displays "Random" instead of actual seed number used
4. **Output Folder Incorrect**: Path/name doesn't match actual output location
5. **Status Terminology**: Shows "Completed" instead of "Success"/"Failed"
6. **No Scroll Bar**: Can't scroll through history

### Current Display (Broken)
```
┌─ Job History ──────────────────────────────────────────────┐
│ Name               | Duration | Seed   | Output   | Status │
├────────────────────┼──────────┼────────┼──────────┼────────┤
│ a beautiful woman… | 1s       | Random | wrong    | Complet│ ❌
│ abc123def456…      | 1m 28s   | Random | wrong    | Complet│ ❌
│ A_Beautiful_Test   | 1s       | Random | wrong    | Complet│ ❌
│ xyz789…            | 1m 28s   | Random | wrong    | Complet│ ❌
└────────────────────────────────────────────────────────────┘
[No scroll bar visible]
```

### Expected Display (Fixed)
```
┌─ Job History ──────────────────────────────────────────────────────┐
│ Pack Name        | Row | V | B | Duration | Seed       | Output       | Status  │
├──────────────────┼─────┼───┼───┼──────────┼────────────┼──────────────┼─────────┤
│ A_Beautiful_Test | 3   | 1 | 1 | 1m 28s   | 1234567890 | 20251226_... | Success │
│ A_Beautiful_Test | 3   | 2 | 1 | 1m 32s   | 9876543210 | 20251226_... | Success │
│ Medieval_Heroes  | 1   | 1 | 1 | 2m 15s   | 5555555555 | 20251226_... | Success │
│ Test_Pack_Error  | 2   | 1 | 1 | 15s      | 1111111111 | 20251226_... | Failed  │
└────────────────────────────────────────────────────────────────────────────────┘
                                                               [Scroll bar visible]
```

---

## Root Cause Analysis

### Issue 1: Prompt vs Pack Name vs Hash

**Problem**: Inconsistent "Name" column data

**Likely causes**:
1. History records from different sources (old format vs new format)
2. Some jobs lack prompt_pack_name field
3. Falling back to prompt text or job_id

**Expected logic**:
```python
# PRIORITY ORDER:
1. prompt_pack_name (if available)
2. job_id (if no pack name)
3. Never show full prompt text (too long)
4. Never show hash unless nothing else available
```

**File**: Check how history records are created and what fields are stored.

### Issue 2: Duration Alternates Every Other Row

**Pattern**: 1s, 1m 28s, 1s, 1m 28s...

**Hypothesis**:
- Two different duration fields being read alternately
- Or duration calculation is wrong for every other row
- Or data corruption in history file

**Likely causes**:
1. **Row index parity bug**: 
   ```python
   # WRONG:
   if row_index % 2 == 0:
       duration = short_duration  # Wrong value
   else:
       duration = actual_duration
   ```

2. **Field name confusion**:
   ```python
   # Multiple duration fields?
   record.get("duration")         # Wrong
   record.get("stage_duration")   # Wrong
   record.get("total_duration")   # Correct
   ```

3. **History file corruption**: Two record formats mixed

### Issue 3: Seed Shows "Random" Instead of Number

**Problem**: Not displaying actual seed used

**Likely cause**:
```python
# CURRENT (WRONG):
seed = record.get("seed", -1)
if seed == -1:
    display_seed = "Random"
else:
    display_seed = str(seed)

# SHOULD USE final_seed from manifest:
seed = record.get("final_seed") or record.get("actual_seed") or -1
if seed == -1:
    display_seed = "Random"
else:
    display_seed = str(seed)
```

**Related to**: D-MANIFEST-001 (seed tracking enhancement)

### Issue 4: Output Folder Path Incorrect

**Problem**: Path doesn't match actual output location

**Expected format**: `20251226_063855_A_Beautiful_Test`

**Possible issues**:
1. Using job_id instead of run_dir name
2. Using old folder structure
3. Path field not populated in history record

**History record should store**:
```json
{
  "output_dir": "output/20251226_063855_A_Beautiful_Test",
  "run_id": "20251226_063855_A_Beautiful_Test"
}
```

### Issue 5: Status "Completed" vs "Success"/"Failed"

**Problem**: All jobs show "Completed" regardless of outcome

**Expected**:
- Job finished successfully → "Success"
- Job finished with error → "Failed"
- Job was cancelled → "Cancelled"

**Likely code**:
```python
# CURRENT:
status = "Completed"  # Always the same

# SHOULD BE:
if record.get("error"):
    status = "Failed"
elif record.get("cancelled"):
    status = "Cancelled"
else:
    status = "Success"
```

### Issue 6: No Scroll Bar

**Problem**: Can't scroll through history when many entries

**Likely causes**:
1. Treeview not placed in scrollable frame
2. Scrollbar widget missing
3. Scrollbar not attached to treeview

**Fix**:
```python
# Create treeview with scrollbar
tree_frame = ttk.Frame(parent)
scrollbar = ttk.Scrollbar(tree_frame, orient="vertical")
tree = ttk.Treeview(tree_frame, yscrollcommand=scrollbar.set)
scrollbar.configure(command=tree.yview)

# Grid layout
tree.grid(row=0, column=0, sticky="nsew")
scrollbar.grid(row=0, column=1, sticky="ns")
tree_frame.grid_rowconfigure(0, weight=1)
tree_frame.grid_columnconfigure(0, weight=1)
```

---

## Investigation Checklist

### 1. Read Job History Panel Source

**File**: `src/gui/panels_v2/job_history_panel_v2.py` (or similar)

**Find**:
- [ ] Treeview creation code
- [ ] Column definitions
- [ ] Data population logic
- [ ] Scrollbar setup (or lack thereof)

### 2. Check History Record Structure

**File**: `src/history/history_record.py`

**Verify fields**:
- [ ] `prompt_pack_name: str`
- [ ] `job_id: str`
- [ ] `duration: int` (in ms or seconds?)
- [ ] `seed: int` or `final_seed: int`
- [ ] `output_dir: str` or `run_id: str`
- [ ] `status: str` or `error: str | None`

### 3. Check History Writer

**File**: `src/history/history_writer.py` or similar

**Verify**:
- [ ] All fields being written to history file
- [ ] Duration calculated correctly
- [ ] Seed captured from job result
- [ ] Status determined from job outcome

### 4. Check History Reader

**File**: Job history service or panel code

**Verify**:
- [ ] Reading correct fields from history records
- [ ] Field name mapping correct
- [ ] Default values appropriate

---

## Implementation Plan

### Phase 1: Fix Name Column (45 minutes)

**File**: `src/gui/panels_v2/job_history_panel_v2.py`

**1.1. Update display logic**:
```python
def _get_display_name(self, record: dict) -> str:
    """Get appropriate display name for history record."""
    # Priority: pack name > job_id > fallback
    pack_name = record.get("prompt_pack_name")
    if pack_name:
        return pack_name
    
    job_id = record.get("job_id")
    if job_id:
        return job_id[:12]  # Truncate if too long
    
    return "Unknown Job"
```

**1.2. Add row/variant/batch columns**:
```python
# Modify treeview columns
columns = ("name", "row", "variant", "batch", "duration", "seed", "output", "status")

# Populate new columns
tree.insert("", "end", values=(
    display_name,
    record.get("prompt_pack_row_index", "?"),
    record.get("variant_index", 0) + 1,  # 1-based
    record.get("batch_index", 0) + 1,    # 1-based
    duration_str,
    seed_str,
    output_str,
    status_str,
))
```

### Phase 2: Fix Duration Bug (1 hour)

**2.1. Investigate history file**:
```bash
# Check actual history records
cat data/job_history.jsonl | jq '.duration'
# Look for pattern in duration values
```

**2.2. Identify field confusion**:
```python
# Check all possible duration fields
possible_fields = [
    "duration",
    "total_duration",
    "elapsed_time",
    "stage_duration_ms",
]

# Use correct field consistently
duration_ms = record.get("total_duration_ms") or record.get("duration") or 0
```

**2.3. Remove any row-index based logic**:
```python
# Search for:
if idx % 2 == 0:  # ❌ WRONG - remove this
    
# Should always use same field:
duration = self._parse_duration(record)
```

### Phase 3: Fix Seed Display (30 minutes)

**File**: `src/gui/panels_v2/job_history_panel_v2.py`

```python
def _get_seed_display(self, record: dict) -> str:
    """Get seed for display, prioritizing final_seed."""
    # Try manifest structure first (D-MANIFEST-001)
    seeds = record.get("seeds", {})
    if isinstance(seeds, dict):
        seed = seeds.get("final_seed") or seeds.get("actual_seed")
        if seed and seed != -1:
            return str(seed)
    
    # Fall back to legacy fields
    seed = record.get("final_seed") or record.get("actual_seed") or record.get("seed") or -1
    
    if seed == -1:
        return "Random"
    else:
        return str(seed)
```

### Phase 4: Fix Output Folder Path (30 minutes)

**4.1. Ensure history records include output path**:

**File**: `src/history/history_writer.py` or where records are created

```python
def write_history_record(self, job_result: dict):
    record = {
        # ... other fields
        "output_dir": job_result.get("output_dir"),  # Full path
        "run_id": job_result.get("run_id"),          # Folder name
        "output_folder_name": Path(job_result["output_dir"]).name,  # Just the name
    }
```

**4.2. Display in history panel**:
```python
def _get_output_display(self, record: dict) -> str:
    """Get output folder for display."""
    # Show just the folder name, not full path
    folder_name = record.get("output_folder_name")
    if folder_name:
        return folder_name
    
    # Fall back to extracting from full path
    output_dir = record.get("output_dir")
    if output_dir:
        return Path(output_dir).name
    
    return "Unknown"
```

### Phase 5: Fix Status Display (30 minutes)

**File**: `src/gui/panels_v2/job_history_panel_v2.py`

```python
def _get_status_display(self, record: dict) -> str:
    """Determine status: Success, Failed, or Cancelled."""
    # Check for explicit status field first
    status = record.get("status", "").lower()
    
    if status in ("success", "completed") and not record.get("error"):
        return "Success"
    elif status in ("failed", "error") or record.get("error"):
        return "Failed"
    elif status in ("cancelled", "canceled"):
        return "Cancelled"
    elif record.get("cancelled"):
        return "Cancelled"
    else:
        # Default: if completed without error = success
        return "Success"
```

### Phase 6: Add Scroll Bar (30 minutes)

**File**: `src/gui/panels_v2/job_history_panel_v2.py`

**6.1. Find treeview creation**:
```python
# CURRENT (likely no scrollbar):
self.tree = ttk.Treeview(parent, columns=columns)
self.tree.pack(fill="both", expand=True)
```

**6.2. Add scrollbar**:
```python
# FIXED:
# Create container frame
tree_container = ttk.Frame(parent)
tree_container.pack(fill="both", expand=True)

# Create scrollbar
scrollbar = ttk.Scrollbar(tree_container, orient="vertical")

# Create treeview with scrollbar
self.tree = ttk.Treeview(
    tree_container,
    columns=columns,
    yscrollcommand=scrollbar.set
)

# Configure scrollbar
scrollbar.configure(command=self.tree.yview)

# Layout with grid for precise control
self.tree.grid(row=0, column=0, sticky="nsew")
scrollbar.grid(row=0, column=1, sticky="ns")

# Configure weights for resizing
tree_container.grid_rowconfigure(0, weight=1)
tree_container.grid_columnconfigure(0, weight=1)
```

### Phase 7: Testing (1 hour)

**Test Case 1: History Records**
- Run 5 jobs of different types
- Check history file has all fields
- Verify duration values are consistent

**Test Case 2: Display**
- Open history panel
- Verify all columns show correct data
- No "Random" seeds (should show numbers)
- Output folders match actual folders
- Status shows Success/Failed

**Test Case 3: Scrolling**
- Add 20+ jobs to history
- Verify scrollbar appears
- Test scrolling works
- Test scrollwheel

**Test Case 4: Edge Cases**
- Job that failed
- Job that was cancelled
- Job with no pack name
- Job with very long name

---

## File Modifications Required

### Primary File
**`src/gui/panels_v2/job_history_panel_v2.py`**
- Update name column logic
- Add row/variant/batch columns
- Fix duration field usage
- Fix seed display logic
- Fix output folder display
- Fix status determination
- Add scrollbar to treeview

### Secondary Files
**`src/history/history_writer.py`**
- Ensure all required fields written
- Add output_folder_name field
- Capture final_seed correctly

**`src/history/history_record.py`**
- Document expected fields
- Add type hints

---

## Success Criteria

✅ **Name column consistent**:
- Always shows pack name if available
- Shows job_id if no pack
- Never shows full prompt or random hash

✅ **Duration accurate**:
- All rows show correct duration
- No alternating pattern
- Format: "1m 28s" or "45s"

✅ **Seed displays actual number**:
- Shows final seed used by SD
- Only shows "Random" if truly random

✅ **Output folder correct**:
- Matches actual folder name
- Format: "20251226_HHMMSS_PackName"

✅ **Status meaningful**:
- "Success" for successful jobs
- "Failed" for errors
- "Cancelled" if user cancelled

✅ **Scrollbar works**:
- Appears when needed
- Scrollwheel works
- Drag scrollbar works

✅ **Additional columns useful**:
- Row number shows prompt index
- Variant shows v1, v2, etc.
- Batch shows b1, b2, etc.

---

## Testing Strategy

### Unit Tests
```python
def test_status_determination():
    assert get_status({"error": None}) == "Success"
    assert get_status({"error": "boom"}) == "Failed"
    assert get_status({"cancelled": True}) == "Cancelled"

def test_seed_display():
    assert get_seed_display({"final_seed": 123}) == "123"
    assert get_seed_display({"seed": -1}) == "Random"
```

### Manual Testing
1. Run various jobs
2. Open history panel
3. Verify each field
4. Test scrolling
5. Test with 50+ jobs

---

## Risk Assessment

**Low Risk**:
- Mostly display logic
- No data loss risk
- Easy to test visually

**Potential Issues**:
- History file format may vary (old vs new records)
- Need backward compatibility

---

## Dependencies

**Requires**:
- Complete history records with all fields
- Related to D-MANIFEST-001 (seed tracking)

**Enables**:
- Useful job history
- Debugging completed jobs
- Learning from past runs

---

## Next Steps

1. ✅ Create this discovery document
2. ⏳ Read `job_history_panel_v2.py`
3. ⏳ Inspect actual history file (job_history.jsonl)
4. ⏳ Identify duration bug root cause
5. ⏳ Implement fixes phase by phase
6. ⏳ Test with real history data
