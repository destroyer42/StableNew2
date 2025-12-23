# PR-PIPE-002 – Queue ETA Based on Historical Duration Stats

## Context

The queue panel currently displays a hardcoded placeholder ETA:

```python
# src/gui/panels_v2/queue_panel_v2.py, line ~355
# Simple estimate: 60 seconds per job as placeholder
# TODO: Replace with actual duration stats from history
estimated_seconds = count * 60
```

This provides no useful information to users. Jobs can take anywhere from 30 seconds (txt2img only) to 10+ minutes (full pipeline with upscale), making a fixed 60-second estimate misleading.

The `job_history.jsonl` file already contains `duration_ms` for completed jobs, along with NJR snapshots that include stage chain information. By aggregating this data, we can provide accurate per-configuration ETAs.

## Non-Goals

- Machine learning or sophisticated prediction models
- Per-prompt duration estimation (only per-stage-chain)
- Modifying how durations are recorded (that's PR-PIPE-001)
- Real-time progress updates during generation (that's PR-PIPE-004)
- Persistent storage of statistics (keep in-memory, rebuild on startup)

## Invariants

- Statistics service is optional; queue panel must function without it
- Cold start (no history): fall back to conservative estimates
- Duration stats refresh on history updates (not on every call)
- Stats computation must not block UI thread
- Zero impact on job execution performance
- Statistics are approximations, UI should indicate uncertainty

## Allowed Files

- `src/services/duration_stats_service.py` (new)
- `src/gui/panels_v2/queue_panel_v2.py` - Consume stats for ETA
- `src/controller/app_controller.py` - Initialize and wire service
- `src/gui/app_state_v2.py` - Optional: expose stats via app_state
- `tests/services/test_duration_stats_service.py` (new)
- `tests/gui_v2/test_queue_panel_eta.py` (new)

## Do Not Touch

- `src/queue/job_history_store.py` - Read-only access
- `src/pipeline/executor.py` - Duration recording is separate (PR-PIPE-001)
- `src/history/*` - History format unchanged
- `src/pipeline/job_models_v2.py` - NJR unchanged

## Interfaces

### DurationStatsService

```python
@dataclass
class StageChainStats:
    """Duration statistics for a specific stage chain configuration."""
    
    stage_chain: tuple[str, ...]  # e.g., ("txt2img", "adetailer", "upscale")
    sample_count: int              # Number of jobs in this bucket
    mean_duration_ms: float        # Average duration
    median_duration_ms: float      # Median duration (more robust)
    min_duration_ms: float         # Fastest run
    max_duration_ms: float         # Slowest run
    stddev_ms: float               # Standard deviation
    last_updated: datetime         # When stats were computed


class DurationStatsService:
    """Aggregates job duration statistics from history for ETA estimation."""
    
    def __init__(
        self,
        history_store: JobHistoryStore,
        *,
        max_samples_per_chain: int = 100,  # Rolling window
        min_samples_for_stats: int = 3,     # Minimum for reliable stats
    ) -> None: ...
    
    def refresh(self) -> None:
        """Recompute stats from history. Called on history updates."""
    
    def get_estimate_for_chain(
        self, 
        stage_chain: Sequence[str],
    ) -> float | None:
        """
        Get estimated duration in seconds for a stage chain.
        
        Returns median duration if enough samples, None otherwise.
        """
    
    def get_estimate_for_job(
        self,
        job: QueueJobV2 | NormalizedJobRecord,
    ) -> float | None:
        """
        Get estimated duration for a specific job based on its stage chain.
        
        Extracts stage chain from job and calls get_estimate_for_chain.
        """
    
    def get_queue_total_estimate(
        self,
        jobs: Sequence[QueueJobV2 | NormalizedJobRecord],
    ) -> tuple[float, int]:
        """
        Get total estimated duration for all jobs in queue.
        
        Returns:
            (total_seconds, jobs_with_estimates)
        """
    
    def get_stats(self, stage_chain: tuple[str, ...]) -> StageChainStats | None:
        """Get full statistics for a stage chain, or None if insufficient data."""
    
    def get_fallback_estimate(self, stage_chain: Sequence[str]) -> float:
        """
        Get conservative fallback estimate when no history available.
        
        Uses hardcoded per-stage estimates:
        - txt2img: 30s
        - img2img: 20s
        - adetailer: 45s
        - upscale: 60s
        """
```

### Queue Panel Integration

```python
# In QueuePanelV2
def _compute_queue_eta(self) -> tuple[float, str]:
    """
    Compute queue ETA using duration stats service.
    
    Returns:
        (total_seconds, confidence_indicator)
        confidence_indicator: "~" for estimate, "?" for fallback
    """
```

### Error Behavior

- History read failure: log error, use fallback estimates
- No history entries: use fallback estimates
- Partially available stats: mix of real + fallback
- Service unavailable: queue panel uses hardcoded fallback (current behavior)

## Implementation Steps (Order Matters)

### Step 1: Create DurationStatsService

Create `src/services/duration_stats_service.py`:

```python
"""Duration statistics service for queue ETA estimation."""

from __future__ import annotations

import statistics
from collections import defaultdict
from dataclasses import dataclass
from datetime import datetime
from typing import TYPE_CHECKING, Any, Sequence

if TYPE_CHECKING:
    from src.queue.job_history_store import JobHistoryEntry, JobHistoryStore
    from src.pipeline.job_models_v2 import NormalizedJobRecord, QueueJobV2

# Fallback estimates per stage in seconds
STAGE_FALLBACK_SECONDS: dict[str, float] = {
    "txt2img": 30.0,
    "img2img": 20.0,
    "adetailer": 45.0,
    "upscale": 60.0,
    "refiner": 40.0,
}


@dataclass
class StageChainStats:
    stage_chain: tuple[str, ...]
    sample_count: int
    mean_duration_ms: float
    median_duration_ms: float
    min_duration_ms: float
    max_duration_ms: float
    stddev_ms: float
    last_updated: datetime


class DurationStatsService:
    def __init__(
        self,
        history_store: JobHistoryStore | None = None,
        *,
        max_samples_per_chain: int = 100,
        min_samples_for_stats: int = 3,
    ) -> None:
        self._history_store = history_store
        self._max_samples = max_samples_per_chain
        self._min_samples = min_samples_for_stats
        self._stats_cache: dict[tuple[str, ...], StageChainStats] = {}
        self._last_refresh: datetime | None = None
    
    def refresh(self) -> None:
        """Recompute statistics from history store."""
        if self._history_store is None:
            return
        
        # Group durations by stage chain
        chain_durations: dict[tuple[str, ...], list[int]] = defaultdict(list)
        
        entries = self._history_store.list_jobs(limit=1000)
        for entry in entries:
            duration_ms = entry.duration_ms
            if duration_ms is None or duration_ms <= 0:
                continue
            
            # Extract stage chain from NJR snapshot
            chain = self._extract_stage_chain(entry)
            if chain:
                chain_durations[chain].append(duration_ms)
        
        # Compute stats for each chain
        self._stats_cache.clear()
        now = datetime.utcnow()
        
        for chain, durations in chain_durations.items():
            # Keep only most recent samples
            recent = durations[-self._max_samples:]
            
            if len(recent) < self._min_samples:
                continue
            
            self._stats_cache[chain] = StageChainStats(
                stage_chain=chain,
                sample_count=len(recent),
                mean_duration_ms=statistics.mean(recent),
                median_duration_ms=statistics.median(recent),
                min_duration_ms=min(recent),
                max_duration_ms=max(recent),
                stddev_ms=statistics.stdev(recent) if len(recent) > 1 else 0.0,
                last_updated=now,
            )
        
        self._last_refresh = now
    
    def _extract_stage_chain(self, entry: JobHistoryEntry) -> tuple[str, ...] | None:
        """Extract stage chain from history entry's NJR snapshot."""
        snapshot = entry.snapshot
        if not snapshot:
            return None
        
        njr = snapshot.get("normalized_job", {})
        stages = njr.get("stage_chain") or njr.get("stages") or []
        
        if isinstance(stages, list) and stages:
            return tuple(str(s) for s in stages)
        return None
    
    def get_estimate_for_chain(self, stage_chain: Sequence[str]) -> float | None:
        """Get estimated duration in seconds for a stage chain."""
        key = tuple(stage_chain)
        stats = self._stats_cache.get(key)
        
        if stats is not None:
            return stats.median_duration_ms / 1000.0
        
        return None
    
    def get_fallback_estimate(self, stage_chain: Sequence[str]) -> float:
        """Get conservative fallback estimate when no history available."""
        total = 0.0
        for stage in stage_chain:
            total += STAGE_FALLBACK_SECONDS.get(stage.lower(), 30.0)
        return total
    
    def get_estimate_for_job(self, job: Any) -> float | None:
        """Get estimated duration for a specific job."""
        # Extract stage chain from job
        chain = None
        
        if hasattr(job, "stage_chain"):
            chain = job.stage_chain
        elif hasattr(job, "config_snapshot"):
            snapshot = job.config_snapshot or {}
            chain = snapshot.get("stages") or snapshot.get("stage_chain")
        elif hasattr(job, "to_unified_summary"):
            summary = job.to_unified_summary()
            chain = getattr(summary, "stage_chain", None)
        
        if chain:
            return self.get_estimate_for_chain(chain)
        return None
    
    def get_queue_total_estimate(
        self, 
        jobs: Sequence[Any],
    ) -> tuple[float, int]:
        """Get total estimated duration for all jobs in queue."""
        total_seconds = 0.0
        jobs_with_estimates = 0
        
        for job in jobs:
            estimate = self.get_estimate_for_job(job)
            if estimate is not None:
                total_seconds += estimate
                jobs_with_estimates += 1
            else:
                # Use fallback
                chain = self._get_job_chain(job)
                total_seconds += self.get_fallback_estimate(chain)
        
        return (total_seconds, jobs_with_estimates)
    
    def _get_job_chain(self, job: Any) -> list[str]:
        """Extract stage chain from job, or return default."""
        if hasattr(job, "stage_chain"):
            return list(job.stage_chain or ["txt2img"])
        if hasattr(job, "config_snapshot"):
            snapshot = job.config_snapshot or {}
            return list(snapshot.get("stages") or ["txt2img"])
        return ["txt2img"]
    
    def get_stats(self, stage_chain: tuple[str, ...]) -> StageChainStats | None:
        """Get full statistics for a stage chain."""
        return self._stats_cache.get(stage_chain)
```

### Step 2: Wire Service into AppController

In `src/controller/app_controller.py`, add initialization:

```python
# In __init__ or _initialize_services
from src.services.duration_stats_service import DurationStatsService

self._duration_stats_service = DurationStatsService(
    history_store=self._job_history_store,
)

# Refresh stats on startup
self._duration_stats_service.refresh()
```

Add refresh hook when history updates:

```python
def _refresh_job_history(self) -> None:
    # ... existing code ...
    
    # Refresh duration stats
    if hasattr(self, "_duration_stats_service"):
        try:
            self._duration_stats_service.refresh()
        except Exception as exc:
            self._append_log(f"[duration_stats] refresh failed: {exc}")
```

Expose service to panels:

```python
@property
def duration_stats_service(self) -> DurationStatsService | None:
    return getattr(self, "_duration_stats_service", None)
```

### Step 3: Update QueuePanelV2 to Use Stats Service

In `src/gui/panels_v2/queue_panel_v2.py`, replace the hardcoded estimate:

```python
def _compute_queue_eta(self) -> tuple[float, str]:
    """Compute queue ETA using duration stats service."""
    count = len(self._jobs)
    if count == 0:
        return (0.0, "")
    
    # Try to get stats service from controller
    stats_service = None
    if self.controller:
        stats_service = getattr(self.controller, "duration_stats_service", None)
    
    if stats_service is None:
        # Fallback to old hardcoded estimate
        return (count * 60.0, "?")
    
    total_seconds, jobs_with_estimates = stats_service.get_queue_total_estimate(
        self._jobs
    )
    
    # Determine confidence indicator
    if jobs_with_estimates == count:
        confidence = "~"  # All based on history
    elif jobs_with_estimates > 0:
        confidence = "~?"  # Mixed
    else:
        confidence = "?"  # All fallback
    
    return (total_seconds, confidence)


def update_jobs(self, jobs: list[QueueJobV2]) -> None:
    # ... existing code ...
    
    # Update ETA label with computed estimate
    if count > 0:
        total_seconds, confidence = self._compute_queue_eta()
        eta_text = self._format_queue_eta(total_seconds)
        # Add confidence indicator
        if confidence:
            eta_text = f"{eta_text} {confidence}"
        self.queue_eta_label.configure(text=eta_text)
    else:
        self.queue_eta_label.configure(text="")
```

### Step 4: Add Per-Job ETA Display (Optional Enhancement)

Update job listbox display to include individual ETAs:

```python
def _format_job_display(self, job: QueueJobV2, index: int) -> str:
    """Format job for listbox display with ETA."""
    order_num = index + 1
    base_summary = job.get_display_summary()
    
    # Get individual job ETA
    eta_str = ""
    if self.controller:
        stats_service = getattr(self.controller, "duration_stats_service", None)
        if stats_service:
            estimate = stats_service.get_estimate_for_job(job)
            if estimate:
                if estimate < 60:
                    eta_str = f" ({int(estimate)}s)"
                else:
                    mins = int(estimate // 60)
                    eta_str = f" (~{mins}m)"
    
    # Mark running job
    if self._running_job_id and job.job_id == self._running_job_id:
        return f"#{order_num} ▶ {base_summary}{eta_str}"
    return f"#{order_num}  {base_summary}{eta_str}"
```

### Step 5: Write Unit Tests

Create `tests/services/test_duration_stats_service.py`.

### Step 6: Write Integration Tests

Create `tests/gui_v2/test_queue_panel_eta.py`.

## Acceptance Criteria

1. **Given** a history with 10 completed `txt2img+adetailer+upscale` jobs averaging 120 seconds, **when** viewing a queue with 5 jobs of that type, **then** the ETA shows approximately "10m 0s ~".

2. **Given** no job history, **when** viewing a queue with 3 `txt2img` jobs, **then** the ETA shows "1m 30s ?" (fallback: 30s × 3).

3. **Given** a mixed queue with some jobs having history and some without, **when** viewing the queue, **then** the ETA shows a blended estimate with "~?" indicator.

4. **Given** the duration stats service is unavailable, **when** viewing the queue, **then** the panel falls back to current behavior without crashing.

5. **Given** a job completes and is added to history, **when** the history refreshes, **then** the duration stats are recomputed and queue ETA updates.

6. **Given** a stage chain with fewer than 3 samples, **when** estimating that chain, **then** fallback estimates are used.

## Test Plan

### Unit Tests

```bash
pytest tests/services/test_duration_stats_service.py -v
```

**Test Cases:**

1. `test_refresh_with_empty_history` - No history returns no stats
2. `test_refresh_with_valid_history` - Computes correct stats
3. `test_get_estimate_for_known_chain` - Returns median duration
4. `test_get_estimate_for_unknown_chain` - Returns None
5. `test_get_fallback_estimate` - Sums per-stage fallbacks
6. `test_queue_total_estimate` - Correct sum across jobs
7. `test_min_samples_threshold` - Respects minimum sample count
8. `test_max_samples_window` - Uses only recent samples

### Integration Tests

```bash
pytest tests/gui_v2/test_queue_panel_eta.py -v
```

**Test Cases:**

1. `test_queue_panel_eta_with_stats_service` - Uses real estimates
2. `test_queue_panel_eta_without_stats_service` - Falls back gracefully
3. `test_queue_panel_eta_updates_on_refresh` - Responds to history changes
4. `test_queue_panel_displays_confidence_indicator` - Shows ~, ?, or ~?

## Rollback

```bash
git revert <commit-hash>
```

Rollback is safe because:
- Queue panel has existing fallback (60s × count)
- Stats service is additive, not replacing existing functionality
- No changes to history storage

## Dependencies

- None (reads existing history format)
- PR-PIPE-001 improves duration data quality but is not required

## Dependents

- PR-PIPE-004 (Progress Polling) may use stats for per-stage ETA
