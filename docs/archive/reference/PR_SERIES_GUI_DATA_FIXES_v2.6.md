# PR Series: GUI & Data Recording Fixes (v2.6)

**Status**: PLANNING
**Date**: 2025-12-24
**Scope**: Comprehensive fixes for GUI display, data recording, and user experience issues

## Executive Summary

This document outlines a series of PRs to address critical gaps in:
1. GUI information display (filtering results, preview thumbnails, time estimates)
2. Job history data completeness (model, VAE, actual seeds, refiner configs)
3. Queue manipulation (up/down buttons)
4. Default value tracking and warnings
5. ADetailer configuration completeness
6. Dark mode theming consistency

## Issues Identified

### CRITICAL (Data Loss/Learning Impact)
1. **txt2img manifest missing model/VAE** - Learning module cannot correlate images with models
2. **txt2img manifest shows seed=-1** - Image reproduction impossible
3. **Refiner configs not recorded** - Unknown which images used refiner
4. **Hires fix configs incorrect** - Denoising shows 0.25 in GUI but 0.7 in manifest

### HIGH (UX/Visibility)
5. **Image filtering results** - Only logged, not shown in GUI
6. **Job history shows blanks** - Model, duration, seed columns empty
7. **Queue up/down buttons broken** - Move viewing window instead of reordering jobs
8. **Preview thumbnail never shows** - Widget exists but never updates
9. **Job time estimator never updates** - Always shows stale data

### MEDIUM (Completeness)
10. **Job lifecycle log inactive** - Subscribes to events but doesn't display them
11. **Default value tracking** - No way to identify when defaults vs user values used
12. **ADetailer missing configs** - Inpainting, mask, feathering options not exposed
13. **Reprocess panel dark mode** - Widgets use light theme

---

## PR Series Design

### PR-GUI-DATA-001: Fix Manifest Recording (txt2img, model, VAE, seeds, refiner)
**Priority**: CRITICAL
**Estimated Effort**: 4-6 hours
**Dependencies**: None

#### Problem Statement
The txt2img stage manifest is missing critical data:
- Model name not recorded (stored in `config` but not at root level for learning)
- VAE not recorded
- `requested_seed` shows -1 instead of actual generated seed
- `actual_seed` and `actual_subseed` missing
- Refiner configuration not recorded (model, switch_at, enabled flag)
- Hires fix denoising shows wrong value (GUI shows 0.25, manifest shows 0.7)

#### Root Cause Analysis

**Location**: `src/pipeline/executor.py` lines 1251-1309 (`run_txt2img_v2`)

```python
metadata = {
    "name": image_name,
    "stage": "txt2img",
    "timestamp": datetime.now().strftime("%Y%m%d_%H%M%S"),
    "prompt": txt_prompt,
    "negative_prompt": txt_negative,
    # ... other fields ...
    "job_id": getattr(self, "_current_job_id", None),
    "model": config.get("model") or config.get("sd_model_checkpoint"),  # NOT RELIABLY SET
    "vae": config.get("vae") or "Automatic",                             # NOT PASSED FROM GUI
    "requested_seed": config.get("seed", -1),                            # Still showing -1
    "actual_seed": gen_info.get("seed"),                                 # This IS extracted
    "actual_subseed": gen_info.get("subseed"),                          # This IS extracted
    "stage_duration_ms": stage_duration_ms,
}
```

**Issues**:
1. `model` falls back to `sd_model_checkpoint` which may not be in config
2. `vae` not passed from GUI config building
3. `requested_seed` still shows -1 because GUI doesn't send actual seed to NJR
4. Refiner data exists in `gen_info` but not extracted to metadata root
5. Hires fix config passed with defaults instead of GUI values

#### Implementation Plan

**Step 1**: Fix model/VAE recording
- **File**: `src/controller/app_controller.py` - `_extract_txt2img_config_from_gui_v2`
- **Change**: Ensure `base_model` and `vae` are always present in NJR
- **Validation**: Check that `self._get_value("model_dropdown")` populates NJR base_model

**Step 2**: Fix seed recording
- **File**: `src/pipeline/executor.py` - `run_txt2img_v2`
- **Change**: Extract `seed`, `subseed`, `subseed_strength` from `gen_info` to metadata root
- **Add fields**:
  ```python
  metadata["requested_seed"] = config.get("seed", -1)  # Keep this
  metadata["actual_seed"] = gen_info.get("seed")        # Already there
  metadata["actual_subseed"] = gen_info.get("subseed")  # Already there
  metadata["subseed_strength"] = gen_info.get("subseed_strength", 0.0)  # NEW
  ```

**Step 3**: Fix refiner recording
- **File**: `src/pipeline/executor.py` - `run_txt2img_v2`
- **Change**: Add refiner section to metadata
  ```python
  # After extracting gen_info
  if config.get("use_refiner"):
      metadata["refiner"] = {
          "enabled": True,
          "model": config.get("refiner_checkpoint"),
          "switch_at": config.get("refiner_switch_at", 0.8),
      }
  else:
      metadata["refiner"] = {"enabled": False}
  ```

**Step 4**: Fix hires fix denoising
- **File**: `src/controller/app_controller.py` - `_extract_txt2img_config_from_gui_v2`
- **Location**: Line ~777 `"hires_fix": {`
- **Problem**: Using `.get("hr_denoising_strength", 0.7)` - should read from GUI widget
- **Fix**:
  ```python
  "hires_fix": {
      "enabled": self._get_value("enable_hr_fix"),
      "upscaler": self._get_value("hr_upscaler_dropdown"),
      "upscale_by": float(self._get_value("hr_scale_spinbox")),
      "denoising_strength": float(self._get_value("hr_denoise_spinbox")),  # READ FROM GUI
  }
  ```

#### Testing Plan
1. **Unit Test**: Create test job with known model/VAE/seed/refiner/hires
2. **Validation**: Check manifest JSON contains all fields
3. **Regression**: Verify existing manifests still load correctly
4. **Learning Module**: Verify learning can read model/VAE from manifest

