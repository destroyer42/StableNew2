from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict, List, Literal

PromptPolarity = Literal["positive", "negative"]

PositiveBucket = Literal[
    "subject",
    "environment",
    "pose_action",
    "composition",
    "lighting_atmosphere",
    "camera_lens",
    "material_surface_detail",
    "style_medium",
    "lora_tokens",
    "quality_tokens",
    "leftover_unknown",
]

NegativeBucket = Literal[
    "anatomy_defects",
    "face_hand_defects",
    "render_artifacts",
    "composition_defects",
    "text_logo_watermark",
    "style_blockers",
    "leftover_unknown",
]

POSITIVE_BUCKET_ORDER: tuple[PositiveBucket, ...] = (
    "subject",
    "environment",
    "pose_action",
    "composition",
    "lighting_atmosphere",
    "camera_lens",
    "material_surface_detail",
    "style_medium",
    "lora_tokens",
    "quality_tokens",
    "leftover_unknown",
)

NEGATIVE_BUCKET_ORDER: tuple[NegativeBucket, ...] = (
    "anatomy_defects",
    "face_hand_defects",
    "render_artifacts",
    "composition_defects",
    "text_logo_watermark",
    "style_blockers",
    "leftover_unknown",
)


@dataclass(slots=True)
class PromptChunk:
    sequence_index: int
    original_text: str
    normalized_text: str
    dedupe_key: str
    polarity: PromptPolarity
    bucket: str
    weight_syntax_detected: bool = False
    lora_syntax_detected: bool = False


@dataclass(slots=True)
class PromptOptimizationResult:
    original_prompt: str
    optimized_prompt: str
    polarity: PromptPolarity
    buckets: Dict[str, List[str]] = field(default_factory=dict)
    dropped_duplicates: List[str] = field(default_factory=list)
    changed: bool = False


@dataclass(slots=True)
class PromptOptimizationPairResult:
    positive: PromptOptimizationResult
    negative: PromptOptimizationResult
