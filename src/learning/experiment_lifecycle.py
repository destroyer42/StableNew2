"""Pure lifecycle rules for Working Draft and Experiment Library placement."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any


def has_successful_admission(payload: Mapping[str, Any] | None) -> bool:
    """Return whether any immutable job was admitted to the queue."""
    return any(
        str(item.get("job_id") or "").strip()
        for item in list((payload or {}).get("plan") or [])
        if isinstance(item, Mapping)
    )


def classify_experiment_lifecycle(
    payload: Mapping[str, Any] | None, *, saved_rating_count: int = 0
) -> str:
    """Return the operator-facing durable lifecycle for a saved experiment."""
    if not has_successful_admission(payload):
        return "Draft/Legacy Draft"
    plan = [item for item in list((payload or {}).get("plan") or []) if isinstance(item, Mapping)]
    statuses = {str(item.get("status") or "").strip().lower() for item in plan}
    if "running" in statuses:
        return "Running"
    if statuses & {"queued", "pending"}:
        return "Queued"
    if statuses and statuses <= {"failed", "cancelled", "canceled"}:
        return "Failed"
    completed = sum(int(item.get("completed_images", 0) or 0) for item in plan)
    if completed and saved_rating_count >= completed:
        return "Complete"
    return "Review Needed"