#### Files Changed
- `src/pipeline/executor.py` (txt2img metadata building)
- `src/controller/app_controller.py` (GUI → NJR config extraction)
- `tests/test_manifest_recording.py` (NEW - validation tests)

---

### PR-GUI-DATA-002: Fix Job History Display (Extraction Logic)
**Priority**: HIGH
**Estimated Effort**: 3-4 hours
**Dependencies**: PR-GUI-DATA-001 (for complete manifest data)

#### Problem Statement
Job history table shows blanks or wrong data:
- Model column empty (should show model name)
- Duration column empty (should show "2m 34s")
- Seed column empty (should show actual seed)
- Pack/Prompt column shows generic text instead of pack name + prompt preview

#### Root Cause Analysis

**Location**: `src/gui/job_history_panel_v2.py` lines 154-197

```python
def _entry_values(self, entry: JobHistoryEntry) -> tuple[str, ...]:
    time_text = self._format_time(entry.completed_at or entry.started_at or entry.created_at)
    status = entry.status.value
    
    # Extract model
    model = self._extract_model(entry)  # RETURNS EMPTY OR "-"
    
    # Extract better summary from NJR snapshot
    packs = self._extract_summary(entry)  # RETURNS GENERIC TEXT
    
    # Calculate duration more robustly
    duration = self._ensure_duration(entry)  # RETURNS EMPTY
    
    # Extract seed
    seed = self._extract_seed(entry)  # RETURNS "-"
    
    # Extract image count from result or NJR snapshot
    images = self._extract_image_count(entry)
    
    # Get actual output folder from result or job_id
    output = self._extract_output_folder(entry)
    
    return (time_text, status, model, packs, duration, seed, images, output)
```

**The helper methods** (`_extract_model`, `_extract_summary`, etc.) **don't exist yet** - they're placeholders!

#### Implementation Plan

**Step 1**: Implement `_extract_model(entry)`
```python
def _extract_model(self, entry: JobHistoryEntry) -> str:
    """Extract model name from NJR snapshot or result."""
    # Try NJR snapshot first
    if entry.snapshot:
        njr = entry.snapshot.get("normalized_job", {})
        model = njr.get("base_model")
        if model:
            # Shorten for display: "sd_xl_base_1.0.safetensors" → "sd_xl_base_1.0"
            return Path(model).stem
    
    # Try result metadata
    if entry.result and isinstance(entry.result, dict):
        metadata = entry.result.get("metadata", {})
        if isinstance(metadata, dict):
            model = metadata.get("model")
            if model:
                return Path(str(model)).stem
    
    return "-"
```

**Step 2**: Implement `_extract_seed(entry)`
```python
def _extract_seed(self, entry: JobHistoryEntry) -> str:
    """Extract actual seed from result or NJR."""
    # Try result first (has actual_seed from gen_info)
    if entry.result and isinstance(entry.result, dict):
        metadata = entry.result.get("metadata", {})
        if isinstance(metadata, dict):
            seed = metadata.get("actual_seed") or metadata.get("requested_seed")
            if seed is not None and seed != -1:
                return str(seed)
    
    # Try NJR snapshot
    if entry.snapshot:
        njr = entry.snapshot.get("normalized_job", {})
        seed = njr.get("seed")
        if seed is not None and seed != -1:
            return str(seed)
    
    return "-"
```

**Step 3**: Implement `_ensure_duration(entry)`
```python
def _ensure_duration(self, entry: JobHistoryEntry) -> str:
    """Calculate duration from timestamps."""
    start = entry.started_at or entry.created_at
    end = entry.completed_at
    
    if not start or not end:
        return "-"
    
    try:
        delta = (end - start).total_seconds()
        if delta < 60:
            return f"{int(delta)}s"
        elif delta < 3600:
            mins = int(delta // 60)
            secs = int(delta % 60)
            return f"{mins}m {secs}s"
        else:
            hours = int(delta // 3600)
            mins = int((delta % 3600) // 60)
            return f"{hours}h {mins}m"
    except Exception:
        return "-"
```

**Step 4**: Improve `_extract_summary(entry)` (already exists but needs enhancement)
```python
def _extract_summary(self, entry: JobHistoryEntry) -> str:
    """Extract pack name + prompt preview."""
    if entry.snapshot:
        njr = entry.snapshot.get("normalized_job", {})
        
        # Get pack name from source
        pack_name = None
        if njr.get("source") == "pack":
            pack_name = njr.get("pack_name") or njr.get("prompt_pack_id")
        
        # Get prompt
        prompt = njr.get("positive_prompt", "")
        
        if pack_name:
            prompt_preview = self._shorten(prompt, width=40)
            return f"{pack_name}: {prompt_preview}"
        elif prompt:
            return self._shorten(prompt, width=60)
    
    return "Job " + (entry.job_id[:8] if entry.job_id else "unknown")
```

#### Testing Plan
1. **Manual**: Run 3 jobs with different models/seeds/packs
2. **Verify**: History table shows correct model, seed, duration, pack name
3. **Edge Cases**: Test with missing data (old jobs, cancelled jobs)

#### Files Changed
- `src/gui/job_history_panel_v2.py` (add extraction methods)

---

### PR-GUI-DATA-003: Fix Queue Up/Down Buttons (Reordering Logic)
**Priority**: HIGH  
**Estimated Effort**: 2-3 hours
**Dependencies**: None

#### Problem Statement
Queue panel "▲ Up" and "▼ Down" buttons move the viewing window selection instead of actually reordering jobs in the queue.

#### Root Cause Analysis

**Location**: `src/gui/panels_v2/queue_panel_v2.py` lines ~600-650

```python
def _on_move_up(self) -> None:
    """Move selected job up in queue."""
    idx = self._get_selected_index()
    if idx is None or idx == 0:
        return
    
    # PROBLEM: This just changes listbox selection, not queue order!
    self.job_listbox.selection_clear(0, tk.END)
    self.job_listbox.selection_set(idx - 1)
    self.job_listbox.see(idx - 1)
```

