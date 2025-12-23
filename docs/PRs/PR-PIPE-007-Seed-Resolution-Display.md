# PR-PIPE-007 – Seed Resolution Display Everywhere

## Context

Currently, seed values are displayed incorrectly throughout the application:

1. **Preview Panel** - Shows `-1` (the request value) even after generation
2. **History Panel** - Shows `-1` or missing seed
3. **Running Job Panel** - Shows requested seed, not resolved
4. **Manifests** - Store `-1` instead of actual seed used

The Stable Diffusion WebUI returns the actual resolved seed in the `info` field of generation responses. This PR ensures:
1. Resolved seeds are captured after generation
2. All UI panels display the actual seed used
3. Users can reproduce successful generations

This PR builds on PR-PIPE-001 (which captures seeds in manifests) and extends the display changes from PR-PIPE-005 (history panel) to all other panels.

## Non-Goals

- Changing how seeds are requested (still support `-1` for random)
- Seed prediction or suggestion features
- Seed search/filter functionality
- Modifying NormalizedJobRecord structure
- Adding seed to file names

## Invariants

- Requested seed of `-1` is still valid and means "random"
- Display must clearly distinguish "Random" from actual seed values
- Resolved seed must be accurate (match actual WebUI generation)
- Seed display must never crash on missing/null values
- All panels must handle both old (no seed) and new (with seed) data

## Allowed Files

- `src/pipeline/executor.py` - Capture resolved seed from response
- `src/gui/preview_panel_v2.py` - Display seed correctly
- `src/gui/panels_v2/running_job_panel_v2.py` - Display seed during execution
- `src/gui/panels_v2/history_panel_v2.py` - Display seed in mini-history
- `src/gui/job_history_panel_v2.py` - Already covered in PR-PIPE-005
- `src/controller/app_controller.py` - Pass resolved seed through callbacks
- `tests/gui_v2/test_seed_display.py` (new)
- `tests/pipeline/test_executor_seed_resolution.py` (new)

## Do Not Touch

- `src/pipeline/job_models_v2.py` - NJR structure unchanged
- `src/queue/job_history_store.py` - Storage format unchanged
- `src/builder/*` - Job building unchanged
- `src/api/client.py` - API layer unchanged

## Interfaces

### Seed Resolution Result

```python
@dataclass
class SeedResolution:
    """Resolved seed information from WebUI response."""
    
    requested: int           # Original request (-1 for random)
    actual: int | None       # Resolved seed from response
    subseed: int | None      # Resolved subseed (if used)
    all_seeds: list[int]     # All seeds for batch
    all_subseeds: list[int]  # All subseeds for batch
    
    @property
    def display_value(self) -> str:
        """Get display-friendly seed value."""
        if self.actual is not None:
            return str(self.actual)
        if self.requested == -1:
            return "Random"
        return str(self.requested)
```

### Display Helper Function

```python
def format_seed_display(
    requested: int | None,
    actual: int | None = None,
    *,
    show_random: bool = True,
) -> str:
    """
    Format seed for display in UI.
    
    Args:
        requested: Requested seed value (-1 for random)
        actual: Resolved seed from generation (if available)
        show_random: If True, show "Random" for -1, else "-1"
        
    Returns:
        Display string: actual seed, "Random", or requested value
    """
```

### Error Behavior

- Null seed values: Display "-" or "Unknown"
- Requested=-1, Actual=None: Display "Random"
- Requested=-1, Actual=12345: Display "12345"
- Requested=12345, Actual=None: Display "12345"
- Invalid seed type: Log warning, display "-"

## Implementation Steps (Order Matters)

### Step 1: Add Seed Display Helper

Create utility function in `src/gui/utils/display_helpers.py` (or add to existing):

