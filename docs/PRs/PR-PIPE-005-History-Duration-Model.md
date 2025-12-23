# PR-PIPE-005 – History Panel Duration & Model Display

## Context

The Job History Panel currently shows limited information about completed jobs:

1. **Duration column often shows "-"** - The `duration_ms` field is not reliably populated
2. **Model not displayed** - Users can't see which model was used for a job
3. **VAE not displayed** - Important for understanding color/saturation differences
4. **Seed shows "-1" or missing** - Not extracted from completed job data
5. **No per-stage breakdown** - Only total job info, not individual stage times

Users need this information to:
- Understand which configurations produce faster results
- Correlate model choice with image quality
- Reproduce successful generations (requires actual seed)
- Compare efficiency of different pipelines

## Non-Goals

- Adding new data recording (that's PR-PIPE-001)
- Modifying history storage format
- Adding image thumbnails to history (future enhancement)
- Detailed stage-by-stage timing breakdown (future enhancement)
- Changing history panel layout significantly

## Invariants

- History entries without new fields must still display correctly
- Column widths must remain reasonable (use abbreviations if needed)
- Panel must handle thousands of entries without performance issues
- Treeview must remain sortable on all columns
- No breaking changes to `JobHistoryEntry` structure

## Allowed Files

- `src/gui/job_history_panel_v2.py` - Add columns, extract display data
- `src/gui/panels_v2/history_panel_v2.py` - If different implementation exists
- `src/controller/app_controller.py` - Ensure duration is calculated on job completion
- `src/queue/job_history_store.py` - Ensure duration_ms is set correctly
- `tests/gui_v2/test_job_history_panel_display.py` (new)

## Do Not Touch

- `src/history/history_record.py` - Schema unchanged
- `src/history/history_schema_v26.py` - Schema unchanged
- `src/pipeline/executor.py` - Manifest changes are separate (PR-PIPE-001)
- `src/pipeline/job_models_v2.py` - NJR unchanged

## Interfaces

### Enhanced Column Configuration

```python
# New columns configuration
HISTORY_COLUMNS = (
    ("time", "Completed", 110),
    ("status", "Status", 70),
    ("model", "Model", 120),        # NEW
    ("packs", "Prompt / Pack", 180),
    ("duration", "Duration", 80),
    ("seed", "Seed", 90),           # NEW
    ("images", "Images", 60),
    ("output", "Output Folder", 160),
)
```

### Data Extraction Methods

```python
class JobHistoryPanelV2(ttk.Frame):
    
    def _extract_model(self, entry: JobHistoryEntry) -> str:
        """Extract model name from NJR snapshot or result."""
    
    def _extract_vae(self, entry: JobHistoryEntry) -> str:
        """Extract VAE name from NJR snapshot or result."""
    
    def _extract_seed(self, entry: JobHistoryEntry) -> str:
        """Extract actual seed from result or snapshot."""
    
    def _ensure_duration(self, entry: JobHistoryEntry) -> str:
        """Ensure duration is calculated and formatted."""
```

### Error Behavior

- Missing model: Display "-" or "Unknown"
- Missing seed: Display "-1" or "Random"
- Missing duration: Calculate from timestamps if possible, else "-"
- Missing VAE: Display "Auto" (default)
- Truncation: Model names truncated to fit column, tooltip shows full name

## Implementation Steps (Order Matters)

### Step 1: Update Column Configuration

In `src/gui/job_history_panel_v2.py`, update the columns definition:

```python
# Replace existing columns definition (~line 68)
columns = ("time", "status", "model", "packs", "duration", "seed", "images", "output")
headings = {
    "time": "Completed",
    "status": "Status",
    "model": "Model",           # NEW
    "packs": "Prompt / Pack",
    "duration": "Duration",
    "seed": "Seed",             # NEW
    "images": "Images",
    "output": "Output",
}

# Update column widths
for col in columns:
    self.history_tree.heading(col, text=headings[col])
    width = {
        "time": 100,
        "status": 70,
        "model": 120,
        "packs": 180,
        "duration": 70,
        "seed": 85,
        "images": 55,
        "output": 150,
    }.get(col, 100)
    self.history_tree.column(col, anchor=tk.W, width=width, stretch=True)
```

### Step 2: Add Model Extraction Method

```python
def _extract_model(self, entry: JobHistoryEntry) -> str:
    """Extract model name from NJR snapshot or result."""
    # Try NJR snapshot first (most reliable)
    if entry.snapshot:
        njr = entry.snapshot.get("normalized_job", {})
        model = njr.get("base_model") or njr.get("model")
        if model:
            return self._shorten(str(model), width=18)
    
    # Try result
    if entry.result and isinstance(entry.result, dict):
        model = entry.result.get("model") or entry.result.get("sd_model_checkpoint")
        if model:
            return self._shorten(str(model), width=18)
    
    return "-"
```

### Step 3: Add Seed Extraction Method

```python
def _extract_seed(self, entry: JobHistoryEntry) -> str:
    """Extract actual seed from result or snapshot."""
    # Try result first (has actual resolved seed)
    if entry.result and isinstance(entry.result, dict):
        seed = entry.result.get("actual_seed") or entry.result.get("seed")
        if seed is not None and seed != -1:
            return str(seed)
    
    # Try NJR snapshot
    if entry.snapshot:
        njr = entry.snapshot.get("normalized_job", {})
        
        # Check for resolved seed
        seed = njr.get("actual_seed") or njr.get("resolved_seed")
        if seed is not None and seed != -1:
            return str(seed)
        
        # Fall back to requested seed
        seed = njr.get("seed")
        if seed is not None:
            if seed == -1:
                return "Random"
            return str(seed)
    
    return "-"
```

### Step 4: Ensure Duration Calculation

Update `_entry_values` to better handle duration:

```python
def _entry_values(self, entry: JobHistoryEntry) -> tuple[str, ...]:
    time_text = self._format_time(entry.completed_at or entry.started_at or entry.created_at)
    status = entry.status.value
    
    # Extract model
    model = self._extract_model(entry)
    
    # Extract summary
    packs = self._extract_summary(entry)
    
    # Calculate duration more robustly
    duration = self._ensure_duration(entry)
    
    # Extract seed
    seed = self._extract_seed(entry)
    
    # Image count
    images = self._extract_image_count(entry)
    
    # Output folder
    output = self._extract_output_folder(entry)
    
    return (time_text, status, model, packs, duration, seed, images, output)


def _ensure_duration(self, entry: JobHistoryEntry) -> str:
    """Ensure duration is calculated and formatted."""
    # Prefer pre-calculated duration_ms
    if entry.duration_ms is not None and entry.duration_ms > 0:
        return self._format_duration_ms(entry.duration_ms)
    
    # Calculate from timestamps if available
    if entry.started_at and entry.completed_at:
        try:
            start = entry.started_at
            end = entry.completed_at
            
            # Handle string timestamps
            if isinstance(start, str):
                start = datetime.fromisoformat(start.replace('Z', '+00:00'))
            if isinstance(end, str):
                end = datetime.fromisoformat(end.replace('Z', '+00:00'))
            
            delta = end - start
            duration_ms = int(delta.total_seconds() * 1000)
            if duration_ms > 0:
                return self._format_duration_ms(duration_ms)
        except Exception:
            pass
    
    return "-"
```

### Step 5: Add Tooltip for Full Model Name

```python
def __init__(self, ...):
    # ... existing init ...
    
    # Add tooltip support
    self._tooltip: tk.Toplevel | None = None
    self.history_tree.bind("<Motion>", self._on_tree_motion)
    self.history_tree.bind("<Leave>", self._hide_tooltip)


def _on_tree_motion(self, event: tk.Event) -> None:
    """Show tooltip with full model name on hover."""
    item = self.history_tree.identify_row(event.y)
    column = self.history_tree.identify_column(event.x)
    
    if not item or column != "#3":  # Model column
        self._hide_tooltip()
        return
    
    job_id = self._item_to_job.get(item)
    if not job_id:
        self._hide_tooltip()
        return
    
    entry = self._entries.get(job_id)
    if not entry:
        self._hide_tooltip()
        return
    
    # Get full model name
    full_model = self._extract_full_model(entry)
    if not full_model or full_model == "-":
        self._hide_tooltip()
        return
    
    self._show_tooltip(event.x_root, event.y_root, full_model)


def _extract_full_model(self, entry: JobHistoryEntry) -> str:
    """Extract full model name without truncation."""
    if entry.snapshot:
        njr = entry.snapshot.get("normalized_job", {})
        model = njr.get("base_model") or njr.get("model")
        if model:
            return str(model)
    return "-"


def _show_tooltip(self, x: int, y: int, text: str) -> None:
    """Display tooltip near cursor."""
    self._hide_tooltip()
    
    self._tooltip = tk.Toplevel(self)
    self._tooltip.wm_overrideredirect(True)
    self._tooltip.wm_geometry(f"+{x + 10}+{y + 10}")
    
    label = tk.Label(
        self._tooltip,
        text=text,
        background="#ffffe0",
        foreground="#000000",
        relief="solid",
        borderwidth=1,
        font=("Segoe UI", 9),
        padx=4,
        pady=2,
    )
    label.pack()


def _hide_tooltip(self, event: tk.Event | None = None) -> None:
    """Hide the tooltip."""
    if self._tooltip:
        self._tooltip.destroy()
        self._tooltip = None
```

### Step 6: Ensure Duration is Recorded on Job Completion

In `src/controller/app_controller.py`, verify duration is set:

```python
def _on_job_finished(self, job: Job) -> None:
    def _apply() -> None:
        if self.app_state:
            self.app_state.set_running_job(None)
        
        # Ensure duration is calculated
        if hasattr(job, "started_at") and hasattr(job, "completed_at"):
            if job.started_at and job.completed_at:
                try:
                    delta = job.completed_at - job.started_at
                    duration_ms = int(delta.total_seconds() * 1000)
                    if duration_ms > 0:
                        job.duration_ms = duration_ms
                except Exception:
                    pass
        
        self._refresh_job_history()

    self._run_in_gui_thread(_apply)
```

### Step 7: Update History Store to Record Duration

In `src/queue/job_history_store.py`, ensure `record_status_change` calculates duration:

```python
def record_status_change(
    self,
    job_id: str,
    status: JobStatus,
    ts: datetime,
    error: str | None = None,
    result: dict[str, Any] | None = None,
) -> None:
    # ... existing code ...
    
    # Calculate duration if completing
    if status == JobStatus.COMPLETED and entry.started_at:
        try:
            delta = ts - entry.started_at
            entry.duration_ms = int(delta.total_seconds() * 1000)
        except Exception:
            pass
```

### Step 8: Write Tests

Create `tests/gui_v2/test_job_history_panel_display.py`.

## Acceptance Criteria

1. **Given** a completed job with model "epicrealismXL_v5", **when** viewing history, **then** the Model column shows "epicrealismXL_v5" (or truncated with tooltip).

2. **Given** a completed job that took 120 seconds, **when** viewing history, **then** the Duration column shows "2m 0s".

3. **Given** a completed job with actual seed 123456789, **when** viewing history, **then** the Seed column shows "123456789".

4. **Given** a job with seed=-1 that has not resolved, **when** viewing history, **then** the Seed column shows "Random".

5. **Given** an old history entry without model field, **when** viewing history, **then** the Model column shows "-" without errors.

6. **Given** a model name longer than column width, **when** hovering over the cell, **then** a tooltip shows the full model name.

7. **Given** `duration_ms` is null but timestamps exist, **when** viewing history, **then** duration is calculated from timestamps.

## Test Plan

### Unit Tests

```bash
pytest tests/gui_v2/test_job_history_panel_display.py -v
```

**Test Cases:**

1. `test_columns_include_model_and_seed` - Verify column configuration
2. `test_extract_model_from_snapshot` - Model extraction works
3. `test_extract_model_fallback_to_result` - Falls back to result
4. `test_extract_model_missing_returns_dash` - Handles missing data
5. `test_extract_seed_from_result` - Actual seed extraction
6. `test_extract_seed_random_display` - Shows "Random" for -1
7. `test_ensure_duration_from_duration_ms` - Uses pre-calculated
8. `test_ensure_duration_from_timestamps` - Calculates from timestamps
9. `test_entry_values_returns_all_columns` - Correct tuple size
10. `test_old_entries_display_without_error` - Backward compatibility

### Manual Verification

1. Generate several jobs with different models
2. Open History panel and verify Model column populated
3. Verify Duration shows actual run time
4. Verify Seed shows actual seed (not -1)
5. Hover over truncated model names for tooltip
6. Sort by each column and verify sorting works

## Rollback

```bash
git revert <commit-hash>
```

Rollback is safe because:
- Changes are display-only
- No data format changes
- Existing entries continue to work
- Column additions are backward compatible

## Dependencies

- PR-PIPE-001 (Manifest Enhancement) - Provides better model/seed data
  - Note: This PR works without PR-PIPE-001 but shows "-" for new fields

## Dependents

- None (display-only changes)
