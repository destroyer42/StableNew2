# PR-GUI-FUNC-003: Functional Enhancements (Refiner Default, Hires Model Logic, Queue Visual Feedback, Output Path Fix)

**Status**: READY FOR IMPLEMENTATION  
**Priority**: High  
**PR Type**: GUI Functional Enhancement  
**Architecture Impact**: Minor (Config defaults, queue display)

---

## Context & Motivation

Several functional issues impact usability and correctness:
1. **Refiner Start default** should be 80% (currently not set)
2. **Hires "Use base model"** checkbox should auto-update hires model dropdown
3. **Queue reordering** lacks visual feedback when jobs move
4. **Variant counter** not incrementing properly
5. **Output folder** opens wrong directory

**Related Outstanding Issues:**
- Issue 2d: SDXL Refiner Start default needs to be 80%
- Issue 2f: Hires fix "Use base model during hires" functionality
- Issue 3d: Queue reordering visual feedback
- Issue 3g: Variant counter and output folder path

---

## Implementation Plan

### Phase 1: Set Refiner Start Default to 80%

**File**: `src/gui/stage_cards_v2/advanced_txt2img_stage_card_v2.py`

**Current code** (line ~327):
```python
self.refiner_switch_var = tk.DoubleVar(value=0.8)
```

The default is already 0.8 (80%), but it's not being applied when loading from a prompt pack that lacks this field.

**Issue**: When `apply_config()` is called, if the config dict doesn't have `refiner_start`, the variable isn't updated.

**Fix** (line ~680-710):
```python
def apply_config(self, cfg: dict[str, Any]) -> None:
    """Apply configuration from prompt pack or preset."""
    # ... existing code ...
    
    # Refiner configuration
    if "refiner_enabled" in cfg:
        self.refiner_enabled_var.set(bool(cfg.get("refiner_enabled", False)))
    if "refiner_model" in cfg:
        self.refiner_model_var.set(cfg.get("refiner_model", ""))
    
    # PR-GUI-FUNC-003: Ensure refiner_start defaults to 0.8 (80%)
    refiner_start = cfg.get("refiner_start", cfg.get("refiner_switch_at", 0.8))
    self.refiner_switch_var.set(float(refiner_start))
```

### Phase 2: Hires "Use Base Model" Auto-Update

**File**: `src/gui/stage_cards_v2/advanced_txt2img_stage_card_v2.py`

**Current behavior**: Checkbox exists but doesn't control dropdown

**Required behavior**:
1. When checkbox is checked → set hires_model to match base model
2. When checkbox is checked → disable hires_model dropdown
3. When checkbox is unchecked → enable hires_model dropdown
4. When base model changes while checkbox is checked → update hires model to match

**Implementation** (line ~430-460):

Add trace for base model changes:
```python
def __init__(self, ...):
    # ... existing init code ...
    
    # PR-GUI-FUNC-003: Trace base model changes for hires sync
    self.model_name_var.trace_add("write", lambda *_: self._on_base_model_changed())
```

Implement hires use base model logic:
```python
def _on_hires_use_base_model_toggled(self) -> None:
    """Handle 'Use base model during hires' checkbox toggle."""
    use_base = self.hires_use_base_model_var.get()
    
    if use_base:
        # Sync hires model to base model
        base_model = self.model_name_var.get()
        self.hires_model_var.set(base_model)
        # Disable dropdown
        if hasattr(self, "_hires_model_combo"):
            self._hires_model_combo.configure(state="disabled")
    else:
        # Enable dropdown
        if hasattr(self, "_hires_model_combo"):
            self._hires_model_combo.configure(state="readonly")

def _on_base_model_changed(self) -> None:
    """Sync hires model when base model changes (if use_base_model is enabled)."""
    if self.hires_use_base_model_var.get():
        base_model = self.model_name_var.get()
        self.hires_model_var.set(base_model)
```

Wire checkbox to handler (line ~430):
```python
ttk.Checkbutton(
    self._hires_options_frame,
    text="Use base model during hires",
    variable=self.hires_use_base_model_var,
    command=self._on_hires_use_base_model_toggled,
    style="Dark.TCheckbutton",
).grid(row=..., column=..., sticky="w")
```

### Phase 3: Queue Reordering Visual Feedback

**File**: `src/gui/panels_v2/queue_panel_v2.py`

**Current issue**: When user clicks Up/Down/Front/Back buttons, the job moves in the queue but the listbox doesn't update visually, making it appear like nothing happened.

**Root cause**: The listbox is populated from `app_state.queue_job_summaries`, but after reordering, the app_state might not be updated immediately, or the listbox isn't refreshing.

**Fix** (line ~300-400):

