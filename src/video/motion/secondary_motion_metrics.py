from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from src.video.motion.secondary_motion_provenance import extract_secondary_motion_summary


def _mapping(value: Any) -> dict[str, Any]:
    return dict(value) if isinstance(value, Mapping) else {}


def _float(value: Any, default: float = 0.0) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _int(value: Any, default: int = 0) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def _resolve_quality_risk_score(
    *,
    status: str,
    intensity: float,
    cap_pixels: int,
    avg_abs_dx: float,
    avg_abs_dy: float,
    max_abs_dx: int,
    max_abs_dy: int,
) -> float:
    if status != "applied":
        return 0.0
    cap = max(1.0, float(cap_pixels or max(max_abs_dx, max_abs_dy, 1)))
    mean_shift_component = max(0.0, min(1.0, (avg_abs_dx + avg_abs_dy) / (2.0 * cap)))
    peak_shift_component = max(0.0, min(1.0, max(max_abs_dx, max_abs_dy) / cap))
    bounded_intensity = max(0.0, min(1.0, intensity))
    return round(
        max(
            0.0,
            min(1.0, (bounded_intensity * 0.5) + (mean_shift_component * 0.25) + (peak_shift_component * 0.25)),
        ),
        4,
    )


def build_secondary_motion_learning_context(payload: Mapping[str, Any] | None) -> dict[str, Any]:
    root = _mapping(payload)
    secondary_motion_payload = _mapping(root.get("secondary_motion"))
    direct_summary = _mapping(root.get("summary"))
    summary = extract_secondary_motion_summary(root)
    if not summary and secondary_motion_payload:
        summary = extract_secondary_motion_summary({"secondary_motion": secondary_motion_payload})
    if not summary and direct_summary:
        summary = direct_summary
    if not summary:
        return {}

    provenance_payload = secondary_motion_payload or root
    apply_result = _mapping(provenance_payload.get("apply_result"))
    policy_payload = _mapping(provenance_payload.get("policy"))
    metrics = _mapping(summary.get("metrics")) or _mapping(apply_result.get("metrics"))

    frames_in = _int(metrics.get("frames_in", apply_result.get("frames_in", 0)))
    frames_out = _int(metrics.get("frames_out", apply_result.get("frames_out", 0)))
    applied_frame_count = _int(metrics.get("applied_frame_count", 0))
    intensity = _float(metrics.get("intensity", policy_payload.get("intensity", 0.0)))
    damping = _float(metrics.get("damping", policy_payload.get("damping", 0.0)))
    frequency_hz = _float(metrics.get("frequency_hz", policy_payload.get("frequency_hz", 0.0)))
    cap_pixels = _int(metrics.get("cap_pixels", policy_payload.get("cap_pixels", 0)))
    avg_abs_dx = _float(metrics.get("avg_abs_dx", 0.0))
    avg_abs_dy = _float(metrics.get("avg_abs_dy", 0.0))
    max_abs_dx = _int(metrics.get("max_abs_dx", 0))
    max_abs_dy = _int(metrics.get("max_abs_dy", 0))
    raw_regions_applied = apply_result.get("regions_applied", metrics.get("regions_applied", 0))
    if isinstance(raw_regions_applied, (list, tuple, set)):
        regions_applied = len([item for item in raw_regions_applied if str(item or "").strip()])
    else:
        regions_applied = _int(raw_regions_applied, 0)

    status = str(summary.get("status") or "")
    return {
        "enabled": bool(summary.get("enabled")),
        "status": status,
        "backend_id": str(
            root.get("backend_id")
            or root.get("video_primary_backend_id")
            or root.get("video_backend_id")
            or ""
        ),
        "policy_id": str(summary.get("policy_id") or ""),
        "application_path": str(summary.get("application_path") or ""),
        "backend_mode": str(summary.get("backend_mode") or ""),
        "intent_mode": str((summary.get("intent") or {}).get("mode") or ""),
        "intent_label": str((summary.get("intent") or {}).get("intent") or ""),
        "skip_reason": str(summary.get("skip_reason") or ""),
        "regions_applied": regions_applied,
        "frames_in": frames_in,
        "frames_out": frames_out,
        "frame_count_delta": frames_out - frames_in,
        "applied_frame_count": applied_frame_count,
        "applied_frame_ratio": round(applied_frame_count / max(1, frames_in), 4) if frames_in > 0 else 0.0,
        "applied_motion_strength": round(intensity if status == "applied" else 0.0, 4),
        "quality_risk_score": _resolve_quality_risk_score(
            status=status,
            intensity=intensity,
            cap_pixels=cap_pixels,
            avg_abs_dx=avg_abs_dx,
            avg_abs_dy=avg_abs_dy,
            max_abs_dx=max_abs_dx,
            max_abs_dy=max_abs_dy,
        ),
        "intensity": round(intensity, 4),
        "damping": round(damping, 4),
        "frequency_hz": round(frequency_hz, 4),
        "cap_pixels": cap_pixels,
        "avg_abs_dx": round(avg_abs_dx, 4),
        "avg_abs_dy": round(avg_abs_dy, 4),
        "max_abs_dx": max_abs_dx,
        "max_abs_dy": max_abs_dy,
    }


__all__ = ["build_secondary_motion_learning_context"]