# D-GUI-002: Running Job Panel Display Issues

**Status**: Discovery  
**Priority**: High  
**Impact**: User cannot monitor running job state accurately  
**Estimated Implementation**: 3-4 hours

---

## Problem Statement

The Running Job Panel has multiple display and UX issues preventing users from monitoring job execution effectively:

1. **Missing Seed Display**: Seed number not shown
2. **Stage Display Incorrect**: Shows all stages (txt2img → adetailer) instead of current stage
3. **Version/Batch Index Off-by-One**: Shows v0/b0 instead of v1/b1 (should be 1-based)
4. **Status Always "Idle"**: Shows "Idle" even when job is actively running
5. **Mystery Grey Box**: Unknown grey textfield/box between Seed and Status fields
6. **Confusing Button Labels**: "pause", "cancel", "cancel queue" → should be "Pause Job", "Cancel Job"
7. **Misplaced Cancel Queue Button**: "Cancel Queue" belongs in Queue panel, not Running Job panel

### Current Display (Broken)
```
┌─ Running Job ─────────────────────────┐
│ Job: A_Beautiful_Test [v0/b0]         │
│ Stages: txt2img → adetailer           │ ❌ Shows all stages
│ Seed: [no value shown]                │ ❌ Missing seed
│ [grey box]                            │ ❌ Unknown purpose
│ Status: Idle                          │ ❌ Wrong - should be "Running"
│                                       │
│ [pause] [cancel] [cancel queue]       │ ❌ Poor labels, wrong button
└───────────────────────────────────────┘
```

### Expected Display (Fixed)
```
┌─ Running Job ─────────────────────────┐
│ Job: A_Beautiful_Test [v1/b1]         │ ✅ 1-based indexing
│ Current Stage: txt2img (1/2)          │ ✅ Shows current + progress
│ Seed: 1234567890                      │ ✅ Actual seed displayed
│ Progress: 45% (ETA: 2m 15s)           │ ✅ Grey box shows progress
│ Status: Running                       │ ✅ Accurate status
│                                       │
│ [Pause Job] [Cancel Job]              │ ✅ Clear labels, queue button removed
└───────────────────────────────────────┘
```

---

## Root Cause Analysis

### Issue 1: Seed Not Displayed

**File**: `src/gui/panels_v2/running_job_panel_v2.py`

**Hypothesis**: 
- Panel may not have a seed label
- Or seed label not being updated with job data
- UnifiedJobSummary may not include seed field

**Investigation**:
```python
# Check if seed label exists
# Check _update_display() method
# Verify UnifiedJobSummary has seed field
```

### Issue 2: Shows All Stages Instead of Current

**Problem**: Displaying `njr.stage_chain_labels` (all stages) instead of current executing stage

**Expected**: 
- `"Current Stage: txt2img (1/3)"` 
- `"Current Stage: adetailer (2/3)"`

**Likely Code**:
```python
# CURRENT (WRONG):
stage_text = " → ".join(job.stage_chain_labels)  # Shows all stages

# SHOULD BE:
current_stage_index = self._get_current_stage_index()
current_stage = job.stage_chain_labels[current_stage_index]
total_stages = len(job.stage_chain_labels)
stage_text = f"{current_stage} ({current_stage_index + 1}/{total_stages})"
```

**Challenge**: How to track which stage is currently executing?
- Pipeline callbacks may need to report current stage
- Or infer from progress events

### Issue 3: v0/b0 Instead of v1/b1

**Problem**: Using 0-based `variant_index` and `batch_index` directly

**Fix**: Add 1 when displaying:
```python
# CURRENT:
variant_text = f"v{job.variant_index}/b{job.batch_index}"  # v0/b0

# SHOULD BE:
variant_text = f"v{job.variant_index + 1}/b{job.batch_index + 1}"  # v1/b1
```

### Issue 4: Status Shows "Idle" When Running

**Problem**: Status field not being updated from job state

**Likely causes**:
- `job.status` field not set correctly
- Status label not bound to job status updates
- Pipeline not sending status updates to GUI

**Expected flow**:
1. Job starts → status = "Running"
2. Job completes → status = "Completed"
3. Job errors → status = "Failed"
4. Job paused → status = "Paused"

### Issue 5: Mystery Grey Box

**Investigation needed**: 
- Check running_job_panel_v2.py line ~200-300
- Look for unlabeled Text/Entry widget
- Likely intended for progress or stage info

**Possibilities**:
1. Progress bar (should show %)
2. Stage info (should show current stage)
3. ETA display (should show time remaining)
4. Unused/broken widget (remove if no purpose)

### Issue 6: Button Label Confusion

**Current**: `[pause] [cancel] [cancel queue]`  
**Fixed**: `[Pause Job] [Cancel Job]` (remove cancel queue)

**File**: `src/gui/panels_v2/running_job_panel_v2.py` (button creation code)

