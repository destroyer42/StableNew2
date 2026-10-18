"""Queue status display contract independent of toolkit."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class QueueStatusState:
    text: str
    severity: str


def resolve_queue_status_display(
    *,
    is_paused: bool,
    has_running_job: bool,
    queue_count: int,
    dispatch_hold: str = "",
) -> QueueStatusState:
    count = max(0, int(queue_count))
    if has_running_job:
        return QueueStatusState(text="Queue: Running job...", severity="running")
    if dispatch_hold and count > 0:
        # A hold (GPU quarantine / WebUI outage) is why nothing starts, so say it before "paused" or "pending".
        paused = " (paused)" if is_paused else ""
        return QueueStatusState(
            text=f"Queue: {count} pending{paused}. {dispatch_hold}", severity="held"
        )
    if is_paused:
        return QueueStatusState(text=f"Queue: Paused ({count} pending)", severity="paused")
    if count > 0:
        suffix = "s" if count != 1 else ""
        return QueueStatusState(text=f"Queue: {count} job{suffix} pending", severity="pending")
    return QueueStatusState(text="Queue: Idle", severity="idle")


def resolve_queue_status_from_label(status: str | None) -> QueueStatusState:
    normalized = str(status or "idle").strip().lower() or "idle"
    if normalized == "running":
        return QueueStatusState(text="Queue: Running", severity="running")
    if normalized == "paused":
        return QueueStatusState(text="Queue: Paused", severity="paused")
    if normalized == "idle":
        return QueueStatusState(text="Queue: Idle", severity="idle")
    return QueueStatusState(text=f"Queue: {normalized.title()}", severity="pending")