**Missing**: Call to controller to actually reorder the queue in `QueueStoreV2`.

#### Implementation Plan

**Step 1**: Add reorder methods to QueueStoreV2
```python
# src/services/queue_store_v2.py

def move_job_up(self, job_id: str) -> bool:
    """Move job up one position in queue."""
    with self._lock:
        try:
            idx = next(i for i, j in enumerate(self._queue) if j.job_id == job_id)
            if idx > 0:
                self._queue[idx], self._queue[idx - 1] = self._queue[idx - 1], self._queue[idx]
                self._mark_dirty()
                return True
        except StopIteration:
            pass
    return False

def move_job_down(self, job_id: str) -> bool:
    """Move job down one position in queue."""
    with self._lock:
        try:
            idx = next(i for i, j in enumerate(self._queue) if j.job_id == job_id)
            if idx < len(self._queue) - 1:
                self._queue[idx], self._queue[idx + 1] = self._queue[idx + 1], self._queue[idx]
                self._mark_dirty()
                return True
        except StopIteration:
            pass
    return False
```

**Step 2**: Add controller methods
```python
# src/controller/app_controller.py

def move_queue_job_up(self, job_id: str) -> None:
    """Move job up in queue and refresh UI."""
    if self.job_service and self.job_service.queue_store:
        success = self.job_service.queue_store.move_job_up(job_id)
        if success:
            self._sync_queue_to_app_state()

def move_queue_job_down(self, job_id: str) -> None:
    """Move job down in queue and refresh UI."""
    if self.job_service and self.job_service.queue_store:
        success = self.job_service.queue_store.move_job_down(job_id)
        if success:
            self._sync_queue_to_app_state()
```

**Step 3**: Fix queue panel buttons
```python
# src/gui/panels_v2/queue_panel_v2.py

def _on_move_up(self) -> None:
    """Move selected job up in queue."""
    job = self._get_selected_job()
    if not job or not self.controller:
        return
    
    # Actually reorder in queue
    if hasattr(self.controller, "move_queue_job_up"):
        self.controller.move_queue_job_up(job.job_id)

def _on_move_down(self) -> None:
    """Move selected job down in queue."""
    job = self._get_selected_job()
    if not job or not self.controller:
        return
    
    # Actually reorder in queue
    if hasattr(self.controller, "move_queue_job_down"):
        self.controller.move_queue_job_down(job.job_id)
```

#### Testing Plan
1. **Manual**: Add 5 jobs to queue
2. **Select** job #3, click "▲ Up"
3. **Verify**: Job #3 is now at position #2 (check queue order and "Send Job" sends correct job)
4. **Regression**: Ensure persistence works (restart app, queue order preserved)

#### Files Changed
- `src/services/queue_store_v2.py` (add move methods)
- `src/controller/app_controller.py` (add controller methods)
- `src/gui/panels_v2/queue_panel_v2.py` (fix button handlers)

---

### PR-GUI-DATA-004: Add Image Filter Results Display (Reprocess Panel)
**Priority**: MEDIUM
**Estimated Effort**: 3-4 hours
**Dependencies**: None (already partially implemented)

#### Problem Statement
Image filtering results only shown in logs, not visible in GUI. User wants:
- Summary text: "400 images found in 2 folders, after txt2img filter → 200, after dimension filter → 180"
- Scrollable table showing: folder/file name, total images, images after filtering

#### Implementation Plan

**Step 1**: Add summary label and table to reprocess panel
```python
# src/gui/panels_v2/reprocess_panel_v2.py (after folder_options_frame)

# Filter results display
self.filter_results_frame = ttk.LabelFrame(self, text="Filter Results", padding=8)
self.filter_results_frame.grid(row=current_row, column=0, sticky="ew", padx=4, pady=(0, 8))
current_row += 1

# Summary text
self.filter_summary_label = ttk.Label(
    self.filter_results_frame,
    text="No folders selected",
    style=BODY_LABEL_STYLE,
)
self.filter_summary_label.pack(anchor="w", pady=(0, 4))

# Table with columns: Source | Total | After Filters
columns = ("source", "total", "filtered")
self.filter_results_tree = ttk.Treeview(
    self.filter_results_frame,
    columns=columns,
    show="headings",
    height=6,
)
self.filter_results_tree.heading("source", text="Folder / File")
self.filter_results_tree.heading("total", text="Total Images")
self.filter_results_tree.heading("filtered", text="After Filters")

self.filter_results_tree.column("source", width=250, anchor="w")
self.filter_results_tree.column("total", width=80, anchor="center")
self.filter_results_tree.column("filtered", width=80, anchor="center")

self.filter_results_tree.pack(fill="both", expand=True, pady=(0, 4))

# Scrollbar
filter_scroll = ttk.Scrollbar(self.filter_results_tree, orient="vertical", command=self.filter_results_tree.yview)
filter_scroll.pack(side="right", fill="y")
self.filter_results_tree.configure(yscrollcommand=filter_scroll.set)
```

**Step 2**: Update `_scan_folders_for_images()` to populate table
```python
def _scan_folders_for_images(self) -> None:
    """Scan selected folders for images, applying filters."""
    # ... existing code ...
    
    # Track per-folder counts
    folder_stats = {}
    
    for folder in self.selected_folders:
        folder_images = []
        if recursive:
            for ext in image_extensions:
                folder_images.extend(folder.rglob(f"*{ext}"))
        else:
            folder_images.extend([
                f for f in folder.iterdir()
                if f.is_file() and f.suffix.lower() in image_extensions
            ])
        
        folder_stats[str(folder)] = {
            "total": len(folder_images),
            "images": folder_images,
        }
        all_images.extend(folder_images)
    
    total_found = len(all_images)
    
    # Apply filters and track per-folder
    # ... existing filter code ...
    
    # Update summary label
    summary = f"{total_found} images found in {len(self.selected_folders)} folder(s)"
    if filename_filter:
        summary += f", after txt2img filter → {len(all_images)}"
    if dimension_filter_enabled:
        summary += f", after dimension filter → {len(all_images)}"
    self.filter_summary_label.config(text=summary)
    
    # Update table
    self.filter_results_tree.delete(*self.filter_results_tree.get_children())
    for folder_path, stats in folder_stats.items():
        # Count how many from this folder passed filters
        filtered_count = sum(1 for img in all_images if str(img).startswith(folder_path))
        self.filter_results_tree.insert(
            "",
            "end",
            values=(
                Path(folder_path).name,
                stats["total"],
                filtered_count,
            ),
        )
```

