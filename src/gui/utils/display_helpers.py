"""Display helper functions for GUI components.

Part of PR-PIPE-007.
"""

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
