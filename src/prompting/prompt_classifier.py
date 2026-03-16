from __future__ import annotations

from src.prompting.prompt_bucket_rules import PromptBucketRules
from src.prompting.prompt_normalizer import normalize_for_match
from src.prompting.prompt_splitter import detect_lora_syntax
from src.prompting.prompt_types import PromptPolarity


def _contains_any(text: str, candidates: set[str]) -> bool:
    return any(candidate in text for candidate in candidates)


def classify_chunk_rule_based(
    chunk: str,
    polarity: PromptPolarity,
    rules: PromptBucketRules,
) -> str:
    normalized = normalize_for_match(chunk)
    if not normalized:
        return "leftover_unknown"

    if polarity == "positive":
        if detect_lora_syntax(chunk):
            return "lora_tokens"
        if _contains_any(normalized, rules.positive_subject_markers):
            return "subject"
        if _contains_any(normalized, rules.positive_environment_keywords):
            return "environment"
        if _contains_any(normalized, rules.positive_pose_keywords):
            return "pose_action"
        if _contains_any(normalized, rules.positive_composition_keywords):
            return "composition"
        if _contains_any(normalized, rules.positive_lighting_keywords):
            return "lighting_atmosphere"
        if _contains_any(normalized, rules.positive_camera_keywords):
            return "camera_lens"
        if _contains_any(normalized, rules.positive_material_keywords):
            return "material_surface_detail"
        if _contains_any(normalized, rules.positive_style_keywords):
            return "style_medium"
        if _contains_any(normalized, rules.positive_quality_keywords):
            return "quality_tokens"
        return "leftover_unknown"

    if _contains_any(normalized, rules.negative_anatomy_keywords):
        return "anatomy_defects"
    if _contains_any(normalized, rules.negative_face_hand_keywords):
        return "face_hand_defects"
    if _contains_any(normalized, rules.negative_render_keywords):
        return "render_artifacts"
    if _contains_any(normalized, rules.negative_composition_keywords):
        return "composition_defects"
    if _contains_any(normalized, rules.negative_text_keywords):
        return "text_logo_watermark"
    if _contains_any(normalized, rules.negative_style_blocker_keywords):
        return "style_blockers"
    return "leftover_unknown"


def classify_chunk_score_based(
    chunk: str,
    polarity: PromptPolarity,
    rules: PromptBucketRules,
) -> str:
    normalized = normalize_for_match(chunk)
    if not normalized:
        return "leftover_unknown"

    if polarity == "positive" and detect_lora_syntax(chunk):
        return "lora_tokens"

    scoring_map = (
        {
            "subject": rules.positive_subject_markers,
            "environment": rules.positive_environment_keywords,
            "pose_action": rules.positive_pose_keywords,
            "composition": rules.positive_composition_keywords,
            "lighting_atmosphere": rules.positive_lighting_keywords,
            "camera_lens": rules.positive_camera_keywords,
            "material_surface_detail": rules.positive_material_keywords,
            "style_medium": rules.positive_style_keywords,
            "quality_tokens": rules.positive_quality_keywords,
        }
        if polarity == "positive"
        else {
            "anatomy_defects": rules.negative_anatomy_keywords,
            "face_hand_defects": rules.negative_face_hand_keywords,
            "render_artifacts": rules.negative_render_keywords,
            "composition_defects": rules.negative_composition_keywords,
            "text_logo_watermark": rules.negative_text_keywords,
            "style_blockers": rules.negative_style_blocker_keywords,
        }
    )

    best_bucket = "leftover_unknown"
    best_score = 0
    for bucket, keywords in scoring_map.items():
        score = sum(1 for keyword in keywords if keyword in normalized)
        if score > best_score:
            best_bucket = bucket
            best_score = score
    if best_score <= 0:
        return classify_chunk_rule_based(chunk, polarity, rules)
    return best_bucket