#### Testing Plan
1. **Manual**: Select 2 folders with 100 and 50 images
2. **Set filter**: "txt2img" filename
3. **Verify**: Summary shows "150 images found in 2 folders, after txt2img filter → 80"
4. **Verify**: Table shows both folders with their counts

#### Files Changed
- `src/gui/panels_v2/reprocess_panel_v2.py` (add table widget, update scan logic)

---

### PR-GUI-DATA-005: Fix Preview Thumbnail & Time Estimator
**Priority**: HIGH
**Estimated Effort**: 4-5 hours
**Dependencies**: None

#### Problem Statement
- Preview thumbnail widget exists but never shows images
- Job time estimator never updates during job execution

#### Root Cause Analysis

**Preview Thumbnail**: `src/gui/preview_panel_v2.py` line 82
```python
self.thumbnail = ThumbnailWidget(
    self.thumbnail_frame,
    width=150,
    height=150,
    placeholder_text="No Preview",
)
```

Widget exists but is never told to load an image. Missing:
- Job selection handler that loads latest output image
- Output monitoring to show images as they're generated

**Time Estimator**: Progress tracking exists but ETA not calculated/displayed

#### Implementation Plan

**Step 1**: Add thumbnail update logic
```python
# src/gui/preview_panel_v2.py

def update_with_summary(self, summary: UnifiedJobSummary | None) -> None:
    """Update preview with job summary and latest output image."""
    if not summary:
        self.thumbnail.clear()
        return
    
    # ... existing text updates ...
    
    # Update thumbnail with latest output image
    if self._show_preview_var.get():
        latest_image = self._find_latest_output_image(summary)
        if latest_image:
            self.thumbnail.load_image(latest_image)
        else:
            self.thumbnail.clear()

def _find_latest_output_image(self, summary: UnifiedJobSummary) -> Path | None:
    """Find the most recently generated image for this job."""
    # Check result for output images
    if summary.result:
        metadata = summary.result.get("metadata", {})
        if isinstance(metadata, list):
            # Multiple stages - get last one
            last_stage = metadata[-1]
            output_path = last_stage.get("path")
            if output_path and Path(output_path).exists():
                return Path(output_path)
    
    # Fallback: scan output folder for this job_id
    output_folder = Path("outputs") / summary.job_id
    if output_folder.exists():
        images = sorted(output_folder.glob("*.png"), key=lambda p: p.stat().st_mtime, reverse=True)
        if images:
            return images[0]
    
    return None
```

**Step 2**: Fix time estimator in running job panel
```python
# src/gui/panels_v2/running_job_panel_v2.py

def _on_running_summary_changed(self) -> None:
    """Update display when running job summary changes."""
    summary = self.app_state.running_job_summary if self.app_state else None
    
    # ... existing code ...
    
    # Calculate and show ETA
    if summary and summary.progress_percent:
        elapsed = (datetime.now() - summary.started_at).total_seconds() if summary.started_at else 0
        if summary.progress_percent > 0:
            total_estimated = elapsed / (summary.progress_percent / 100.0)
            remaining = total_estimated - elapsed
            self.eta_label.config(text=f"ETA: {self._format_seconds(remaining)}")
        else:
            self.eta_label.config(text="ETA: Calculating...")
    else:
        self.eta_label.config(text="")

def _format_seconds(self, seconds: float) -> str:
    """Format seconds to MM:SS or HH:MM:SS."""
    if seconds < 60:
        return f"{int(seconds)}s"
    elif seconds < 3600:
        mins = int(seconds // 60)
        secs = int(seconds % 60)
        return f"{mins}:{secs:02d}"
    else:
        hours = int(seconds // 3600)
        mins = int((seconds % 3600) // 60)
        return f"{hours}:{mins:02d}:00"
```

#### Testing Plan
1. **Thumbnail**: Run job, verify thumbnail shows latest image
2. **Time Estimator**: Run 2-minute job, verify ETA counts down
3. **Progress Updates**: Verify ETA recalculates as job progresses

#### Files Changed
- `src/gui/preview_panel_v2.py` (add thumbnail loading)
- `src/gui/panels_v2/running_job_panel_v2.py` (add ETA calculation)

---

### PR-GUI-DATA-006: Enhance Job Lifecycle Log Display
**Priority**: LOW
**Estimated Effort**: 1-2 hours
**Dependencies**: None

#### Problem Statement
Job lifecycle log panel exists but doesn't show useful information.

#### Current State
The panel subscribes to events but formatting is too verbose/technical.

#### Implementation Plan

Enhance `_format_event` to show user-friendly messages:
```python
def _format_event(self, event: JobLifecycleLogEvent) -> str:
    """Format lifecycle event for display."""
    ts = event.timestamp.strftime("%H:%M:%S")
    
    # User-friendly event descriptions
    if event.event_type == "job_created":
        msg = f"Job {event.job_id[:8]} created"
    elif event.event_type == "job_queued":
        msg = f"Job {event.job_id[:8]} added to queue"
    elif event.event_type == "job_started":
        msg = f"Job {event.job_id[:8]} started"
    elif event.event_type == "stage_started":
        stage = event.message.split()[-1] if event.message else "unknown"
        msg = f"Started {stage} stage"
    elif event.event_type == "stage_completed":
        stage = event.message.split()[-1] if event.message else "unknown"
        msg = f"Completed {stage} stage"
    elif event.event_type == "job_completed":
        msg = f"Job {event.job_id[:8]} completed ✓"
    elif event.event_type == "job_failed":
        msg = f"Job {event.job_id[:8]} failed ✗"
    else:
        msg = event.message
    
    return f"{ts} | {msg}"
```