```python
# CURRENT:
pause_btn = ttk.Button(frame, text="pause", ...)
cancel_btn = ttk.Button(frame, text="cancel", ...)
cancel_queue_btn = ttk.Button(frame, text="cancel queue", ...)  # ❌ Wrong panel

# FIXED:
pause_btn = ttk.Button(frame, text="Pause Job", ...)
cancel_btn = ttk.Button(frame, text="Cancel Job", ...)
# Remove cancel_queue_btn - it belongs in Queue panel
```

---

## Investigation Checklist

### 1. Read Running Job Panel Source

**File**: `src/gui/panels_v2/running_job_panel_v2.py`

**Find**:
- [ ] Line where labels are created (seed_label, status_label, etc.)
- [ ] `_update_display()` or `update_job()` method
- [ ] Button creation code
- [ ] Mystery grey widget definition

### 2. Check UnifiedJobSummary Fields

**File**: `src/pipeline/job_models_v2.py`

**Verify fields exist**:
- [ ] `seed: int | None`
- [ ] `current_stage: str` or way to determine it
- [ ] `status: str` (should be "Running", "Completed", etc.)
- [ ] `variant_index: int`
- [ ] `batch_index: int`

### 3. Check Pipeline Status Updates

**File**: `src/pipeline/pipeline_runner.py`

**Verify callbacks**:
- [ ] Are stage change events sent to GUI?
- [ ] Are status updates sent when job starts/completes?
- [ ] Is seed information passed to GUI?

### 4. Check Controller Integration

**Files**: `src/controller/app_controller.py`, `src/controller/pipeline_controller.py`

**Verify**:
- [ ] `_set_running_job()` passes complete job info
- [ ] Status updates trigger GUI refresh
- [ ] Current stage tracked somewhere

---

## Implementation Plan

### Phase 1: Add Seed Display (30 minutes)

**File**: `src/gui/panels_v2/running_job_panel_v2.py`

**1.1. Add seed label** (if missing):
```python
# In __init__ or _build_ui():
self.seed_label = ttk.Label(info_frame, text="Seed: --")
self.seed_label.grid(row=X, column=0, sticky="w")
```

**1.2. Update seed in _update_display()**:
```python
def _update_display(self):
    if self._current_job:
        # Get seed from UnifiedJobSummary or NJR
        seed = getattr(self._current_job, 'seed', None)
        if seed is not None and seed != -1:
            self.seed_label.configure(text=f"Seed: {seed}")
        else:
            self.seed_label.configure(text="Seed: Random")
```

### Phase 2: Fix Stage Display (1 hour)

**2.1. Track current stage index**:

Need pipeline to report which stage is executing. Options:

**Option A**: Add to UnifiedJobSummary
```python
@dataclass
class UnifiedJobSummary:
    current_stage_index: int = 0
    stage_chain_labels: list[str]
```

**Option B**: Infer from progress events
```python
# Controller tracks: self._current_stage_index = 0
# Pipeline callbacks increment it when stage changes
```

**2.2. Update display code**:
```python
def _update_display(self):
    if self._current_job:
        stages = self._current_job.stage_chain_labels
        current_idx = getattr(self._current_job, 'current_stage_index', 0)
        
        if stages and current_idx < len(stages):
            current_stage = stages[current_idx]
            total = len(stages)
            stage_text = f"Current Stage: {current_stage} ({current_idx + 1}/{total})"
        else:
            stage_text = "Stage: " + " → ".join(stages)
        
        self.stage_label.configure(text=stage_text)
```

### Phase 3: Fix v0/b0 → v1/b1 (15 minutes)

**File**: `src/gui/panels_v2/running_job_panel_v2.py`

```python
def _update_display(self):
    if self._current_job:
        # Display 1-based indices
        variant_display = self._current_job.variant_index + 1
        batch_display = self._current_job.batch_index + 1
        
        variant_text = f"v{variant_display}/b{batch_display}"
        # Update label with variant_text
```

### Phase 4: Fix Status Display (30 minutes)

**4.1. Ensure status field updated**:

**File**: `src/controller/app_controller.py` or `pipeline_controller.py`

```python
def _set_running_job(self, job: Job):
    njr = getattr(job, "_normalized_record", None)
    if njr:
        summary = UnifiedJobSummary.from_normalized_record(njr)
        # Ensure status reflects actual job state
        if job.status == JobStatus.RUNNING:
            summary.status = "Running"  # Override if needed
        
        self.app_state.set_running_job(summary)
```

**4.2. Update panel display**:
```python
def _update_display(self):
    if self._current_job:
        status = self._current_job.status or "Unknown"
        self.status_label.configure(text=f"Status: {status}")
```

### Phase 5: Investigate/Fix Grey Box (30 minutes)

**5.1. Find the widget**:
```python
# Search running_job_panel_v2.py for:
# - tk.Text() without label
# - ttk.Entry() between seed and status
# - Frame with different background color
```

