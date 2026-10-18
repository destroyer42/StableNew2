"""Operator-facing reason a non-empty queue is not dispatching.

A GPU device-loss quarantine and a WebUI outage hold both leave jobs QUEUED and unchanged, so pausing, toggling
auto-run and Send Job appear to do nothing. This turns the queue's own ``dispatch_summary()`` projection into one
sentence for the queue panel. It reads only; it never releases or changes a hold.
"""

from __future__ import annotations

import logging
from collections.abc import Mapping
from typing import Any

logger = logging.getLogger(__name__)

GPU_HINT = "open Readiness and use 'Confirm GPU recovered...'"
WEBUI_HINT = "waiting for the WebUI to prove ready again"


def format_dispatch_hold(summary: Mapping[str, Any] | None) -> str:
    """Return the hold sentence for a ``JobQueue.dispatch_summary()`` mapping, or ``""`` when nothing is held."""

    if not summary:
        return ""
    held_gpu = int(summary.get("held_gpu_loss") or 0)
    held_webui = int(summary.get("held_webui") or 0)
    if held_gpu <= 0 and held_webui <= 0:
        return ""
    eligible = int(summary.get("eligible") or 0)
    parts: list[str] = []
    if held_gpu > 0:
        parts.append(f"{held_gpu} held by the GPU device-loss quarantine - {GPU_HINT}")
    if held_webui > 0:
        parts.append(f"{held_webui} held by a WebUI outage - {WEBUI_HINT}")
    lead = "Dispatch is held" if eligible <= 0 else f"{eligible} can still run; some jobs are held"
    return f"{lead}: " + "; ".join(parts)


def describe_dispatch_hold(queue: Any) -> str:
    """Read the queue's dispatch summary and format it; any failure yields ``""`` (this is display only)."""

    summary_of = getattr(queue, "dispatch_summary", None)
    if not callable(summary_of):
        return ""
    try:
        return format_dispatch_hold(summary_of())
    except Exception:
        logger.exception("Dispatch hold summary unavailable")
        return ""


__all__ = ["describe_dispatch_hold", "format_dispatch_hold"]