#### Files Changed
- `src/gui/panels_v2/debug_log_panel_v2.py` (enhance formatting)

---

### PR-GUI-DATA-007: Add Default Value Warning System
**Priority**: MEDIUM
**Estimated Effort**: 3-4 hours
**Dependencies**: None

#### Problem Statement
No visibility into when default values are used vs user-provided values. Need [WARN] tags in logs to identify config extraction issues.

#### Implementation Plan

**Step 1**: Add logging decorator for config extraction
```python
# src/utils/config_helpers.py (NEW FILE)

import logging
from functools import wraps
from typing import Any

logger = logging.getLogger(__name__)

def log_default_value(param_name: str, default_value: Any, source: str = "unknown"):
    """Log when a default value is used instead of user input."""
    logger.warning(
        f"[WARN] Using default value for '{param_name}' = {default_value} (source: {source})"
    )

def track_defaults(param_map: dict[str, Any]):
    """Decorator to track when defaults are used in config extraction."""
    def decorator(func):
        @wraps(func)
        def wrapper(*args, **kwargs):
            result = func(*args, **kwargs)
            
            # Check which params used defaults
            for param, default in param_map.items():
                if result.get(param) == default:
                    log_default_value(param, default, source=func.__name__)
            
            return result
        return wrapper
    return decorator
```

**Step 2**: Apply to config extraction methods
```python
# src/controller/app_controller.py

@track_defaults({
    "steps": 20,
    "cfg_scale": 7.0,
    "denoising_strength": 0.7,
})
def _extract_txt2img_config_from_gui_v2(self) -> dict[str, Any]:
    """Extract txt2img config, tracking defaults."""
    # ... existing code ...
```

**Step 3**: Add validation warnings for missing GUI values
```python
def _get_value(self, widget_name: str, default: Any = None) -> Any:
    """Get widget value with default tracking."""
    value = self._widgets.get(widget_name)
    
    if value is None and default is not None:
        logger.warning(
            f"[WARN] Widget '{widget_name}' not found, using default: {default}"
        )
        return default
    
    return value
```

#### Testing Plan
1. **Remove widget**: Delete a GUI widget temporarily
2. **Run job**: Verify [WARN] message appears in log
3. **Check config**: Verify default value was used

#### Files Changed
- `src/utils/config_helpers.py` (NEW - logging utilities)
- `src/controller/app_controller.py` (add default tracking)

---

### PR-GUI-DATA-008: Implement ADetailer Two-Pass Controls & Advanced Settings
**Priority**: MEDIUM
**Estimated Effort**: 6-8 hours
**Dependencies**: None

#### Problem Statement
ADetailer configuration is incomplete - GUI only exposes single-pass controls:
- **Currently exposed**: model, confidence, max detections, mask blur, merge mode, face/hands toggles, steps/CFG/sampler/denoise, prompts, padding
- **Missing (hardcoded in executor)**:
  - Separate hands pass model/settings
  - Per-pass enable toggles (face pass, hands pass)
  - Mask filter method (largest/all) and parameters (k, min_ratio, max_ratio)
  - Dilate/erode value
  - Scheduler override
  - Per-pass padding
  - Mask feathering
  - Inpainting options (mask_blur, inpaint_padding, inpaint_only_masked)

Users cannot configure two-pass workflows or fine-tune mask filtering without editing code.

#### Current State Analysis

**ADetailerStageCardV2** (`src/gui/stage_cards_v2/adetailer_card_v2.py`):
- Has face model dropdown, but no hands model dropdown
- Has single "padding" field, not per-pass
- Missing mask filter controls entirely
- Missing dilate/erode slider
- Missing scheduler dropdown
- Missing feather slider
- Missing inpainting detail controls

**Executor** (`src/pipeline/executor.py` - `run_adetailer_v2`):
- Hardcodes hands pass: `ad_model_2 = "hand_yolov8n.pt"`
- Hardcodes mask filter: `"ad_mask_k_largest": 3, "ad_mask_min_ratio": 0.01`
- Hardcodes dilate/erode: `"ad_dilate_erode": 4`
- Uses single padding value for both passes

#### Implementation Plan

**Step 1**: Add Two-Pass Controls Section to GUI
```python
# src/gui/stage_cards_v2/adetailer_card_v2.py

# After existing model dropdown, add two-pass section:
two_pass_frame = ttk.LabelFrame(settings_frame, text="Pass Configuration", padding=8)
two_pass_frame.grid(row=current_row, column=0, columnspan=2, sticky="ew", pady=4)
current_row += 1

# Face pass toggle + model
self.enable_face_pass_var = tk.BooleanVar(value=True)
face_pass_check = ttk.Checkbutton(
    two_pass_frame,
    text="Face Pass",
    variable=self.enable_face_pass_var,
    style="Dark.TCheckbutton",
)
face_pass_check.grid(row=0, column=0, sticky="w")

self.face_model_var = tk.StringVar(value="face_yolov8n.pt")
face_model_combo = ttk.Combobox(
    two_pass_frame,
    textvariable=self.face_model_var,
    values=["face_yolov8n.pt", "face_yolov8s.pt", "mediapipe_face_full"],
    width=20,
    state="readonly",
)
face_model_combo.grid(row=0, column=1, sticky="w", padx=(8, 0))

# Hands pass toggle + model
self.enable_hands_pass_var = tk.BooleanVar(value=False)
hands_pass_check = ttk.Checkbutton(
    two_pass_frame,
    text="Hands Pass",
    variable=self.enable_hands_pass_var,
    style="Dark.TCheckbutton",
)
hands_pass_check.grid(row=1, column=0, sticky="w", pady=(4, 0))

self.hands_model_var = tk.StringVar(value="hand_yolov8n.pt")
hands_model_combo = ttk.Combobox(
    two_pass_frame,
    textvariable=self.hands_model_var,
    values=["hand_yolov8n.pt", "hand_yolov8s.pt"],
    width=20,
    state="readonly",
)
hands_model_combo.grid(row=1, column=1, sticky="w", padx=(8, 0))

# Per-pass padding (replace single padding field)
ttk.Label(two_pass_frame, text="Face Padding:", style="Body.TLabel").grid(row=2, column=0, sticky="w", pady=(4, 0))
self.face_padding_var = tk.IntVar(value=32)
face_padding_spin = ttk.Spinbox(
    two_pass_frame,
    from_=0,
    to=256,
    textvariable=self.face_padding_var,
    width=8,
)
face_padding_spin.grid(row=2, column=1, sticky="w", padx=(8, 0), pady=(4, 0))

ttk.Label(two_pass_frame, text="Hands Padding:", style="Body.TLabel").grid(row=3, column=0, sticky="w", pady=(4, 0))
self.hands_padding_var = tk.IntVar(value=32)
hands_padding_spin = ttk.Spinbox(
    two_pass_frame,
    from_=0,
    to=256,
    textvariable=self.hands_padding_var,
    width=8,
)
hands_padding_spin.grid(row=3, column=1, sticky="w", padx=(8, 0), pady=(4, 0))
```