```python
def _on_move_up(self) -> None:
    """Move selected job up one position in queue."""
    selected_indices = self.listbox.curselection()
    if not selected_indices:
        return
    index = selected_indices[0]
    if index == 0:
        return  # Already at top
    
    # Move in controller
    if self.controller and hasattr(self.controller, "move_job_in_queue"):
        job_id = self._get_job_id_at_index(index)
        if job_id:
            self.controller.move_job_in_queue(job_id, index - 1)
            
            # PR-GUI-FUNC-003: Force immediate visual update
            self._refresh_queue_display()
            # Maintain selection on moved item
            self.listbox.selection_clear(0, tk.END)
            self.listbox.selection_set(index - 1)
            self.listbox.see(index - 1)

def _on_move_down(self) -> None:
    """Move selected job down one position in queue."""
    selected_indices = self.listbox.curselection()
    if not selected_indices:
        return
    index = selected_indices[0]
    if index >= self.listbox.size() - 1:
        return  # Already at bottom
    
    # Move in controller
    if self.controller and hasattr(self.controller, "move_job_in_queue"):
        job_id = self._get_job_id_at_index(index)
        if job_id:
            self.controller.move_job_in_queue(job_id, index + 1)
            
            # PR-GUI-FUNC-003: Force immediate visual update
            self._refresh_queue_display()
            # Maintain selection on moved item
            self.listbox.selection_clear(0, tk.END)
            self.listbox.selection_set(index + 1)
            self.listbox.see(index + 1)

def _on_move_to_front(self) -> None:
    """Move selected job to front of queue."""
    selected_indices = self.listbox.curselection()
    if not selected_indices:
        return
    index = selected_indices[0]
    if index == 0:
        return
    
    if self.controller and hasattr(self.controller, "move_job_to_front"):
        job_id = self._get_job_id_at_index(index)
        if job_id:
            self.controller.move_job_to_front(job_id)
            
            # PR-GUI-FUNC-003: Force immediate visual update
            self._refresh_queue_display()
            self.listbox.selection_clear(0, tk.END)
            self.listbox.selection_set(0)
            self.listbox.see(0)

def _on_move_to_back(self) -> None:
    """Move selected job to back of queue."""
    selected_indices = self.listbox.curselection()
    if not selected_indices:
        return
    index = selected_indices[0]
    last_index = self.listbox.size() - 1
    if index == last_index:
        return
    
    if self.controller and hasattr(self.controller, "move_job_to_back"):
        job_id = self._get_job_id_at_index(index)
        if job_id:
            self.controller.move_job_to_back(job_id)
            
            # PR-GUI-FUNC-003: Force immediate visual update
            self._refresh_queue_display()
            self.listbox.selection_clear(0, tk.END)
            self.listbox.selection_set(last_index)
            self.listbox.see(last_index)

def _refresh_queue_display(self) -> None:
    """Force immediate refresh of queue listbox from app_state."""
    if self.app_state and hasattr(self.app_state, "queue_job_summaries"):
        summaries = self.app_state.queue_job_summaries
        self._populate_listbox(summaries)
```

### Phase 4: Variant Counter Fix

**Issue**: Variant number not incrementing in filenames

**Investigation needed**: Check filename generation in `src/pipeline/output_manager_v2.py` or `src/pipeline/filename_builder_v2.py`

**File**: Search for variant counter logic

```python
# Expected: filename_0001.png, filename_0002.png, etc.
# Actual: All generating as filename_0001.png
```

**Fix** (to be determined after code review):
- Ensure variant counter increments in output manager
- Check if counter is per-job or per-batch
- Verify counter resets appropriately between jobs

### Phase 5: Output Folder Path Fix

**Issue**: "Open Output Folder" opens `runs/` instead of actual output directory

**File**: `src/gui/panels_v2/queue_panel_v2.py` or similar

**Current code** (search for "open output folder"):
```python
def _on_open_output_folder(self) -> None:
    """Open the output folder for the selected job."""
    # Currently opens: Path("runs/")
    # Should open: actual job output directory from job.output_dir or similar
```

**Fix**:
```python
def _on_open_output_folder(self) -> None:
    """Open the output folder where the selected job's images are saved."""
    selected_indices = self.listbox.curselection()
    if not selected_indices:
        return
    
    job_id = self._get_job_id_at_index(selected_indices[0])
    if not job_id:
        return
    
    # Get job details from app_state or controller
    if self.controller and hasattr(self.controller, "get_job_output_directory"):
        output_dir = self.controller.get_job_output_directory(job_id)
        if output_dir and Path(output_dir).exists():
            import subprocess
            subprocess.Popen(f'explorer "{output_dir}"')  # Windows
            # For cross-platform: use platform module
        else:
            # Fallback to default output directory
            from src.config.app_config import get_output_directory
            default_dir = get_output_directory()
            if Path(default_dir).exists():
                subprocess.Popen(f'explorer "{default_dir}"')
```

---

## Allowed Files

| File | Purpose | Modification Type |
|------|---------|-------------------|
| `src/gui/stage_cards_v2/advanced_txt2img_stage_card_v2.py` | **MODIFY** - Refiner default, Hires logic | Config + handlers |
| `src/gui/panels_v2/queue_panel_v2.py` | **MODIFY** - Queue visual feedback, output path | Display logic |
| `src/pipeline/output_manager_v2.py` | **MODIFY** - Variant counter (if needed) | Counter logic |
| `src/controller/app_controller.py` | **MODIFY** - Get job output directory (if needed) | Query method |