```python
"""Display helper functions for GUI components."""

from __future__ import annotations

from typing import Any


def format_seed_display(
    requested: int | None,
    actual: int | None = None,
    *,
    show_random: bool = True,
) -> str:
    """
    Format seed for display in UI.
    
    Priority:
    1. Use actual (resolved) seed if available
    2. Show "Random" for -1 if show_random=True
    3. Show requested seed
    4. Fall back to "-"
    
    Args:
        requested: Requested seed value (-1 for random)
        actual: Resolved seed from generation (if available)
        show_random: If True, show "Random" for -1 requests
        
    Returns:
        Display string
    """
    # Prefer actual seed
    if actual is not None and actual != -1:
        return str(actual)
    
    # Handle requested seed
    if requested is not None:
        if requested == -1:
            return "Random" if show_random else "-1"
        return str(requested)
    
    return "-"


def extract_seed_from_job(job: Any) -> tuple[int | None, int | None]:
    """
    Extract requested and actual seed from a job object.
    
    Args:
        job: Job object (NormalizedJobRecord, QueueJobV2, etc.)
        
    Returns:
        (requested_seed, actual_seed)
    """
    requested = None
    actual = None
    
    # Try direct attributes
    if hasattr(job, "seed"):
        requested = job.seed
    if hasattr(job, "actual_seed"):
        actual = job.actual_seed
    if hasattr(job, "resolved_seed"):
        actual = actual or job.resolved_seed
    
    # Try config snapshot
    if hasattr(job, "config_snapshot"):
        snapshot = job.config_snapshot or {}
        requested = requested or snapshot.get("seed")
        actual = actual or snapshot.get("actual_seed")
    
    # Try unified summary
    if hasattr(job, "to_unified_summary"):
        try:
            summary = job.to_unified_summary()
            requested = requested or getattr(summary, "seed", None)
            actual = actual or getattr(summary, "actual_seed", None)
        except Exception:
            pass
    
    return (requested, actual)
```

### Step 2: Update Preview Panel Seed Display

In `src/gui/preview_panel_v2.py`, update how seed is shown:

```python
from src.gui.utils.display_helpers import format_seed_display, extract_seed_from_job

def set_job_summaries(self, summaries: list[Any]) -> None:
    # ... existing code ...
    
    # Update seed display
    if summaries:
        first = summaries[0]
        requested, actual = extract_seed_from_job(first)
        seed_text = format_seed_display(requested, actual)
        self.seed_label.configure(text=f"Seed: {seed_text}")
    else:
        self.seed_label.configure(text="Seed: -")
```

Also update `_summary_from_normalized_job`:

```python
def _summary_from_normalized_job(self, job: NormalizedJobRecord) -> Any:
    # ... existing code ...
    
    # Extract seed info
    requested_seed = getattr(job, "seed", None)
    actual_seed = getattr(job, "actual_seed", None) or getattr(job, "resolved_seed", None)
    
    # Add to summary namespace
    summary.requested_seed = requested_seed
    summary.actual_seed = actual_seed
    summary.seed_display = format_seed_display(requested_seed, actual_seed)
    
    return summary
```

### Step 3: Update Running Job Panel Seed Display

In `src/gui/panels_v2/running_job_panel_v2.py`:

```python
from src.gui.utils.display_helpers import format_seed_display

def _update_display(self) -> None:
    # ... existing code ...
    
    # Update seed display if summary available
    if self._current_job_summary:
        requested = getattr(self._current_job_summary, "seed", None)
        actual = getattr(self._current_job_summary, "actual_seed", None)
        seed_text = format_seed_display(requested, actual)
        
        # Add seed info to stage chain or create new label
        if hasattr(self, "seed_label"):
            self.seed_label.configure(text=f"Seed: {seed_text}")
```

Add seed label in `__init__`:

```python
# After stage_chain_label
self.seed_label = ttk.Label(
    self,
    text="Seed: -",
    wraplength=400,
)
self.seed_label.pack(fill="x", pady=(0, 4))
```

### Step 4: Update Mini History Panel

In `src/gui/panels_v2/history_panel_v2.py`:

```python
from src.gui.utils.display_helpers import format_seed_display

def append_history_item(self, dto: JobHistoryItemDTO) -> None:
    # ... existing code ...
    
    # Extract seed for display
    requested_seed = getattr(dto, "seed", None)
    actual_seed = getattr(dto, "actual_seed", None)
    
    if actual_seed is not None or requested_seed is not None:
        seed_text = format_seed_display(requested_seed, actual_seed)
        if seed_text and seed_text != "-":
            parts.append(f"Seed:{seed_text}")
```

### Step 5: Update Executor to Capture Resolved Seed

Ensure executor stores resolved seed in results (builds on PR-PIPE-001):