**Step 2**: Add Mask Filter Controls Section
```python
# src/gui/stage_cards_v2/adetailer_card_v2.py

mask_filter_frame = ttk.LabelFrame(settings_frame, text="Mask Filtering", padding=8)
mask_filter_frame.grid(row=current_row, column=0, columnspan=2, sticky="ew", pady=4)
current_row += 1

# Filter method
ttk.Label(mask_filter_frame, text="Method:", style="Body.TLabel").grid(row=0, column=0, sticky="w")
self.mask_filter_method_var = tk.StringVar(value="largest")
method_combo = ttk.Combobox(
    mask_filter_frame,
    textvariable=self.mask_filter_method_var,
    values=["largest", "all"],
    width=10,
    state="readonly",
)
method_combo.grid(row=0, column=1, sticky="w", padx=(8, 0))

# K (max detections)
ttk.Label(mask_filter_frame, text="Max Detections (k):", style="Body.TLabel").grid(row=1, column=0, sticky="w", pady=(4, 0))
self.mask_k_var = tk.IntVar(value=3)
k_spin = ttk.Spinbox(
    mask_filter_frame,
    from_=1,
    to=10,
    textvariable=self.mask_k_var,
    width=8,
)
k_spin.grid(row=1, column=1, sticky="w", padx=(8, 0), pady=(4, 0))

# Min ratio (filter tiny detections)
ttk.Label(mask_filter_frame, text="Min Ratio:", style="Body.TLabel").grid(row=2, column=0, sticky="w", pady=(4, 0))
self.mask_min_ratio_var = tk.DoubleVar(value=0.01)
min_ratio_spin = ttk.Spinbox(
    mask_filter_frame,
    from_=0.0,
    to=1.0,
    increment=0.01,
    textvariable=self.mask_min_ratio_var,
    width=8,
)
min_ratio_spin.grid(row=2, column=1, sticky="w", padx=(8, 0), pady=(4, 0))

# Max ratio (filter huge detections)
ttk.Label(mask_filter_frame, text="Max Ratio:", style="Body.TLabel").grid(row=3, column=0, sticky="w", pady=(4, 0))
self.mask_max_ratio_var = tk.DoubleVar(value=1.0)
max_ratio_spin = ttk.Spinbox(
    mask_filter_frame,
    from_=0.0,
    to=1.0,
    increment=0.01,
    textvariable=self.mask_max_ratio_var,
    width=8,
)
max_ratio_spin.grid(row=3, column=1, sticky="w", padx=(8, 0), pady=(4, 0))
```

**Step 3**: Add Mask Processing Controls Section
```python
# src/gui/stage_cards_v2/adetailer_card_v2.py

mask_proc_frame = ttk.LabelFrame(settings_frame, text="Mask Processing", padding=8)
mask_proc_frame.grid(row=current_row, column=0, columnspan=2, sticky="ew", pady=4)
current_row += 1

# Dilate/Erode
ttk.Label(mask_proc_frame, text="Dilate/Erode:", style="Body.TLabel").grid(row=0, column=0, sticky="w")
self.dilate_erode_var = tk.IntVar(value=4)
dilate_spin = ttk.Spinbox(
    mask_proc_frame,
    from_=-32,
    to=32,
    textvariable=self.dilate_erode_var,
    width=8,
)
dilate_spin.grid(row=0, column=1, sticky="w", padx=(8, 0))

# Mask blur (already exists, keep it)

# Mask feather (NEW)
ttk.Label(mask_proc_frame, text="Feather:", style="Body.TLabel").grid(row=2, column=0, sticky="w", pady=(4, 0))
self.mask_feather_var = tk.IntVar(value=5)
feather_spin = ttk.Spinbox(
    mask_proc_frame,
    from_=0,
    to=64,
    textvariable=self.mask_feather_var,
    width=8,
)
feather_spin.grid(row=2, column=1, sticky="w", padx=(8, 0), pady=(4, 0))
```

