"""Calculate job duration statistics for time estimates."""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from src.queue.job_history_store import JobHistoryEntry


class DurationStats:
    """Calculate average job duration from history for time estimates."""

    def __init__(self) -> None:
        self._entries: list[JobHistoryEntry] = []

    def load_history(self, entries: list[JobHistoryEntry]) -> None:
        """Load history entries for duration analysis."""
        self._entries = [e for e in entries if e.duration_ms is not None and e.duration_ms > 0]

    def get_average_duration_ms(self, stage_filter: str | None = None) -> int | None:
        """Get average duration in milliseconds for all jobs or filtered by stage.

        Args:
            stage_filter: Optional stage name to filter by (e.g., "txt2img", "adetailer")

        Returns:
            Average duration in milliseconds, or None if no data available.
        """
        if not self._entries:
            return None

        # For now, calculate simple average across all jobs
        # TODO: In future, filter by stage combination from snapshot
        durations = [e.duration_ms for e in self._entries if e.duration_ms]
        if not durations:
            return None

        return sum(durations) // len(durations)

    def format_duration_ms(self, duration_ms: int | None) -> str:
        """Format duration in milliseconds to human-readable string.

        Args:
            duration_ms: Duration in milliseconds

        Returns:
            Formatted string like "1m 23s" or "45s"
        """
        if duration_ms is None or duration_ms <= 0:
            return "-"

        total_seconds = duration_ms / 1000
        if total_seconds < 60:
            return f"{total_seconds:.0f}s"

        minutes = int(total_seconds // 60)
        seconds = int(total_seconds % 60)
        if minutes < 60:
            return f"{minutes}m {seconds}s"

        hours = minutes // 60
        minutes = minutes % 60
        return f"{hours}h {minutes}m"
