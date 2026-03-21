from __future__ import annotations

from pathlib import Path
from typing import Any


def _safe_float(value: Any) -> float | None:
    try:
        if value is None or value == "":
            return None
        return float(value)
    except (TypeError, ValueError):
        return None


def _safe_int(value: Any) -> int | None:
    try:
        if value is None or value == "":
            return None
        return int(value)
    except (TypeError, ValueError):
        return None


def _extract_subject_assessment(adaptive_refinement: dict[str, Any]) -> dict[str, Any]:
    decision_bundle = dict(adaptive_refinement.get("decision_bundle") or {})
    observation = dict(decision_bundle.get("observation") or {})
    subject_assessment = dict(observation.get("subject_assessment") or {})
    if subject_assessment:
        return subject_assessment
    image_assessments = observation.get("image_assessments") or []
    if isinstance(image_assessments, list) and image_assessments:
        first = image_assessments[0]
        if isinstance(first, dict):
            return dict(first)
    return {}


def compute_image_sharpness_variance(image_path: str | Path | None) -> float | None:
    if not image_path:
        return None
    try:
        import cv2  # type: ignore
    except Exception:
        return None
    try:
        image = cv2.imread(str(image_path), cv2.IMREAD_GRAYSCALE)
        if image is None:
            return None
        return float(cv2.Laplacian(image, cv2.CV_64F).var())
    except Exception:
        return None


def build_refinement_learning_context(
    adaptive_refinement: dict[str, Any] | None,
    *,
    output_paths: list[str] | None = None,
) -> dict[str, Any]:
    payload = dict(adaptive_refinement or {})
    if not payload:
        return {}

    intent = dict(payload.get("intent") or {})
    prompt_intent = dict(payload.get("prompt_intent") or {})
    decision_bundle = dict(payload.get("decision_bundle") or {})
    subject_assessment = _extract_subject_assessment(payload)
    image_decisions = payload.get("image_decisions") or []
    image_decision_count = len(image_decisions) if isinstance(image_decisions, list) else 0
    prompt_patch = dict(decision_bundle.get("prompt_patch") or {})
    applied_overrides = dict(decision_bundle.get("applied_overrides") or {})

    policy_ids: list[str] = []
    if decision_bundle.get("policy_id"):
        policy_ids.append(str(decision_bundle.get("policy_id")))
    if isinstance(image_decisions, list):
        for row in image_decisions:
            if not isinstance(row, dict):
                continue
            bundle = dict(row.get("decision_bundle") or {})
            policy_id = bundle.get("policy_id")
            if policy_id:
                policy_ids.append(str(policy_id))

    deduped_policy_ids: list[str] = []
    for item in policy_ids:
        if item not in deduped_policy_ids:
            deduped_policy_ids.append(item)

    face_count = _safe_int(subject_assessment.get("detection_count"))
    face_area_ratio = _safe_float(subject_assessment.get("face_area_ratio"))
    face_detected = bool((face_count or 0) > 0 or str(subject_assessment.get("scale_band") or "") not in {"", "no_face"})
    sharpness_variance = None
    if output_paths:
        sharpness_variance = compute_image_sharpness_variance(output_paths[0])

    return {
        "mode": str(intent.get("mode") or ""),
        "profile_id": str(intent.get("profile_id") or ""),
        "detector_preference": str(intent.get("detector_preference") or ""),
        "algorithm_version": str(decision_bundle.get("algorithm_version") or intent.get("algorithm_version") or ""),
        "policy_id": str(decision_bundle.get("policy_id") or ""),
        "policy_ids": list(deduped_policy_ids),
        "detector_id": str(decision_bundle.get("detector_id") or subject_assessment.get("detector_id") or ""),
        "scale_band": str(subject_assessment.get("scale_band") or ""),
        "pose_band": str(subject_assessment.get("pose_band") or ""),
        "face_detected": face_detected,
        "face_count": face_count,
        "face_area_ratio": face_area_ratio,
        "face_height_ratio": _safe_float(subject_assessment.get("face_height_ratio")),
        "face_width_ratio": _safe_float(subject_assessment.get("face_width_ratio")),
        "prompt_intent_band": str(prompt_intent.get("intent_band") or ""),
        "requested_pose": str(prompt_intent.get("requested_pose") or ""),
        "wants_face_detail": bool(prompt_intent.get("wants_face_detail")),
        "has_prompt_patch": bool(prompt_patch),
        "has_applied_overrides": bool(applied_overrides),
        "prompt_patch_ops": ",".join(
            key for key in ("add_positive", "remove_positive", "add_negative", "remove_negative") if prompt_patch.get(key)
        ),
        "applied_override_keys": ",".join(sorted(applied_overrides.keys())),
        "image_decision_count": image_decision_count,
        "sharpness_variance": sharpness_variance,
    }


__all__ = ["build_refinement_learning_context", "compute_image_sharpness_variance"]
