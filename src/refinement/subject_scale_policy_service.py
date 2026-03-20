from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .detectors.base_detector import SubjectDetector
from .detectors.null_detector import NullDetector
from .refinement_policy_registry import NoOpRefinementPolicyRegistry, RefinementPolicyRegistry


@dataclass(frozen=True, slots=True)
class SubjectScalePolicyConfig:
    algorithm_version: str = "v1"


class SubjectScalePolicyService:
    def __init__(
        self,
        *,
        detector: SubjectDetector | None = None,
        registry: RefinementPolicyRegistry | None = None,
        cfg: SubjectScalePolicyConfig | None = None,
    ) -> None:
        self._detector = detector or NullDetector()
        self._registry = registry or NoOpRefinementPolicyRegistry()
        self._cfg = cfg or SubjectScalePolicyConfig()

    def assess(self, image_path: Path | None = None) -> dict[str, Any]:
        detections = self._detector.detect_faces(image_path) if image_path is not None else ()
        notes = ["assessment_unavailable"] if image_path is None else []
        if not detections:
            notes.append("no_face_detected")
        return {
            "detector_id": self._detector.detector_id,
            "image_path": str(image_path) if image_path is not None else None,
            "detection_count": len(detections),
            "primary_detection_index": 0 if detections else None,
            "scale_band": "no_face" if not detections else "unknown",
            "pose_band": "unknown",
            "notes": notes,
        }

    def build_bundle(
        self,
        *,
        mode: str,
        prompt_intent: dict[str, Any],
        image_path: Path | None = None,
        extra_observation: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        assessment = self.assess(image_path=image_path)
        observation = {
            "prompt_intent": dict(prompt_intent),
            "subject_assessment": assessment,
        }
        if extra_observation:
            observation.update(dict(extra_observation))
        bundle = self._registry.build_decision_bundle(mode=mode, observation=observation)
        return bundle.to_dict()