---

## Forbidden Files

**No builder or executor logic may be modified.** Changes are limited to:
- GUI display and interaction
- Configuration defaults
- Output path resolution

---

## Testing Requirements

### Unit Tests

**File**: `tests/gui_v2/test_txt2img_refiner_hires.py`

```python
def test_refiner_start_default():
    """Test refiner_start defaults to 0.8 when not in config."""
    card = AdvancedTxt2ImgStageCardV2(...)
    config = {"refiner_enabled": True}  # No refiner_start
    card.apply_config(config)
    assert card.refiner_switch_var.get() == 0.8

def test_hires_use_base_model_syncs():
    """Test hires model syncs when 'use base model' is checked."""
    card = AdvancedTxt2ImgStageCardV2(...)
    card.model_name_var.set("model_A.safetensors")
    card.hires_use_base_model_var.set(True)
    card._on_hires_use_base_model_toggled()
    assert card.hires_model_var.get() == "model_A.safetensors"

def test_hires_dropdown_disabled_when_using_base():
    """Test hires model dropdown is disabled when using base model."""
    card = AdvancedTxt2ImgStageCardV2(...)
    card.hires_use_base_model_var.set(True)
    card._on_hires_use_base_model_toggled()
    assert card._hires_model_combo.cget("state") == "disabled"
```

**File**: `tests/gui_v2/test_queue_panel_visual_feedback.py`

```python
def test_queue_move_up_updates_display():
    """Test moving job up visually updates listbox."""
    panel = QueuePanelV2(...)
    # Populate with test jobs
    # Select job at index 1
    # Call _on_move_up()
    # Assert listbox shows job at index 0
    # Assert selection moved to index 0
    pass

def test_queue_move_down_maintains_selection():
    """Test moving job down keeps selection on moved item."""
    # Similar to above
    pass
```

### Manual Testing

1. **Refiner Default**:
   - Create new prompt pack without `refiner_start` field
   - Load pack in GUI
   - Enable refiner
   - Verify "Refiner start" slider shows 80%

2. **Hires Use Base Model**:
   - Select base model in Txt2Img
   - Enable Hires fix
   - Check "Use base model during hires"
   - Verify hires model dropdown shows same model
   - Verify dropdown is disabled (grayed out)
   - Change base model
   - Verify hires model updates automatically
   - Uncheck "Use base model"
   - Verify dropdown is re-enabled

3. **Queue Visual Feedback**:
   - Add 3 jobs to queue
   - Select middle job
   - Click "Up" button
   - Verify job visually moves up in listbox
   - Verify selection follows the moved job
   - Click "Front" button
   - Verify job moves to top position
   - Verify listbox updates immediately

4. **Variant Counter**:
   - Run a job that generates 3 variants
   - Check output folder
   - Verify filenames: image_0001.png, image_0002.png, image_0003.png
   - Run another job
   - Verify variants reset: image_0001.png (new batch)

5. **Output Folder**:
   - Complete a job
   - Select job in history or queue
   - Click "Open Output Folder"
   - Verify Windows Explorer opens to the correct output directory
   - Verify images from that job are visible

---

## Tech Debt Addressed

- **Missing defaults**: Refiner start now properly defaults to recommended value
- **Manual model sync**: Hires model auto-syncs with base model when desired
- **Poor UX**: Queue reordering now provides immediate visual feedback
- **Broken navigation**: Output folder button now opens correct directory

---

## Implementation Notes

1. **Refiner start**: The value 0.8 (80%) is recommended by Stability AI for SDXL refiner
2. **Hires model sync**: Only syncs when checkbox is checked - preserves user choice
3. **Queue refresh**: `_refresh_queue_display()` must be called immediately after controller action
4. **Output path**: May need to store output_dir in job metadata for retrieval

---

## Definition of Done

- [ ] Refiner start defaults to 80% when missing from config
- [ ] Hires "Use base model" checkbox syncs model and disables dropdown
- [ ] Base model changes update hires model when sync is enabled
- [ ] Queue Up/Down/Front/Back buttons show immediate visual feedback
- [ ] Selection follows moved job in queue
- [ ] Variant counter increments correctly across images in batch
- [ ] "Open Output Folder" opens correct directory for selected job
- [ ] All unit tests pass
- [ ] Manual testing confirms all behaviors work correctly
- [ ] Outstanding Issues document updated

---

## Post-Implementation Tasks

1. Update Outstanding Issues document - mark items 2d, 2f, 3d, 3g as FIXED
2. Consider adding keyboard shortcuts for queue reordering (Ctrl+Up/Down)
3. Add user preference for default refiner start value

---

**Estimated Effort**: 6-8 hours  
**Risk Level**: Medium (controller interaction required)  
**Dependencies**: None
