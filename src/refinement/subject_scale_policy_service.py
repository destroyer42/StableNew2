from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

from PIL import Image

from .detectors.base_detector import SubjectDetector
from .detectors.null_detector import NullDetector
from .refinement_policy_registry import NoOpRefinementPolicyRegistry, RefinementPolicyRegistry


@dataclass(frozen=True, slots=True)
class SubjectScalePolicyConfig:
    algorithm_version: str = "v1"
    micro_face_area_ratio: float = 0.004
    small_face_area_ratio: float = 0.012
    medium_face_area_ratio: float = 0.030


class SubjectScalePolicyService:
    def __init__(
        self,
        *,
        detector: SubjectDetector | None = None,
        registry: RefinementPolicyRegistry | None = None,
        cfg: SubjectScalePolicyConfig | None = None,
        unavailable_reason: str | None = None,
    ) -> None:
        self._detector = detector or NullDetector()
        self._registry = registry or NoOpRefinementPolicyRegistry()
        self._cfg = cfg or SubjectScalePolicyConfig()
        self._unavailable_reason = unavailable_reason

    def assess(self, image_path: Path | None = None) -> dict[str, Any]:
        status = "available"
        notes: list[str] = []
        detections: tuple[dict[str, Any], ...] = ()
        if self._unavailable_reason or image_path is None:
            status = "unavailable"
            notes.append(self._unavailable_reason or "assessment_unavailable")
        else:
            try:
                detections = self._detector.detect_faces(image_path)
            except Exception as exc:
                status = "error"
                notes.append(f"detector_error: {exc}")
        image_w: int | None = None
        image_h: int | None = None
        face_area_ratio: float | None = None
        face_height_ratio: float | None = None
        face_width_ratio: float | None = None
        scale_band = "unknown"
        if status != "available":
            pass  # Unavailable/error observations remain unknown, never confirmed no-face.
        elif not detections:
            notes.append("no_face_detected")
            scale_band = "no_face"
        elif image_path is not None:
            with Image.open(image_path) as image:
                image_w, image_h = image.size
            primary = max(detections, key=lambda item: int(item["w"]) * int(item["h"]))
            area = float(primary["w"]) * float(primary["h"])
            total_area = float(image_w) * float(image_h) if image_w and image_h else 0.0
            face_area_ratio = (area / total_area) if total_area > 0 else None
            face_height_ratio = (float(primary["h"]) / float(image_h)) if image_h else None
            face_width_ratio = (float(primary["w"]) / float(image_w)) if image_w else None
            if face_area_ratio is None:
                scale_band = "unknown"
            elif face_area_ratio < self._cfg.micro_face_area_ratio:
                scale_band = "micro"
            elif face_area_ratio < self._cfg.small_face_area_ratio:
                scale_band = "small"
            elif face_area_ratio < self._cfg.medium_face_area_ratio:
                scale_band = "medium"
            else:
                scale_band = "large"
        return {
            "detector_id": self._detector.detector_id,
            "algorithm_version": self._cfg.algorithm_version,
            "detector_algorithm_version": getattr(self._detector, "algorithm_version", "unknown"),
            "detector_model_sha256": getattr(self._detector, "model_sha256", ""),
            "detection_status": status,
            "image_path": str(image_path) if image_path is not None else None,
            "image_width": image_w,
            "image_height": image_h,
            "detections": [dict(item) for item in detections],
            "detection_count": len(detections),
            "primary_detection_index": 0 if detections else None,
            "face_area_ratio": face_area_ratio,
            "face_height_ratio": face_height_ratio,
            "face_width_ratio": face_width_ratio,
            "scale_band": scale_band,
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