**Step 4**: Add Inpainting Detail Controls Section
```python
# src/gui/stage_cards_v2/adetailer_card_v2.py

inpaint_frame = ttk.LabelFrame(settings_frame, text="Inpainting Options", padding=8)
inpaint_frame.grid(row=current_row, column=0, columnspan=2, sticky="ew", pady=4)
current_row += 1

# Inpaint padding
ttk.Label(inpaint_frame, text="Inpaint Padding:", style="Body.TLabel").grid(row=0, column=0, sticky="w")
self.inpaint_padding_var = tk.IntVar(value=32)
inpaint_pad_spin = ttk.Spinbox(
    inpaint_frame,
    from_=0,
    to=256,
    textvariable=self.inpaint_padding_var,
    width=8,
)
inpaint_pad_spin.grid(row=0, column=1, sticky="w", padx=(8, 0))

# Only masked toggle
self.inpaint_only_masked_var = tk.BooleanVar(value=True)
only_masked_check = ttk.Checkbutton(
    inpaint_frame,
    text="Only Masked",
    variable=self.inpaint_only_masked_var,
    style="Dark.TCheckbutton",
)
only_masked_check.grid(row=1, column=0, columnspan=2, sticky="w", pady=(4, 0))

# Scheduler override
ttk.Label(inpaint_frame, text="Scheduler:", style="Body.TLabel").grid(row=2, column=0, sticky="w", pady=(4, 0))
self.scheduler_var = tk.StringVar(value="Use sampler default")
scheduler_combo = ttk.Combobox(
    inpaint_frame,
    textvariable=self.scheduler_var,
    values=["Use sampler default", "Automatic", "Karras", "Exponential", "SGM Uniform"],
    width=20,
    state="readonly",
)
scheduler_combo.grid(row=2, column=1, sticky="w", padx=(8, 0), pady=(4, 0))
```

**Step 5**: Update Config Extraction in Controller
```python
# src/controller/app_controller.py - _extract_adetailer_config_from_gui_v2

def _extract_adetailer_config_from_gui_v2(self) -> dict[str, Any]:
    """Extract ADetailer config with two-pass support."""
    return {
        # Existing fields...
        "adetailer_model": self._get_value("adetailer_face_model_var"),
        "adetailer_steps": int(self._get_value("adetailer_steps_var")),
        "adetailer_cfg": float(self._get_value("adetailer_cfg_var")),
        "adetailer_denoise": float(self._get_value("adetailer_denoise_var")),
        "adetailer_sampler": self._get_value("adetailer_sampler_var"),
        
        # NEW: Two-pass settings
        "enable_face_pass": self._get_value("enable_face_pass_var"),
        "face_model": self._get_value("face_model_var"),
        "face_padding": int(self._get_value("face_padding_var")),
        "enable_hands_pass": self._get_value("enable_hands_pass_var"),
        "hands_model": self._get_value("hands_model_var"),
        "hands_padding": int(self._get_value("hands_padding_var")),
        
        # NEW: Mask filter settings
        "mask_filter_method": self._get_value("mask_filter_method_var"),
        "mask_k_largest": int(self._get_value("mask_k_var")),
        "mask_min_ratio": float(self._get_value("mask_min_ratio_var")),
        "mask_max_ratio": float(self._get_value("mask_max_ratio_var")),
        
        # NEW: Mask processing
        "mask_dilate_erode": int(self._get_value("dilate_erode_var")),
        "mask_blur": int(self._get_value("mask_blur_var")),  # Already exists
        "mask_feather": int(self._get_value("mask_feather_var")),
        
        # NEW: Inpainting options
        "inpaint_padding": int(self._get_value("inpaint_padding_var")),
        "inpaint_only_masked": self._get_value("inpaint_only_masked_var"),
        "scheduler": self._get_value("scheduler_var"),
    }
```

**Step 6**: Update Executor to Use Config Values (Remove Hardcoded Defaults)
```python
# src/pipeline/executor.py - run_adetailer_v2

def run_adetailer_v2(self, config: dict, init_image: str) -> dict:
    """Run ADetailer with two-pass support and user-configurable settings."""
    
    # Build args list for enabled passes
    args = []
    
    # Face pass (if enabled)
    if config.get("enable_face_pass", True):
        face_args = {
            "ad_model": config.get("face_model", "face_yolov8n.pt"),
            "ad_prompt": config.get("adetailer_prompt", ""),
            "ad_negative_prompt": config.get("adetailer_negative_prompt", ""),
            "ad_confidence": config.get("adetailer_confidence", 0.3),
            "ad_mask_k_largest": config.get("mask_k_largest", 3),
            "ad_mask_min_ratio": config.get("mask_min_ratio", 0.01),
            "ad_mask_max_ratio": config.get("mask_max_ratio", 1.0),
            "ad_dilate_erode": config.get("mask_dilate_erode", 4),
            "ad_mask_blur": config.get("mask_blur", 4),
            "ad_inpaint_only_masked": config.get("inpaint_only_masked", True),
            "ad_inpaint_only_masked_padding": config.get("face_padding", 32),
            "ad_mask_merge_invert": config.get("adetailer_merge_mode", "None"),
        }
        args.append(face_args)
    
    # Hands pass (if enabled)
    if config.get("enable_hands_pass", False):
        hands_args = {
            "ad_model": config.get("hands_model", "hand_yolov8n.pt"),
            "ad_prompt": config.get("adetailer_prompt", ""),
            "ad_negative_prompt": config.get("adetailer_negative_prompt", ""),
            "ad_confidence": config.get("adetailer_confidence", 0.3),
            "ad_mask_k_largest": config.get("mask_k_largest", 3),
            "ad_mask_min_ratio": config.get("mask_min_ratio", 0.01),
            "ad_mask_max_ratio": config.get("mask_max_ratio", 1.0),
            "ad_dilate_erode": config.get("mask_dilate_erode", 4),
            "ad_mask_blur": config.get("mask_blur", 4),
            "ad_inpaint_only_masked": config.get("inpaint_only_masked", True),
            "ad_inpaint_only_masked_padding": config.get("hands_padding", 32),
            "ad_mask_merge_invert": config.get("adetailer_merge_mode", "None"),
        }
        args.append(hands_args)
    
    # Build payload
    payload = {
        "init_images": [init_image],
        "prompt": config.get("adetailer_prompt", ""),
        "negative_prompt": config.get("adetailer_negative_prompt", ""),
        "sampler_name": config.get("adetailer_sampler", "DPM++ 2M Karras"),
        "steps": config.get("adetailer_steps", 14),
        "cfg_scale": config.get("adetailer_cfg", 5.5),
        "denoising_strength": config.get("adetailer_denoise", 0.32),
        "width": payload_width,
        "height": payload_height,
        "alwayson_scripts": {
            "ADetailer": {
                "args": args,  # Now contains user-configured passes
            }
        },
    }
    
    # Add scheduler if specified
    scheduler = config.get("scheduler")
    if scheduler and scheduler != "Use sampler default":
        payload["scheduler"] = scheduler
    
    # ... rest of execution logic ...
```

