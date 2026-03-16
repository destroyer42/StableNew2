from __future__ import annotations

from dataclasses import dataclass
from typing import Set

from src.config.prompting_defaults import DEFAULT_NEGATIVE_KEYWORDS, DEFAULT_POSITIVE_KEYWORDS


@dataclass(frozen=True, slots=True)
class PromptBucketRules:
    positive_subject_markers: Set[str]
    positive_environment_keywords: Set[str]
    positive_pose_keywords: Set[str]
    positive_composition_keywords: Set[str]
    positive_lighting_keywords: Set[str]
    positive_camera_keywords: Set[str]
    positive_material_keywords: Set[str]
    positive_style_keywords: Set[str]
    positive_quality_keywords: Set[str]
    negative_anatomy_keywords: Set[str]
    negative_face_hand_keywords: Set[str]
    negative_render_keywords: Set[str]
    negative_composition_keywords: Set[str]
    negative_text_keywords: Set[str]
    negative_style_blocker_keywords: Set[str]


def build_default_prompt_bucket_rules() -> PromptBucketRules:
    return PromptBucketRules(
        positive_subject_markers=set(DEFAULT_POSITIVE_KEYWORDS["subject"]),
        positive_environment_keywords=set(DEFAULT_POSITIVE_KEYWORDS["environment"]),
        positive_pose_keywords=set(DEFAULT_POSITIVE_KEYWORDS["pose_action"]),
        positive_composition_keywords=set(DEFAULT_POSITIVE_KEYWORDS["composition"]),
        positive_lighting_keywords=set(DEFAULT_POSITIVE_KEYWORDS["lighting_atmosphere"]),
        positive_camera_keywords=set(DEFAULT_POSITIVE_KEYWORDS["camera_lens"]),
        positive_material_keywords=set(DEFAULT_POSITIVE_KEYWORDS["material_surface_detail"]),
        positive_style_keywords=set(DEFAULT_POSITIVE_KEYWORDS["style_medium"]),
        positive_quality_keywords=set(DEFAULT_POSITIVE_KEYWORDS["quality_tokens"]),
        negative_anatomy_keywords=set(DEFAULT_NEGATIVE_KEYWORDS["anatomy_defects"]),
        negative_face_hand_keywords=set(DEFAULT_NEGATIVE_KEYWORDS["face_hand_defects"]),
        negative_render_keywords=set(DEFAULT_NEGATIVE_KEYWORDS["render_artifacts"]),
        negative_composition_keywords=set(DEFAULT_NEGATIVE_KEYWORDS["composition_defects"]),
        negative_text_keywords=set(DEFAULT_NEGATIVE_KEYWORDS["text_logo_watermark"]),
        negative_style_blocker_keywords=set(DEFAULT_NEGATIVE_KEYWORDS["style_blockers"]),
    )
