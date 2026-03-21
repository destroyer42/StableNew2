from __future__ import annotations

from dataclasses import dataclass
from typing import cast
from typing import Any, Protocol

from .refinement_policy_models import RefinementDecisionBundle


class RefinementPolicyRegistry(Protocol):
    def build_decision_bundle(self, *, mode: str, observation: dict[str, Any] | None = None) -> RefinementDecisionBundle:
        ...


@dataclass(slots=True)
class NoOpRefinementPolicyRegistry:
    algorithm_version: str = "v1"

    @staticmethod
    def _as_bool(value: Any) -> bool:
        return bool(value)

    @staticmethod
    def _as_float(value: Any) -> float | None:
        try:
            return float(value)
        except (TypeError, ValueError):
            return None

    def _build_adetailer_policy(
        self,
        *,
        observation: dict[str, Any],
    ) -> tuple[str | None, dict[str, Any], tuple[str, ...]]:
        prompt_intent = dict(observation.get("prompt_intent") or {})
        assessment = dict(observation.get("subject_assessment") or {})
        scale_band = str(assessment.get("scale_band") or "unknown")
        wants_profile = self._as_bool(prompt_intent.get("wants_profile"))
        wants_face_detail = self._as_bool(prompt_intent.get("wants_face_detail"))
        face_width_ratio = self._as_float(assessment.get("face_width_ratio"))
        notes: list[str] = []
        overrides: dict[str, Any] = {}
        policy_id: str | None = None

        if scale_band == "micro":
            policy_id = "adetailer_micro_face_v1"
            overrides = {
                "ad_confidence": 0.22,
                "ad_mask_min_ratio": 0.003,
                "ad_inpaint_only_masked_padding": 48,
            }
            notes.append("small_subject_recovery")
        elif scale_band == "small":
            policy_id = "adetailer_small_face_v1"
            overrides = {
                "ad_confidence": 0.28,
                "ad_mask_min_ratio": 0.006,
                "ad_inpaint_only_masked_padding": 40,
            }
            notes.append("small_subject_recovery")
        elif wants_profile or wants_face_detail or (face_width_ratio is not None and face_width_ratio < 0.22):
            policy_id = "adetailer_profile_detail_v1"
            overrides = {
                "ad_confidence": 0.30,
                "ad_inpaint_only_masked_padding": 40,
            }
            notes.append("profile_or_detail_recovery")

        return policy_id, overrides, tuple(notes)

    def build_decision_bundle(
        self,
        *,
        mode: str,
        observation: dict[str, Any] | None = None,
    ) -> RefinementDecisionBundle:
        normalized_mode = mode if mode in {"disabled", "observe", "adetailer", "full"} else "disabled"
        observation_payload = dict(observation or {})
        policy_id: str | None = None
        applied_overrides: dict[str, Any] = {}
        notes: tuple[str, ...] = ()
        if normalized_mode == "observe":
            policy_id = "observe_only_v1"
        elif normalized_mode in {"adetailer", "full"}:
            policy_id, applied_overrides, notes = self._build_adetailer_policy(
                observation=cast(dict[str, Any], observation_payload),
            )
        return RefinementDecisionBundle(
            algorithm_version=self.algorithm_version,
            mode=normalized_mode,
            policy_id=policy_id,
            detector_id=str(observation_payload.get("subject_assessment", {}).get("detector_id") or "null"),
            observation=observation_payload,
            applied_overrides=applied_overrides,
            notes=notes,
        )
