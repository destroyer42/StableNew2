from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any

from src.prompting.contracts import (
    PromptContext,
    PromptIntentBundle,
    PromptOptimizerAnalysisBundle,
    PromptRecommendation,
    PromptSourceContext,
)
from src.prompting.prompt_intent_analyzer import PromptIntentAnalyzer
from src.prompting.prompt_optimizer_service import PromptOptimizerService
from src.prompting.prompt_splitter import split_prompt_chunks
from src.prompting.prompt_types import POSITIVE_BUCKET_ORDER, NEGATIVE_BUCKET_ORDER, PromptOptimizationPairResult
from src.utils.embedding_prompt_utils import extract_embedding_entries


@dataclass(frozen=True, slots=True)
class PromptOptimizerOrchestrationResult:
    optimization: PromptOptimizationPairResult
    analysis: PromptOptimizerAnalysisBundle


class PromptOptimizerOrchestrator:
    def __init__(
        self,
        *,
        service: PromptOptimizerService,
        analyzer: PromptIntentAnalyzer | None = None,
    ) -> None:
        self._service = service
        self._analyzer = analyzer or PromptIntentAnalyzer()

    def orchestrate(
        self,
        *,
        positive_prompt: str,
        negative_prompt: str,
        stage_name: str,
        config: dict[str, Any] | None = None,
    ) -> PromptOptimizerOrchestrationResult:
        optimization = self._service.optimize_prompts(
            positive_prompt,
            negative_prompt,
            pipeline_name=stage_name,
        )
        prompt_context = self._build_prompt_context(
            positive_prompt=positive_prompt,
            negative_prompt=negative_prompt,
            stage_name=stage_name,
            config=config,
            optimization=optimization,
        )
        intent = self._analyzer.infer(
            positive=positive_prompt,
            negative=negative_prompt,
            prompt_context=prompt_context,
        )
        recommendations = self._build_recommendations(
            stage_name=stage_name,
            prompt_context=prompt_context,
            intent=intent,
        )
        analysis = PromptOptimizerAnalysisBundle(
            stage=stage_name,
            mode="recommend_only_v1",
            context=prompt_context,
            intent=intent,
            recommendations=recommendations,
            warnings=list(prompt_context.warnings),
            errors=[],
        )
        return PromptOptimizerOrchestrationResult(optimization=optimization, analysis=analysis)

    def _build_prompt_context(
        self,
        *,
        positive_prompt: str,
        negative_prompt: str,
        stage_name: str,
        config: dict[str, Any] | None,
        optimization: PromptOptimizationPairResult,
    ) -> PromptContext:
        positive_chunks = split_prompt_chunks(positive_prompt)
        negative_chunks = split_prompt_chunks(negative_prompt)
        config_payload = dict(config or {})
        prompt_optimizer_cfg = dict(config_payload.get("prompt_optimizer") or {})
        large_chunk_threshold = int(prompt_optimizer_cfg.get("large_chunk_warning_threshold") or 18)
        warnings: list[str] = []
        if len(positive_chunks) >= large_chunk_threshold or len(negative_chunks) >= large_chunk_threshold:
            warnings.append("large_chunk_count")
        source = PromptSourceContext(
            prompt_source=str(config_payload.get("prompt_source") or ""),
            prompt_pack_id=str(config_payload.get("prompt_pack_id") or ""),
            prompt_pack_row_index=_optional_int(config_payload.get("prompt_pack_row_index")),
            run_mode=str(config_payload.get("run_mode") or ""),
            source=str(config_payload.get("source") or ""),
            tags=_coerce_tags(config_payload.get("tags")),
        )
        return PromptContext(
            stage=stage_name,
            pipeline_name=stage_name,
            positive_chunk_count=len(positive_chunks),
            negative_chunk_count=len(negative_chunks),
            positive_bucket_counts=_bucket_counts(optimization.positive.buckets, POSITIVE_BUCKET_ORDER),
            negative_bucket_counts=_bucket_counts(optimization.negative.buckets, NEGATIVE_BUCKET_ORDER),
            loras=_extract_loras(positive_prompt),
            embeddings=_extract_embeddings(positive_prompt),
            source=source,
            warnings=warnings,
        )

    def _build_recommendations(
        self,
        *,
        stage_name: str,
        prompt_context: PromptContext,
        intent: PromptIntentBundle,
    ) -> list[PromptRecommendation]:
        recommendations: list[PromptRecommendation] = []
        if stage_name in {"txt2img", "img2img"} and intent.has_people_tokens and intent.wants_face_detail:
            recommendations.append(
                PromptRecommendation(
                    recommendation_id="consider_face_pass",
                    category="stage_policy",
                    priority="medium",
                    target="adetailer",
                    action="consider_face_pass",
                    rationale="People-focused prompt with face-detail signals suggests an ADetailer face pass may help.",
                    suggested_settings={"enabled": True},
                )
            )
        if "large_chunk_count" in prompt_context.warnings:
            recommendations.append(
                PromptRecommendation(
                    recommendation_id="review_prompt_density",
                    category="operator_review",
                    priority="medium",
                    target="prompt",
                    action="review_prompt_density",
                    rationale="Prompt chunk count is above the configured warning threshold; review for over-constraint.",
                    suggested_settings={},
                )
            )
        for conflict in intent.conflicts:
            recommendations.append(
                PromptRecommendation(
                    recommendation_id=conflict,
                    category="prompt_conflict",
                    priority="high",
                    target="prompt",
                    action="review_prompt_conflict",
                    rationale=f"Detected prompt conflict: {conflict}.",
                    suggested_settings={},
                )
            )
        if intent.sensitive:
            recommendations.append(
                PromptRecommendation(
                    recommendation_id="sensitive_prompt_detected",
                    category="operator_review",
                    priority="low",
                    target="prompt",
                    action="confirm_sensitive_prompt_intent",
                    rationale="Prompt includes user-provided sensitive-content signals; record only, no mutation applied.",
                    suggested_settings={},
                )
            )
        return recommendations


def _bucket_counts(buckets: dict[str, list[str]], ordered_buckets: tuple[str, ...]) -> dict[str, int]:
    counts: dict[str, int] = {}
    for bucket in ordered_buckets:
        size = len(list(buckets.get(bucket) or []))
        if size:
            counts[bucket] = size
    return counts


def _extract_loras(text: str) -> list[dict[str, Any]]:
    pattern = re.compile(r"<\s*lora\s*:([^:>]+):([^>]+)>", re.IGNORECASE)
    loras: list[dict[str, Any]] = []
    for match in pattern.finditer(str(text or "")):
        name = match.group(1).strip()
        weight = _optional_float(match.group(2).strip())
        if name:
            loras.append({"name": name, "weight": weight})
    return loras


def _extract_embeddings(text: str) -> list[dict[str, Any]]:
    return [
        {"name": name, "weight": weight}
        for name, weight in extract_embedding_entries(str(text or ""))
        if str(name or "").strip()
    ]


def _optional_int(value: Any) -> int | None:
    try:
        if value in (None, ""):
            return None
        return int(value)
    except (TypeError, ValueError):
        return None


def _optional_float(value: Any) -> float | None:
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _coerce_tags(value: Any) -> list[str]:
    if isinstance(value, list):
        return [str(item).strip() for item in value if str(item).strip()]
    if isinstance(value, tuple):
        return [str(item).strip() for item in value if str(item).strip()]
    return []
