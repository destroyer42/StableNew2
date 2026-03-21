from __future__ import annotations

from collections.abc import Mapping
from typing import Any


SECONDARY_MOTION_PROVENANCE_SCHEMA_V1 = "stablenew.secondary-motion-provenance.v1"
SECONDARY_MOTION_SUMMARY_SCHEMA_V1 = "stablenew.secondary-motion-summary.v1"


def _mapping(value: Any) -> dict[str, Any]:
    return dict(value) if isinstance(value, Mapping) else {}


def _scalar_metrics(metrics: Mapping[str, Any] | None) -> dict[str, float | int]:
    scalars: dict[str, float | int] = {}
    for key, value in _mapping(metrics).items():
        if isinstance(value, bool):
            continue
        if isinstance(value, (int, float)):
            scalars[str(key)] = value
    return scalars


def build_secondary_motion_summary(
    *,
    intent: Mapping[str, Any] | None = None,
    policy: Mapping[str, Any] | None = None,
    apply_result: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    intent_payload = _mapping(intent)
    policy_payload = _mapping(policy)
    apply_payload = _mapping(apply_result)
    status = str(apply_payload.get("status") or "")
    if not status:
        status = "observe" if str(policy_payload.get("backend_mode") or "").startswith("observe") else "disabled"
    application_path = str(apply_payload.get("application_path") or "")
    if not application_path and status == "observe":
        application_path = "policy_observation_only"
    elif not application_path:
        application_path = "shared_postprocess_engine"
    return {
        "schema": SECONDARY_MOTION_SUMMARY_SCHEMA_V1,
        "enabled": bool(policy_payload.get("enabled", intent_payload.get("enabled", False))),
        "status": status,
        "policy_id": str(policy_payload.get("policy_id") or ""),
        "application_path": application_path,
        "intent": {
            "mode": str(intent_payload.get("mode") or ""),
            "intent": str(intent_payload.get("intent") or ""),
        },
        "backend_mode": str(policy_payload.get("backend_mode") or ""),
        "skip_reason": str(apply_payload.get("skip_reason") or ""),
        "metrics": _scalar_metrics(apply_payload.get("metrics") or policy_payload),
    }


def build_secondary_motion_manifest_block(
    *,
    intent: Mapping[str, Any] | None = None,
    policy: Mapping[str, Any] | None = None,
    apply_result: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    intent_payload = _mapping(intent)
    policy_payload = _mapping(policy)
    apply_payload = _mapping(apply_result)
    return {
        "schema": SECONDARY_MOTION_PROVENANCE_SCHEMA_V1,
        "intent": intent_payload,
        "policy": policy_payload,
        "apply_result": apply_payload,
        "summary": build_secondary_motion_summary(
            intent=intent_payload,
            policy=policy_payload,
            apply_result=apply_payload,
        ),
    }


def extract_secondary_motion_summary(payload: Mapping[str, Any] | None) -> dict[str, Any]:
    data = _mapping(payload)
    explicit = _mapping(data.get("secondary_motion_summary"))
    if explicit:
        return explicit

    secondary_motion = _mapping(data.get("secondary_motion"))
    if not secondary_motion:
        return {}

    summary = _mapping(secondary_motion.get("summary"))
    if summary:
        return summary

    return build_secondary_motion_summary(
        intent=_mapping(secondary_motion.get("intent")),
        policy=_mapping(
            secondary_motion.get("policy")
            or secondary_motion.get("primary_policy")
        ),
        apply_result=_mapping(secondary_motion.get("apply_result")),
    )


__all__ = [
    "SECONDARY_MOTION_PROVENANCE_SCHEMA_V1",
    "SECONDARY_MOTION_SUMMARY_SCHEMA_V1",
    "build_secondary_motion_manifest_block",
    "build_secondary_motion_summary",
    "extract_secondary_motion_summary",
]
