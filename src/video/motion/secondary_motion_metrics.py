from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from src.video.motion.secondary_motion_provenance import extract_secondary_motion_summary


def build_secondary_motion_learning_context(payload: Mapping[str, Any] | None) -> dict[str, Any]:
    summary = extract_secondary_motion_summary(payload)
    if not summary and isinstance(payload, Mapping):
        direct_summary = payload.get("summary")
        if isinstance(direct_summary, Mapping):
            summary = dict(direct_summary)
    if not summary:
        return {}
    metrics = dict(summary.get("metrics") or {}) if isinstance(summary.get("metrics"), Mapping) else {}
    return {
        "enabled": bool(summary.get("enabled")),
        "status": str(summary.get("status") or ""),
        "policy_id": str(summary.get("policy_id") or ""),
        "application_path": str(summary.get("application_path") or ""),
        "backend_mode": str(summary.get("backend_mode") or ""),
        "intent_mode": str((summary.get("intent") or {}).get("mode") or ""),
        "intent_label": str((summary.get("intent") or {}).get("intent") or ""),
        "skip_reason": str(summary.get("skip_reason") or ""),
        "regions_applied": int(metrics.get("regions_applied", 0) or 0),
        "frames_in": int(metrics.get("frames_in", 0) or 0),
        "frames_out": int(metrics.get("frames_out", 0) or 0),
    }


__all__ = ["build_secondary_motion_learning_context"]