```python
def _run_txt2img_impl(self, ...):
    # ... existing code ...
    
    response = self._generate_images("txt2img", payload)
    
    # Extract generation info including seed
    gen_info = self._extract_generation_info(response)
    actual_seed = gen_info.get("seed")
    actual_subseed = gen_info.get("subseed")
    all_seeds = gen_info.get("all_seeds", [])
    
    # Store for later access
    self._last_resolved_seed = actual_seed
    self._last_resolved_subseed = actual_subseed
    
    # ... continue with image saving, using actual_seed in metadata ...
```

### Step 6: Pass Resolved Seed Through Callbacks

In `src/controller/app_controller.py`, update job completion callback:

```python
def _on_job_finished(self, job: Job) -> None:
    def _apply() -> None:
        # ... existing code ...
        
        # Extract resolved seed from result if available
        result = getattr(job, "result", None)
        if isinstance(result, dict):
            actual_seed = result.get("actual_seed")
            if actual_seed is not None:
                # Update job's NJR with resolved seed
                njr = getattr(job, "_normalized_record", None)
                if njr and hasattr(njr, "actual_seed"):
                    njr.actual_seed = actual_seed
        
        self._refresh_job_history()

    self._run_in_gui_thread(_apply)
```

### Step 7: Add Seed to JobHistoryItemDTO

Ensure DTO carries seed info:

```python
# In src/pipeline/job_models_v2.py or appropriate location
@dataclass
class JobHistoryItemDTO:
    # ... existing fields ...
    seed: int | None = None           # Requested seed
    actual_seed: int | None = None    # Resolved seed
```

### Step 8: Write Tests

Create `tests/gui_v2/test_seed_display.py`.

## Acceptance Criteria

1. **Given** a job with `seed=-1`, **when** generation completes with actual seed 123456789, **then** all panels show "123456789" (not "Random" or "-1").

2. **Given** a job preview before generation, **when** `seed=-1`, **then** preview shows "Random".

3. **Given** a job preview with `seed=42`, **when** displayed, **then** preview shows "42".

4. **Given** a completed job in history, **when** viewing history panel, **then** the actual resolved seed is displayed.

5. **Given** the running job panel, **when** a job is executing, **then** the seed label shows either "Random" (before resolution) or actual seed (after txt2img).

6. **Given** an old history entry without seed data, **when** viewing history, **then** "-" is shown without errors.

7. **Given** `format_seed_display(None, None)`, **when** called, **then** returns "-".

## Test Plan

### Unit Tests

```bash
pytest tests/gui_v2/test_seed_display.py -v
pytest tests/pipeline/test_executor_seed_resolution.py -v
```

**Display Helper Tests:**

1. `test_format_seed_actual_overrides_requested` - Actual seed wins
2. `test_format_seed_random_when_minus_one` - Shows "Random"
3. `test_format_seed_requested_when_no_actual` - Falls back to requested
4. `test_format_seed_dash_when_null` - Returns "-"
5. `test_extract_seed_from_njr` - Extracts from NormalizedJobRecord
6. `test_extract_seed_from_queue_job` - Extracts from QueueJobV2

**Preview Panel Tests:**

1. `test_preview_panel_shows_random` - Random seed display
2. `test_preview_panel_shows_actual_seed` - Resolved seed display
3. `test_preview_panel_seed_updates_on_job_change` - Updates correctly

**Running Job Panel Tests:**

1. `test_running_job_panel_has_seed_label` - Label exists
2. `test_running_job_panel_seed_updates` - Updates with job

**Executor Tests:**

1. `test_executor_extracts_seed_from_response` - Seed extraction works
2. `test_executor_stores_resolved_seed` - Seed stored for access

### Manual Verification

1. Generate an image with seed=-1
2. Check manifest for `actual_seed` field
3. View job in history - verify seed shown
4. Queue multiple jobs - verify seeds differ
5. Generate with explicit seed (42) - verify matches

## Rollback

```bash
git revert <commit-hash>
```

Rollback is safe because:
- Display changes only affect UI rendering
- Helper functions are additive
- Existing seed=-1 behavior unchanged
- No data structure changes

## Dependencies

- PR-PIPE-001 (Manifest Enhancement) - Captures actual_seed in manifests
  - Note: This PR can work partially without PR-PIPE-001 but won't have seed in manifests

## Dependents

- Learning/Rating module - Uses seed to identify reproducible generations
