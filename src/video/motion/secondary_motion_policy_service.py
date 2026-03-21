from __future__ import annotations

from collections.abc import Mapping
from copy import deepcopy
from typing import Any

from .secondary_motion_models import SecondaryMotionIntent, SecondaryMotionPolicy


def _mapping_dict(value: Any) -> dict[str, Any]:
    if isinstance(value, Mapping):
        return deepcopy(dict(value))
    return {}


class SecondaryMotionPolicyService:
    def build_observation(
        self,
        *,
        intent: Mapping[str, Any] | None,
        stage_name: str,
        backend_id: str,
        prompt: str,
        negative_prompt: str,
        motion_profile: str = "",
        subject_summary: Mapping[str, Any] | None = None,
    ) -> dict[str, Any]:
        motion_intent = SecondaryMotionIntent.from_dict(intent)
        normalized_subject = _mapping_dict(subject_summary)
        prompt_features = self._infer_prompt_features(
            prompt=prompt,
            negative_prompt=negative_prompt,
            intent_label=motion_intent.intent,
        )
        policy = self.plan(
            intent=motion_intent,
            stage_name=stage_name,
            backend_id=backend_id,
            prompt_features=prompt_features,
            subject_summary=normalized_subject,
        )
        return {
            "intent": motion_intent.to_dict(),
            "policy": policy.to_dict(),
            "stage_name": stage_name,
            "backend_id": backend_id,
            "motion_profile": str(motion_profile or ""),
            "prompt_features": prompt_features,
            "subject_summary": normalized_subject,
        }

    def plan(
        self,
        *,
        intent: SecondaryMotionIntent | Mapping[str, Any] | None,
        stage_name: str,
        backend_id: str,
        prompt_features: Mapping[str, Any] | None = None,
        subject_summary: Mapping[str, Any] | None = None,
    ) -> SecondaryMotionPolicy:
        motion_intent = (
            intent if isinstance(intent, SecondaryMotionIntent) else SecondaryMotionIntent.from_dict(intent)
        )
        if not motion_intent.enabled or motion_intent.mode == "disabled":
            return SecondaryMotionPolicy(reasons=("secondary_motion_disabled",))

        features = _mapping_dict(prompt_features)
        subject = _mapping_dict(subject_summary)
        subject_scale = str(subject.get("scale_band") or subject.get("subject_scale") or "unknown")
        pose_class = str(subject.get("pose_band") or features.get("pose_class") or "steady")
        energy = float(features.get("energy", 0.35) or 0.35)
        steady = bool(features.get("camera_locked", False))

        intensity = min(0.9, max(0.1, energy))
        if steady:
            intensity = min(intensity, 0.3)
        if subject_scale == "micro":
            intensity = min(intensity, 0.18)
        elif subject_scale == "small":
            intensity = min(intensity, 0.26)
        elif subject_scale == "large":
            intensity = min(0.75, intensity + 0.1)

        damping = 0.92 if steady else 0.78
        if subject_scale in {"micro", "small"}:
            damping = max(damping, 0.88)
        frequency_hz = 0.18 if steady else 0.42
        if pose_class in {"action", "running", "flying"}:
            frequency_hz = 0.58
        cap_pixels = {
            "micro": 8,
            "small": 14,
            "medium": 24,
            "large": 36,
        }.get(subject_scale, 20)
        backend_mode = (
            "observe_native_candidate"
            if motion_intent.allow_native_backend
            else "observe_shared_postprocess_candidate"
        )
        if motion_intent.mode == "apply":
            backend_mode = (
                "apply_native_candidate"
                if motion_intent.allow_native_backend
                else "apply_shared_postprocess_candidate"
            )
        reasons = [
            f"stage={stage_name}",
            f"backend={backend_id}",
            f"intent={motion_intent.intent}",
            f"pose={pose_class}",
            f"subject_scale={subject_scale}",
        ]
        if motion_intent.allow_prompt_bias:
            reasons.append("prompt_bias_allowed")
        if motion_intent.allow_native_backend:
            reasons.append("native_backend_allowed")

        return SecondaryMotionPolicy(
            policy_id=f"{backend_id}_{stage_name}_{motion_intent.mode}_v1",
            enabled=True,
            backend_mode=backend_mode,
            intensity=round(float(intensity), 4),
            damping=round(float(damping), 4),
            frequency_hz=round(float(frequency_hz), 4),
            cap_pixels=cap_pixels,
            subject_scale=subject_scale,
            pose_class=pose_class,
            reasons=tuple(reasons),
            algorithm_version=motion_intent.algorithm_version,
        )

    @staticmethod
    def _infer_prompt_features(
        *,
        prompt: str,
        negative_prompt: str,
        intent_label: str,
    ) -> dict[str, Any]:
        text = f"{prompt} {intent_label}".lower()
        negative = negative_prompt.lower()
        action_tokens = ("running", "jump", "jumping", "dance", "dancing", "flying", "action", "spinning")
        calm_tokens = ("portrait", "still", "calm", "steady", "resting", "posed")
        float_tokens = ("floating", "hovering", "drifting")
        action_score = sum(1 for token in action_tokens if token in text)
        calm_score = sum(1 for token in calm_tokens if token in text)
        floating = any(token in text for token in float_tokens)
        camera_locked = "camera shake" in negative or calm_score > action_score
        pose_class = "steady"
        if floating:
            pose_class = "floating"
        elif action_score > calm_score:
            pose_class = "action"
        energy = 0.35
        if action_score:
            energy = min(0.75, 0.35 + (action_score * 0.12))
        elif calm_score:
            energy = 0.2
        if floating:
            energy = max(energy, 0.28)
        if camera_locked:
            energy = min(energy, 0.3)
        return {
            "pose_class": pose_class,
            "energy": round(float(energy), 4),
            "camera_locked": camera_locked,
            "floating": floating,
        }
