from __future__ import annotations

from collections.abc import Mapping
from copy import deepcopy
from dataclasses import dataclass, field
from typing import Any, Literal


ADAPTIVE_REFINEMENT_SCHEMA_V1 = "stablenew.adaptive-refinement.v1"
REFINEMENT_DECISION_SCHEMA_V1 = "stablenew.refinement-decision.v1"

AdaptiveRefinementMode = Literal["disabled", "observe", "adetailer", "full"]


def _mapping_dict(value: Any) -> dict[str, Any]:
    if isinstance(value, Mapping):
        return deepcopy(dict(value))
    return {}


@dataclass(frozen=True, slots=True)
class AdaptiveRefinementIntent:
    schema: str = ADAPTIVE_REFINEMENT_SCHEMA_V1
    enabled: bool = False
    mode: AdaptiveRefinementMode = "disabled"
    profile_id: str = "auto_v1"
    detector_preference: str = "null"
    record_decisions: bool = True
    algorithm_version: str = "v1"

    @classmethod
    def from_dict(cls, value: Mapping[str, Any] | None) -> AdaptiveRefinementIntent:
        data = _mapping_dict(value)
        mode = str(data.get("mode") or "disabled").lower()
        if mode not in {"disabled", "observe", "adetailer", "full"}:
            mode = "disabled"
        return cls(
            schema=str(data.get("schema") or ADAPTIVE_REFINEMENT_SCHEMA_V1),
            enabled=bool(data.get("enabled", False)),
            mode=mode,  # type: ignore[arg-type]
            profile_id=str(data.get("profile_id") or "auto_v1"),
            detector_preference=str(data.get("detector_preference") or "null"),
            record_decisions=bool(data.get("record_decisions", True)),
            algorithm_version=str(data.get("algorithm_version") or "v1"),
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema": self.schema,
            "enabled": self.enabled,
            "mode": self.mode,
            "profile_id": self.profile_id,
            "detector_preference": self.detector_preference,
            "record_decisions": self.record_decisions,
            "algorithm_version": self.algorithm_version,
        }


@dataclass(frozen=True, slots=True)
class RefinementDecisionBundle:
    schema: str = REFINEMENT_DECISION_SCHEMA_V1
    algorithm_version: str = "v1"
    mode: AdaptiveRefinementMode = "disabled"
    policy_id: str | None = None
    detector_id: str = "null"
    observation: dict[str, Any] = field(default_factory=dict)
    applied_overrides: dict[str, Any] = field(default_factory=dict)
    prompt_patch: dict[str, Any] = field(default_factory=dict)
    notes: tuple[str, ...] = ()

    @classmethod
    def from_dict(cls, value: Mapping[str, Any] | None) -> RefinementDecisionBundle:
        data = _mapping_dict(value)
        mode = str(data.get("mode") or "disabled").lower()
        if mode not in {"disabled", "observe", "adetailer", "full"}:
            mode = "disabled"
        notes = data.get("notes")
        return cls(
            schema=str(data.get("schema") or REFINEMENT_DECISION_SCHEMA_V1),
            algorithm_version=str(data.get("algorithm_version") or "v1"),
            mode=mode,  # type: ignore[arg-type]
            policy_id=str(data["policy_id"]) if data.get("policy_id") else None,
            detector_id=str(data.get("detector_id") or "null"),
            observation=_mapping_dict(data.get("observation")),
            applied_overrides=_mapping_dict(data.get("applied_overrides")),
            prompt_patch=_mapping_dict(data.get("prompt_patch")),
            notes=tuple(str(note) for note in notes) if isinstance(notes, (list, tuple)) else (),
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema": self.schema,
            "algorithm_version": self.algorithm_version,
            "mode": self.mode,
            "policy_id": self.policy_id,
            "detector_id": self.detector_id,
            "observation": _mapping_dict(self.observation),
            "applied_overrides": _mapping_dict(self.applied_overrides),
            "prompt_patch": _mapping_dict(self.prompt_patch),
            "notes": list(self.notes),
        }