**5.2. Determine purpose**:
- If it's meant for progress → show progress %
- If it's meant for ETA → show time remaining
- If unused → remove it

**Example fix (progress bar)**:
```python
# Replace grey box with progress indicator
self.progress_label = ttk.Label(frame, text="Progress: --")
# Or use ttk.Progressbar for visual bar

def _update_display(self):
    progress_pct = self._get_job_progress()
    self.progress_label.configure(text=f"Progress: {progress_pct}%")
```

### Phase 6: Fix Button Labels (15 minutes)

**File**: `src/gui/panels_v2/running_job_panel_v2.py`

```python
# Find button creation code (likely in __init__ or _build_ui)

# BEFORE:
pause_btn = ttk.Button(btn_frame, text="pause", command=self._on_pause)
cancel_btn = ttk.Button(btn_frame, text="cancel", command=self._on_cancel)
cancel_queue_btn = ttk.Button(btn_frame, text="cancel queue", ...)

# AFTER:
pause_btn = ttk.Button(btn_frame, text="Pause Job", command=self._on_pause)
cancel_btn = ttk.Button(btn_frame, text="Cancel Job", command=self._on_cancel)
# Remove cancel_queue_btn entirely - functionality is in Queue panel
```

### Phase 7: Testing (1 hour)

**Test Case 1: Job Starts**
- Queue job and click "Send Job"
- Verify:
  - ✅ Status changes to "Running"
  - ✅ Seed displays actual number (or "Random")
  - ✅ Stage shows "txt2img (1/N)"
  - ✅ Variant shows v1/b1 (not v0/b0)
  - ✅ Progress updates (if grey box is progress)

**Test Case 2: Multi-Stage Job**
- Queue job with txt2img → adetailer → upscale
- Verify:
  - ✅ Stage updates: "txt2img (1/3)" → "adetailer (2/3)" → "upscale (3/3)"
  - ✅ Status remains "Running" through all stages

**Test Case 3: Job Completes**
- Let job finish
- Verify:
  - ✅ Status changes to "Completed" or "Success"
  - ✅ Panel clears or shows final state

**Test Case 4: Pause/Cancel**
- Test "Pause Job" button
- Test "Cancel Job" button
- Verify:
  - ✅ Labels are clear and descriptive
  - ✅ No "Cancel Queue" button present

---

## File Modifications Required

### Primary File
**`src/gui/panels_v2/running_job_panel_v2.py`**
- Add seed label (if missing)
- Update stage display logic
- Fix variant/batch indexing (+1)
- Fix status display
- Investigate grey box
- Update button labels
- Remove cancel queue button

### Secondary Files
**`src/controller/app_controller.py`** or **`pipeline_controller.py`**
- Ensure `_set_running_job()` sets correct status
- Track current stage index (if not already)

**`src/pipeline/job_models_v2.py`**
- May need to add `current_stage_index` field to UnifiedJobSummary
- Or track separately in controller

---

## Success Criteria

✅ **Seed displayed correctly**:
- Shows actual seed number when available
- Shows "Random" when seed = -1

✅ **Stage shows current, not all**:
- Format: "Current Stage: txt2img (1/3)"
- Updates as stages progress

✅ **Variant/batch 1-based**:
- Shows v1/b1 instead of v0/b0
- Matches queue display format

✅ **Status accurate**:
- "Running" when executing
- "Completed" or "Success" when done
- "Paused" if paused
- "Failed" if error

✅ **Grey box identified and fixed**:
- Shows useful information (progress, ETA, etc.)
- Or removed if unused

✅ **Button labels clear**:
- "Pause Job" and "Cancel Job"
- No "Cancel Queue" button

---

## Testing Strategy

### Manual Testing
1. Start StableNew
2. Queue a job with multiple stages
3. Click "Send Job"
4. Watch Running Job panel update
5. Verify all fields display correctly
6. Test buttons

### Edge Cases
- Job with seed = -1 (random)
- Job with seed = 42 (fixed)
- Single-stage job (txt2img only)
- Multi-stage job (3+ stages)
- Job that fails mid-execution

---

## Risk Assessment

**Low Risk**:
- Isolated to Running Job panel
- Mostly display logic changes
- No breaking changes to backend

**Potential Issues**:
- Need to track current stage (may require pipeline changes)
- Grey box purpose unknown (need investigation)

---

## Dependencies

**Requires**:
- UnifiedJobSummary with complete fields
- Pipeline callbacks for stage changes (may need to add)

**Enables**:
- Better job monitoring
- Clearer UX
- Easier debugging

---

## Next Steps

1. ✅ Create this discovery document
2. ⏳ Read `running_job_panel_v2.py` lines 1-500
3. ⏳ Identify all labels and their update code
4. ⏳ Find grey box widget
5. ⏳ Implement fixes phase by phase
6. ⏳ Test with real job execution
