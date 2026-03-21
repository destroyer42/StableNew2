from __future__ import annotations

from collections.abc import Mapping
from copy import deepcopy
from dataclasses import dataclass
from typing import Any, Literal


SECONDARY_MOTION_SCHEMA_V1 = "stablenew.secondary-motion.v1"
SECONDARY_MOTION_POLICY_SCHEMA_V1 = "stablenew.secondary-motion-policy.v1"

SecondaryMotionMode = Literal["disabled", "observe", "apply"]


def _mapping_dict(value: Any) -> dict[str, Any]:
    if isinstance(value, Mapping):
        return deepcopy(dict(value))
    return {}


def _normalize_mode(value: Any) -> SecondaryMotionMode:
    mode = str(value or "disabled").lower()
    if mode not in {"disabled", "observe", "apply"}:
        mode = "disabled"
    return mode  # type: ignore[return-value]


def _normalize_regions(value: Any) -> tuple[str, ...]:
    if isinstance(value, str):
        if not value.strip():
            return ()
        return (value.strip(),)
    if isinstance(value, (list, tuple)):
        return tuple(str(item).strip() for item in value if str(item or "").strip())
    return ()


@dataclass(frozen=True, slots=True)
class SecondaryMotionIntent:
    schema: str = SECONDARY_MOTION_SCHEMA_V1
    enabled: bool = False
    mode: SecondaryMotionMode = "disabled"
    intent: str = "steady"
    regions: tuple[str, ...] = ()
    allow_prompt_bias: bool = False
    allow_native_backend: bool = False
    record_decisions: bool = True
    seed: int | None = None
    algorithm_version: str = "v1"

    @classmethod
    def from_dict(cls, value: Mapping[str, Any] | None) -> SecondaryMotionIntent:
        data = _mapping_dict(value)
        raw_seed = data.get("seed")
        seed = int(raw_seed) if raw_seed not in (None, "") else None
        return cls(
            schema=str(data.get("schema") or SECONDARY_MOTION_SCHEMA_V1),
            enabled=bool(data.get("enabled", False)),
            mode=_normalize_mode(data.get("mode")),
            intent=str(data.get("intent") or "steady"),
            regions=_normalize_regions(data.get("regions")),
            allow_prompt_bias=bool(data.get("allow_prompt_bias", False)),
            allow_native_backend=bool(data.get("allow_native_backend", False)),
            record_decisions=bool(data.get("record_decisions", True)),
            seed=seed,
            algorithm_version=str(data.get("algorithm_version") or "v1"),
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema": self.schema,
            "enabled": self.enabled,
            "mode": self.mode,
            "intent": self.intent,
            "regions": list(self.regions),
            "allow_prompt_bias": self.allow_prompt_bias,
            "allow_native_backend": self.allow_native_backend,
            "record_decisions": self.record_decisions,
            "seed": self.seed,
            "algorithm_version": self.algorithm_version,
        }


@dataclass(frozen=True, slots=True)
class SecondaryMotionPolicy:
    schema: str = SECONDARY_MOTION_POLICY_SCHEMA_V1
    policy_id: str = "secondary_motion_disabled_v1"
    enabled: bool = False
    backend_mode: str = "disabled"
    intensity: float = 0.0
    damping: float = 1.0
    frequency_hz: float = 0.0
    cap_pixels: int = 0
    subject_scale: str = "unknown"
    pose_class: str = "steady"
    reasons: tuple[str, ...] = ()
    algorithm_version: str = "v1"

    @classmethod
    def from_dict(cls, value: Mapping[str, Any] | None) -> SecondaryMotionPolicy:
        data = _mapping_dict(value)
        reasons = data.get("reasons")
        return cls(
            schema=str(data.get("schema") or SECONDARY_MOTION_POLICY_SCHEMA_V1),
            policy_id=str(data.get("policy_id") or "secondary_motion_disabled_v1"),
            enabled=bool(data.get("enabled", False)),
            backend_mode=str(data.get("backend_mode") or "disabled"),
            intensity=float(data.get("intensity", 0.0) or 0.0),
            damping=float(data.get("damping", 1.0) or 1.0),
            frequency_hz=float(data.get("frequency_hz", 0.0) or 0.0),
            cap_pixels=int(data.get("cap_pixels", 0) or 0),
            subject_scale=str(data.get("subject_scale") or "unknown"),
            pose_class=str(data.get("pose_class") or "steady"),
            reasons=tuple(str(item) for item in reasons) if isinstance(reasons, (list, tuple)) else (),
            algorithm_version=str(data.get("algorithm_version") or "v1"),
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema": self.schema,
            "policy_id": self.policy_id,
            "enabled": self.enabled,
            "backend_mode": self.backend_mode,
            "intensity": self.intensity,
            "damping": self.damping,
            "frequency_hz": self.frequency_hz,
            "cap_pixels": self.cap_pixels,
            "subject_scale": self.subject_scale,
            "pose_class": self.pose_class,
            "reasons": list(self.reasons),
            "algorithm_version": self.algorithm_version,
        }
