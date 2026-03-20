from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Protocol

from .refinement_policy_models import RefinementDecisionBundle


class RefinementPolicyRegistry(Protocol):
    def build_decision_bundle(self, *, mode: str, observation: dict[str, Any] | None = None) -> RefinementDecisionBundle:
        ...


@dataclass(slots=True)
class NoOpRefinementPolicyRegistry:
    algorithm_version: str = "v1"

    def build_decision_bundle(
        self,
        *,
        mode: str,
        observation: dict[str, Any] | None = None,
    ) -> RefinementDecisionBundle:
        normalized_mode = mode if mode in {"disabled", "observe", "adetailer", "full"} else "disabled"
        return RefinementDecisionBundle(
            algorithm_version=self.algorithm_version,
            mode=normalized_mode,
            policy_id="observe_only_v1" if normalized_mode == "observe" else None,
            detector_id="null",
            observation=dict(observation or {}),
        )
