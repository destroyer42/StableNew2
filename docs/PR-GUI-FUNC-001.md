# PR-GUI-FUNC-001: Pipeline Tab Core Functionality Fixes

**Status**: 🟡 Specification  
**Priority**: HIGH  
**Effort**: MEDIUM (1 week)  
**Phase**: GUI Functional Repair  
**Date**: 2025-12-26

---

## Context & Motivation

### Problem Statement

Multiple core features in the Pipeline Tab are broken or non-functional:
- ❌ Refresh button doesn't refresh Prompt Pack list
- ❌ Pause/Cancel Job buttons always disabled (can't stop running jobs)
- ❌ Queue reordering (Up/Down/Front/Back) doesn't visually update
- ❌ Open Output Folder opens wrong directory (runs/ instead of actual output)
- ❌ Variant # not incrementing during batch processing
- ❌ Global Prompts save functionality unclear and possibly not wired

These are critical usability issues that prevent users from effectively managing jobs.

### Why This Matters

1. **Job Control**: Users cannot pause/cancel running jobs (safety/control issue)
2. **Queue Management**: Cannot reorder queue effectively (workflow blocker)
3. **File Organization**: Cannot find generated images (output folder wrong)
4. **Content Management**: Cannot refresh prompt packs without restart

### Current Architecture

**Queue System**:
- `QueuePanelV2` displays queue
- `RunningJobPanelV2` shows active job
- Controller manages job lifecycle

**File Output**:
- Jobs write to `output/` directory
- Running Job panel stores `runs/` path
- Mismatch between display and actual output

### Reference

Based on discovery in [D-GUI-004](D-GUI-004-Pipeline-Tab-Dark-Mode-UX.md), issues 1.b, 1.f, 3.d, 3.f, 3.g

---

## Goals & Non-Goals

### ✅ Goals

1. **Fix Refresh Button**
   - Clicking "Refresh" in Pack Selector reloads pack list from disk
   - Updates dropdown and listbox with new packs
   - Shows feedback (brief message or visual indicator)

2. **Enable Pause/Cancel Buttons**
   - Buttons enabled when job is running
   - Buttons disabled when no job running
   - Pause button pauses current job
   - Cancel button terminates current job
   - State updates correctly

3. **Fix Queue Reordering Visual Update**
   - Up/Down buttons visually move selected job
   - Front/Back buttons visually move selected job
   - Queue panel refreshes to show new order
   - Selection stays on moved job

4. **Fix Output Folder Path**
   - "Open Output Folder" uses actual output directory
   - Path stored correctly in job metadata
   - Opens correct folder in file explorer

5. **Fix Variant Counter**
   - Variant # increments during batch processing
   - Displays as "1/5", "2/5", etc.
   - Resets for new jobs

6. **Clarify Global Prompts Functionality**
   - Save buttons work and give feedback
   - Enable checkboxes control prepend behavior
   - State persists in pack configs

### ❌ Non-Goals

1. **Dark Mode Styling**: Separate PR (PR-GUI-DARKMODE-001)
2. **Layout Changes**: Separate PR (PR-GUI-LAYOUT-001)
3. **New Features**: Not adding new capabilities
4. **Job Lifecycle Log**: Removal in separate PR (PR-GUI-CLEANUP-001)

---

## Allowed Files

### ✅ Files to Modify

| File | Reason | Lines Changed (Est.) |
|------|--------|----------------------|
| `src/gui/sidebar_panel_v2.py` | Fix Refresh button, Global Prompts save | 50 |
| `src/gui/panels_v2/queue_panel_v2.py` | Fix reordering visual update | 40 |
| `src/gui/panels_v2/running_job_panel_v2.py` | Fix Pause/Cancel enable, variant counter, output folder | 80 |
| `src/controller/app_controller.py` | Add pause/cancel wiring if needed | 30 |
| `src/gui/prompt_pack_adapter_v2.py` | Enhance refresh functionality | 20 |
| `src/queue/job_model.py` | Add variant tracking if missing | 10 |

**Total**: 6 files, ~230 lines

### ✅ Files to Create

| File | Purpose | Lines (Est.) |
|------|---------|--------------|
| `tests/gui_v2/test_pr_gui_func_001.py` | Test refresh, pause/cancel, reordering | 150 |

**Total**: 1 file, ~150 lines

### ❌ Forbidden Files (DO NOT TOUCH)

| File/Directory | Reason |
|----------------|--------|
| `src/pipeline/**` | No pipeline logic changes |
| `src/builders/**` | No builder changes |
| `src/gui/theme_v2.py` | No theme changes |

**Rationale**: This PR fixes GUI functionality without changing core pipeline/builder logic.

---

## Implementation Plan

### Step 1: Fix Refresh Button

**File**: `src/gui/sidebar_panel_v2.py`

**Current Issue**: Refresh button callback not wired or not reloading packs

**Solution**:
```python
def _on_refresh_packs(self) -> None:
    """Reload prompt pack list from disk."""
    try:
        # Reload packs via adapter
        if self.prompt_pack_adapter:
            self.prompt_pack_adapter.refresh_packs()
        
        # Update listbox and dropdown
        self._update_pack_listbox()
        
        # Show brief feedback
        self._show_refresh_feedback()
    except Exception as e:
        logger.error(f"Failed to refresh packs: {e}")
```

**Wiring**:
```python
refresh_btn = ttk.Button(
    frame,
    text="Refresh",
    style="Dark.TButton",
    command=self._on_refresh_packs  # Add this
)
```

### Step 2: Enable Pause/Cancel Buttons

**File**: `src/gui/panels_v2/running_job_panel_v2.py`

**Current Issue**: Buttons configured with `state=["disabled"]` permanently

**Solution**:
```python
def _update_button_states(self) -> None:
    """Update Pause/Cancel button states based on job status."""
    if self._current_job_summary is None:
        # No job running
        self.pause_resume_button.state(["disabled"])
        self.cancel_button.state(["disabled"])
        return
    
    # Job running - enable buttons
    self.pause_resume_button.state(["!disabled"])
    self.cancel_button.state(["!disabled"])
    
    # Update pause button text
    if self._is_paused:
        self.pause_resume_button.configure(text="Resume Job")
    else:
        self.pause_resume_button.configure(text="Pause Job")
```

**Call in `update_job_with_summary()`**:
```python
def update_job_with_summary(...):
    # ... existing code ...
    self._update_display()
    self._update_button_states()  # Add this
```

**Wire callbacks**:
```python
self.pause_resume_button.configure(command=self._on_pause_resume_clicked)
self.cancel_button.configure(command=self._on_cancel_clicked)

def _on_pause_resume_clicked(self) -> None:
    if self.controller:
        self.controller.pause_current_job() if not self._is_paused else self.controller.resume_current_job()
        
def _on_cancel_clicked(self) -> None:
    if self.controller:
        self.controller.cancel_current_job()
```

### Step 3: Fix Queue Reordering Visual Update

**File**: `src/gui/panels_v2/queue_panel_v2.py`

**Current Issue**: Queue operations don't trigger listbox refresh

**Solution**:
```python
def _move_job_up(self) -> None:
    """Move selected job up in queue."""
    selection = self.queue_listbox.curselection()
    if not selection or selection[0] == 0:
        return
    
    idx = selection[0]
    
    # Move in controller
    if self.controller:
        self.controller.move_job_up(idx)
    
    # Refresh display
    self._refresh_queue_display()
    
    # Restore selection (one position up)
    self.queue_listbox.selection_clear(0, tk.END)
    self.queue_listbox.selection_set(idx - 1)
    self.queue_listbox.see(idx - 1)

def _refresh_queue_display(self) -> None:
    """Reload queue from controller and update listbox."""
    self.queue_listbox.delete(0, tk.END)
    if self.controller:
        jobs = self.controller.get_queue_jobs()
        for job in jobs:
            self.queue_listbox.insert(tk.END, job.get_display_summary())
```

Apply same pattern to `_move_job_down()`, `_move_to_front()`, `_move_to_back()`

### Step 4: Fix Output Folder Path

**File**: `src/gui/panels_v2/running_job_panel_v2.py`

**Current Issue**: Stores/opens `runs/` instead of actual output directory

**Solution**:
```python
def _on_open_output_clicked(self) -> None:
    """Open the job's actual output folder."""
    if self._current_job_summary is None:
        return
    
    # Get actual output directory from job
    output_dir = self._get_job_output_directory()
    
    if output_dir and os.path.exists(output_dir):
        os.startfile(output_dir)  # Windows
        # subprocess.run(["open", output_dir])  # macOS
        # subprocess.run(["xdg-open", output_dir])  # Linux
    else:
        logger.warning(f"Output directory not found: {output_dir}")

def _get_job_output_directory(self) -> str | None:
    """Get the actual output directory for the current job."""
    if self._current_job_summary is None:
        return None
    
    # Check job snapshot for output_dir
    snapshot = getattr(self._current_job_summary, "snapshot", {})
    output_dir = snapshot.get("output_dir") or snapshot.get("base_output_dir")
    
    if not output_dir:
        # Fallback to default output directory
        output_dir = "output"
    
    return output_dir
```

**Store correct path when job starts**:
```python
def update_job_with_summary(self, job, summary, progress_info):
    # ... existing code ...
    
    # Store output directory
    if summary:
        self._current_output_dir = summary.base_output_dir
```

### Step 5: Fix Variant Counter

**File**: `src/gui/panels_v2/running_job_panel_v2.py`

**Current Issue**: Variant # not incrementing

**Solution**:
```python
def _update_display(self) -> None:
    # ... existing code ...
    
    # Update variant counter
    if self._current_job_summary:
        variant_idx = getattr(self._current_job_summary, "variant_index", None)
        variant_total = getattr(self._current_job_summary, "variant_total", None)
        
        if variant_idx is not None and variant_total is not None:
            variant_text = f"{variant_idx + 1}/{variant_total}"
        else:
            variant_text = "N/A"
        
        self.variant_label.configure(text=variant_text)
```

**Ensure job summary includes variant info**: Check that `NormalizedJobRecord` or `JobUiSummary` includes `variant_index` and `variant_total` fields.

### Step 6: Clarify Global Prompts Functionality

**File**: `src/gui/sidebar_panel_v2.py`

**Current Behavior**: Unclear if saves work, no feedback

**Solution**:
```python
def _on_save_global_positive(self) -> None:
    """Save current global positive prompt as default."""
    text = self.global_positive_text.get("1.0", tk.END).strip()
    
    # Save to preferences/state
    if self.app_state:
        self.app_state.global_positive_prompt = text
        self.app_state.save_state()
    
    # Show confirmation
    self._show_save_confirmation("Global Positive saved")

def _on_save_global_negative(self) -> None:
    """Save current global negative prompt as default."""
    text = self.global_negative_text.get("1.0", tk.END).strip()
    
    # Save to preferences/state
    if self.app_state:
        self.app_state.global_negative_prompt = text
        self.app_state.save_state()
    
    # Show confirmation
    self._show_save_confirmation("Global Negative saved")

def _show_save_confirmation(self, message: str) -> None:
    """Show brief save confirmation message."""
    # Option 1: Status label (if exists)
    if hasattr(self, "status_label"):
        self.status_label.configure(text=message)
        self.after(2000, lambda: self.status_label.configure(text=""))
    
    # Option 2: Tooltip-style popup
    # (implement simple tooltip)
```

**Wire enable checkboxes**: Ensure checkboxes control prepend behavior in resolution layer.

---

## Testing Plan

### Unit Tests

**File**: `tests/gui_v2/test_pr_gui_func_001.py`

```python
def test_refresh_button_reloads_packs():
    """Test refresh button reloads prompt pack list."""
    # Setup
    sidebar = create_sidebar_panel()
    initial_count = sidebar.pack_listbox.size()
    
    # Create new pack file
    create_test_pack("new_pack.json")
    
    # Act
    sidebar._on_refresh_packs()
    
    # Assert
    assert sidebar.pack_listbox.size() == initial_count + 1

def test_pause_button_enabled_when_job_running():
    """Test pause button enabled state when job is running."""
    panel = create_running_job_panel()
    
    # No job
    panel.update_job_with_summary(None, None, None)
    assert "disabled" in panel.pause_resume_button.state()
    
    # Job running
    job_summary = create_mock_job_summary()
    panel.update_job_with_summary(mock_job(), job_summary, None)
    assert "disabled" not in panel.pause_resume_button.state()

def test_queue_reordering_updates_display():
    """Test moving job updates queue listbox."""
    panel = create_queue_panel()
    panel.add_jobs([job1, job2, job3])
    
    # Select job2
    panel.queue_listbox.selection_set(1)
    
    # Move up
    panel._move_job_up()
    
    # Assert
    assert panel.queue_listbox.get(0) == job2.get_display_summary()
    assert panel.queue_listbox.curselection()[0] == 0

def test_output_folder_uses_correct_path():
    """Test output folder opens correct directory."""
    panel = create_running_job_panel()
    job_summary = Mock(base_output_dir="output/test_run")
    panel.update_job_with_summary(Mock(), job_summary, None)
    
    path = panel._get_job_output_directory()
    assert path == "output/test_run"

def test_variant_counter_increments():
    """Test variant counter shows correct value."""
    panel = create_running_job_panel()
    
    job_summary = Mock(variant_index=2, variant_total=5)
    panel.update_job_with_summary(Mock(), job_summary, None)
    
    assert "3/5" in panel.variant_label.cget("text")
```

### Manual Testing

1. **Refresh Button**:
   - Add new pack to `packs/` folder
   - Click Refresh in Pack Selector
   - Verify new pack appears in list

2. **Pause/Cancel**:
   - Start a job
   - Verify Pause/Cancel buttons enabled
   - Click Pause → verify job pauses
   - Click Cancel → verify job terminates
   - Verify buttons disabled when no job

3. **Queue Reordering**:
   - Add 3 jobs to queue
   - Select middle job
   - Click Up → verify visually moves up
   - Click Down → verify visually moves down
   - Click Front → verify moves to top
   - Click Back → verify moves to bottom

4. **Output Folder**:
   - Run a job
   - Click "Open Output Folder"
   - Verify opens correct directory with images

5. **Variant Counter**:
   - Run batch job (5 variants)
   - Watch variant counter increment: 1/5, 2/5, 3/5, 4/5, 5/5

6. **Global Prompts**:
   - Enter text in Global Positive
   - Click Save
   - Verify confirmation message
   - Restart app
   - Verify text persists

---

## Verification Criteria

### ✅ Success Criteria

1. **Refresh Button**
   - [ ] Clicking Refresh reloads pack list from disk
   - [ ] New packs appear after refresh
   - [ ] No errors in console

2. **Pause/Cancel Buttons**
   - [ ] Buttons enabled when job running
   - [ ] Buttons disabled when no job
   - [ ] Pause actually pauses job
   - [ ] Cancel actually terminates job

3. **Queue Reordering**
   - [ ] Up/Down/Front/Back buttons work
   - [ ] Listbox updates visually
   - [ ] Selection tracks moved job

4. **Output Folder**
   - [ ] Opens correct output directory
   - [ ] Directory contains generated images

5. **Variant Counter**
   - [ ] Shows "N/A" or "1/1" for single jobs
   - [ ] Shows "1/5", "2/5", etc. for batch jobs
   - [ ] Increments correctly

6. **Global Prompts**
   - [ ] Save buttons work
   - [ ] Shows confirmation
   - [ ] State persists across restarts

### ❌ Failure Criteria

Any of:
- Refresh causes crash
- Pause/Cancel don't affect job
- Queue reordering breaks queue
- Wrong folder opens
- Variant counter incorrect

---

## Risk Assessment

### Low Risk Areas

✅ **Refresh Button**: Simple callback wiring  
✅ **Variant Counter**: Display-only update

### Medium Risk Areas

⚠️ **Pause/Cancel**: Requires controller support
- **Mitigation**: Check controller has pause/cancel methods, add if needed

⚠️ **Queue Reordering**: Must maintain queue integrity
- **Mitigation**: Test thoroughly, add validation

### High Risk Areas

❌ **Output Folder**: Must not break existing paths
- **Mitigation**: Fallback to default if path missing, validate paths exist

### Rollback Plan

If issues found:
1. Revert specific failing change
2. Each fix is independent, can be partially rolled back
3. No pipeline/builder changes to revert

---

## Tech Debt Removed

✅ **Non-functional Refresh**: Users can now reload packs  
✅ **Disabled Pause/Cancel**: Users can now control jobs  
✅ **Invisible Queue Reordering**: Visual feedback now works  
✅ **Wrong Output Folder**: Correct folder now opens  
✅ **Broken Variant Counter**: Counter now works  
✅ **Unclear Global Prompts**: Functionality now clear

**Net Tech Debt**: -6 major functional issues

---

## Architecture Alignment

### ✅ Enforces Architecture v2.6

- No changes to pipeline (PromptPack → NJR → Queue → Runner)
- Controller methods used properly
- GUI → Controller → State flow maintained

### ✅ Follows Testing Standards

- Unit tests for all fixes
- Manual test procedures documented

### ✅ Maintains Separation of Concerns

- GUI fixes in GUI layer
- Controller calls for job control
- No pipeline logic in GUI

---

## Dependencies

### External

- ✅ Tkinter/ttk - already used
- ✅ OS file operations - standard library

### Internal

- ✅ Controller methods - may need enhancement
- ✅ Queue system - already exists
- ⚠️ Job model - may need variant fields added

---

## Timeline & Effort

### Breakdown

| Task | Effort | Duration |
|------|--------|----------|
| Step 1: Refresh button | 4 hours | Day 1 |
| Step 2: Pause/Cancel | 8 hours | Day 2 |
| Step 3: Queue reordering | 6 hours | Day 3 |
| Step 4: Output folder | 4 hours | Day 4 AM |
| Step 5: Variant counter | 3 hours | Day 4 PM |
| Step 6: Global prompts | 3 hours | Day 5 AM |
| Testing & validation | 8 hours | Day 5-6 |
| Buffer | 4 hours | Day 7 |

**Total**: 5-7 days

---

## Approval & Sign-Off

**Planner**: GitHub Copilot (Multi-agent)  
**Executor**: TBD (Codex or Rob)  
**Reviewer**: Rob (Product Owner)

**Approval Status**: 🟡 Awaiting Rob's approval

---

## Next Steps

1. **Rob reviews this PR spec**
2. **Rob approves or requests changes**
3. **Executor implements Steps 1-6**
4. **Rob validates functionality**
5. **Merge to `testingBranchFromWorking`**
6. **Test for 1 week**
7. **Merge to `main`**

---

**Document Status**: ✅ Complete  
**Ready for Implementation**: ✅ Yes (pending approval)  
**Estimated Completion**: 2026-01-03 (1 week from approval)