**Step 7**: Update Sidebar Config Reading (if applicable)
If ADetailer settings are read from sidebar config files, ensure new fields are included in the schema.

#### Testing Plan
1. **Two-pass workflow**: Enable both face and hands passes with different models/padding
2. **Verify payload**: Check WebUI receives separate args entries for each pass
3. **Mask filtering**: Set k=2, min_ratio=0.05, verify only 2 largest detections processed
4. **Dilate/erode**: Set to 8, verify mask expansion in output
5. **Scheduler**: Test with "Karras" override, verify applied
6. **Single-pass backward compat**: Disable hands pass, verify face-only works
7. **Visual quality**: Compare before/after with fine-tuned settings

#### Files Changed
- `src/gui/stage_cards_v2/adetailer_card_v2.py` (add 30+ new widgets in organized sections)
- `src/controller/app_controller.py` (update config extraction)
- `src/pipeline/executor.py` (remove hardcoded values, use config)
- `tests/test_adetailer_two_pass.py` (NEW - validation tests)

#### Migration Notes
- Existing jobs will use default values for new fields (backward compatible)
- Users can now customize two-pass workflows without code changes
- All hardcoded executor defaults now exposed in GUI

---

### PR-GUI-DATA-009: Fix Reprocess Panel Dark Mode Theming
**Priority**: LOW
**Estimated Effort**: 1 hour
**Dependencies**: None

#### Problem Statement
Reprocess panel widgets (spinboxes, entries, checkboxes) use light theme instead of dark mode.

#### Implementation Plan

Apply dark theme styles:
```python
# src/gui/panels_v2/reprocess_panel_v2.py

# Change all widget creations to use dark styles:
self.filename_filter_entry = ttk.Entry(
    filename_frame,
    textvariable=self.filename_filter_var,
    width=15,
    style="Dark.TEntry",  # ADD THIS
)

self.max_width_spinbox = ttk.Spinbox(
    dim_frame,
    from_=64,
    to=8192,
    increment=64,
    textvariable=self.max_width_var,
    width=8,
    style="Dark.TSpinbox",  # ADD THIS
)

# Same for all other widgets
```

#### Testing Plan
1. **Visual check**: Open reprocess panel in dark mode
2. **Verify**: All widgets use dark background/text

#### Files Changed
- `src/gui/panels_v2/reprocess_panel_v2.py` (apply dark styles)

---

## Implementation Order (Recommended)

### Phase 1: Data Integrity (CRITICAL)
1. **PR-GUI-DATA-001**: Fix manifest recording (model, VAE, seeds, refiner)
2. **PR-GUI-DATA-002**: Fix job history display extraction

### Phase 2: Core UX (HIGH)
3. **PR-GUI-DATA-003**: Fix queue up/down buttons
4. **PR-GUI-DATA-005**: Fix preview thumbnail & time estimator

### Phase 3: Visibility (MEDIUM)
5. **PR-GUI-DATA-004**: Add image filter results display
6. **PR-GUI-DATA-007**: Add default value warning system
7. **PR-GUI-DATA-008**: Implement ADetailer recommendations

### Phase 4: Polish (LOW)
8. **PR-GUI-DATA-006**: Enhance job lifecycle log
9. **PR-GUI-DATA-009**: Fix reprocess panel dark mode

---

## Testing Strategy

### Automated Tests
- **Manifest validation**: `tests/test_manifest_recording.py`
- **Queue reordering**: `tests/test_queue_operations.py`
- **Config extraction**: `tests/test_config_defaults.py`

### Manual Testing Checklist
- [ ] Run full pipeline job, verify manifest contains model/VAE/seed/refiner
- [ ] Check job history shows correct model, duration, seed
- [ ] Reorder queue with up/down, verify "Send Job" sends correct job
- [ ] Verify preview thumbnail updates during job execution
- [ ] Check ETA counts down correctly
- [ ] Verify filter results table shows per-folder counts
- [ ] Test ADetailer with new mask/inpainting settings
- [ ] Verify [WARN] logs appear when defaults used
- [ ] Visual check: all widgets use dark mode theme

### Regression Testing
- [ ] Old manifests still load correctly
- [ ] Queue persistence works with reordering
- [ ] Existing jobs complete successfully
- [ ] Learning module still works with new manifest format

---

## Risk Assessment

### Low Risk
- Dark mode theming (cosmetic)
- Lifecycle log formatting (display only)
- Filter results display (additive)

### Medium Risk
- Queue reordering (touches queue state management)
- Default value tracking (new logging, potential noise)
- ADetailer config changes (payload structure change)

### High Risk
- Manifest format changes (affects learning, history, reproduction)
- Extraction logic (could break job history display)

### Mitigation Strategies
1. **Manifest changes**: Keep backward compatibility, add migration if needed
2. **Queue reordering**: Extensive testing with persistence
3. **Config extraction**: Thorough logging to identify issues early
4. **ADetailer**: Test with/without new fields, ensure fallbacks work

---

## Timeline Estimate

**Total Effort**: 30-40 hours
**Sprints** (assuming 2-week sprints, 20 hours/week):
- Sprint 1: PRs 001, 002, 003 (critical + high)
- Sprint 2: PRs 004, 005, 007 (high + medium)
- Sprint 3: PRs 006, 008, 009 (medium + low + polish)

---

## Conclusion

This PR series addresses **13 distinct issues** across data recording, UX, and theming. Priority is on data integrity (manifests) and core UX (queue, history, preview), followed by visibility improvements and polish.

Each PR is designed to be:
- **Atomic**: Independently testable and deployable
- **Safe**: Includes rollback strategy and regression tests
- **Documented**: Clear before/after examples

**Next Steps**:
1. Review this plan with team
2. Create GitHub issues for each PR
3. Begin Phase 1 implementation
4. Iterate based on testing feedback
