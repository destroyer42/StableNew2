"""Duration statistics service for queue ETA estimation.

PR-PIPE-002: Aggregates job duration data from history to provide accurate
queue ETA estimates based on stage chain configurations.
"""

from __future__ import annotations

import statistics
from collections import defaultdict
from dataclasses import dataclass
from datetime import datetime
from typing import TYPE_CHECKING, Any, Sequence

if TYPE_CHECKING:
    from src.queue.job_history_store import JobHistoryEntry, JobHistoryStore
    from src.pipeline.job_models_v2 import NormalizedJobRecord
    from src.queue.job_model import QueueJobV2

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
    """Duration statistics for a specific stage chain configuration."""

    stage_chain: tuple[str, ...]  # e.g., ("txt2img", "adetailer", "upscale")
    sample_count: int  # Number of jobs in this bucket
    mean_duration_ms: float  # Average duration
    median_duration_ms: float  # Median duration (more robust)
    min_duration_ms: float  # Fastest run
    max_duration_ms: float  # Slowest run
    stddev_ms: float  # Standard deviation
    last_updated: datetime  # When stats were computed


class DurationStatsService:
    """Aggregates job duration statistics from history for ETA estimation."""

    def __init__(
        self,
        history_store: JobHistoryStore | None = None,
        *,
        max_samples_per_chain: int = 100,
        min_samples_for_stats: int = 3,
    ) -> None:
        """Initialize the duration stats service.

        Args:
            history_store: JobHistoryStore to read history from.
            max_samples_per_chain: Maximum number of recent samples to keep per chain.
            min_samples_for_stats: Minimum samples required for reliable statistics.
        """
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

        try:
            entries = self._history_store.list_jobs(limit=1000)
        except Exception:
            # History read failure - log and keep existing cache
            return

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
            recent = durations[-self._max_samples :]

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
        """Get estimated duration in seconds for a stage chain.

        Returns median duration if enough samples, None otherwise.

        Args:
            stage_chain: Sequence of stage names.

        Returns:
            Estimated duration in seconds, or None if insufficient data.
        """
        key = tuple(stage_chain)
        stats = self._stats_cache.get(key)

        if stats is not None:
            return stats.median_duration_ms / 1000.0

        return None

    def get_fallback_estimate(self, stage_chain: Sequence[str]) -> float:
        """Get conservative fallback estimate when no history available.

        Uses hardcoded per-stage estimates:
        - txt2img: 30s
        - img2img: 20s
        - adetailer: 45s
        - upscale: 60s
        - refiner: 40s

        Args:
            stage_chain: Sequence of stage names.

        Returns:
            Estimated duration in seconds based on stage sum.
        """
        total = 0.0
        for stage in stage_chain:
            total += STAGE_FALLBACK_SECONDS.get(stage.lower(), 30.0)
        return total

    def get_estimate_for_job(self, job: Any) -> float | None:
        """Get estimated duration for a specific job based on its stage chain.

        Extracts stage chain from job and calls get_estimate_for_chain.

        Args:
            job: QueueJobV2 or NormalizedJobRecord instance.

        Returns:
            Estimated duration in seconds, or None if no history available.
        """
        # Extract stage chain from job
        chain = None

        if hasattr(job, "stage_chain") and job.stage_chain:
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
        """Get total estimated duration for all jobs in queue.

        Args:
            jobs: Sequence of QueueJobV2 or NormalizedJobRecord instances.

        Returns:
            Tuple of (total_seconds, jobs_with_estimates) where jobs_with_estimates
            is the count of jobs that had historical data available.
        """
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
        """Get full statistics for a stage chain, or None if insufficient data.

        Args:
            stage_chain: Tuple of stage names.

        Returns:
            StageChainStats if available, None otherwise.
        """
        return self._stats_cache.get(stage_chain)
