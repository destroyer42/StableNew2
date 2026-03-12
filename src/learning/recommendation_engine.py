# Subsystem: Learning
# Role: Explores parameter space to recommend improved configurations.

"""Automated Parameter Recommendation Engine (APRE).

Analyzes historical LearningRecordWriter data to provide parameter recommendations
for optimal Stable Diffusion settings based on user ratings.
"""

from __future__ import annotations

import json
import logging
import os
import statistics
import time
from collections import defaultdict
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

# PR-046: keywords used to infer people-presence from a prompt text
_PEOPLE_KEYWORDS: frozenset[str] = frozenset(
    {
        "woman", "man", "girl", "boy", "person", "people", "portrait",
        "face", "couple", "model", "male", "female", "lady", "gentleman",
        "child", "teen", "adult",
    }
)


@dataclass
class ParameterRecommendation:
    """A single parameter recommendation with confidence."""

    parameter_name: str
    recommended_value: Any
    confidence_score: float  # 0.0 to 1.0
    sample_count: int
    mean_rating: float
    rating_stddev: float
    confidence_rationale: str = ""
    context_key: str = ""

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary for UI display."""
        return {
            "parameter": self.parameter_name,
            "value": self.recommended_value,
            "confidence": self.confidence_score,
            "samples": self.sample_count,
            "mean_rating": self.mean_rating,
            "stddev": self.rating_stddev,
            "rationale": self.confidence_rationale,
            "context": self.context_key,
        }


# Evidence tier constants (PR-044)
EVIDENCE_TIER_EXPERIMENT_STRONG = "experiment_strong"
EVIDENCE_TIER_SPARSE_PLUS_REVIEW = "experiment_sparse_plus_review"
EVIDENCE_TIER_REVIEW_ONLY = "review_only"
EVIDENCE_TIER_NO_EVIDENCE = "no_evidence"


@dataclass
class RecommendationSet:
    """Complete set of recommendations for a prompt/stage combination."""

    prompt_text: str
    stage: str
    timestamp: float
    recommendations: list[ParameterRecommendation] = field(default_factory=list)
    # PR-044: evidence provenance
    evidence_tier: str = EVIDENCE_TIER_NO_EVIDENCE
    automation_eligible: bool = False

    def get_best_for_parameter(self, param_name: str) -> ParameterRecommendation | None:
        """Get the best recommendation for a specific parameter."""
        matches = [r for r in self.recommendations if r.parameter_name == param_name]
        return max(matches, key=lambda r: r.confidence_score) if matches else None

    def to_ui_format(self) -> list[dict[str, Any]]:
        """Convert to format suitable for UI display."""
        return [rec.to_dict() for rec in self.recommendations]


class RecommendationEngine:
    """Analyzes learning records to provide parameter recommendations.

    Uses statistical analysis of user ratings to identify optimal parameter settings
    for different prompts and pipeline stages.
    """

    def __init__(self, records_path: str | os.PathLike[str]) -> None:
        """Initialize with path to learning records JSONL file."""
        self.records_path = Path(records_path)
        self._cache: dict[str, Any] | None = None
        self._cache_timestamp: float = 0.0
        self._cache_mtime: float = 0.0

    def _should_reload_cache(self) -> bool:
        """Check if cache needs to be reloaded based on file modification time."""
        if not self.records_path.exists():
            return True
        mtime = self.records_path.stat().st_mtime
        return mtime > self._cache_mtime

    @staticmethod
    def _prompt_tokens(text: str) -> set[str]:
        parts = [p.strip().lower() for p in str(text or "").replace("\n", " ").split(",")]
        return {p for p in parts if p}

    @staticmethod
    def _prompt_similarity_bucket(query_prompt: str, record_prompt: str) -> str:
        query_tokens = RecommendationEngine._prompt_tokens(query_prompt)
        record_tokens = RecommendationEngine._prompt_tokens(record_prompt)
        if not query_tokens or not record_tokens:
            return "unknown"
        overlap = len(query_tokens.intersection(record_tokens)) / max(1, len(query_tokens))
        if overlap >= 0.6:
            return "high"
        if overlap >= 0.3:
            return "medium"
        return "low"

    @staticmethod
    def _resolution_bucket(width: Any, height: Any) -> str:
        try:
            w = int(width or 0)
            h = int(height or 0)
        except Exception:
            return "unknown"
        pixels = w * h
        if pixels <= 0:
            return "unknown"
        if pixels <= 512 * 512:
            return "small"
        if pixels <= 1024 * 1024:
            return "medium"
        return "large"

    def _build_query_context(self, prompt_text: str, stage: str) -> dict[str, str]:
        # PR-046: detect people presence for context-aware subscore weighting
        lower_tokens = {
            t.strip().lower()
            for t in str(prompt_text or "").replace(",", " ").split()
            if t.strip()
        }
        has_people = bool(lower_tokens & _PEOPLE_KEYWORDS)
        return {
            "stage": str(stage or "txt2img"),
            "style_bucket": "default",
            "prompt_similarity_bucket": "high",
            "resolution_bucket": "unknown",
            "model": "",
            "has_people": str(has_people),
        }

    def _load_records(self) -> list[dict[str, Any]]:
        """Load and parse all learning records from JSONL file."""
        if not self.records_path.exists():
            return []

        records = []
        try:
            with open(self.records_path, encoding="utf-8") as f:
                for line_num, line in enumerate(f, 1):
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        record = json.loads(line)
                        records.append(record)
                    except json.JSONDecodeError as e:
                        logger.warning(f"Skipping malformed JSON at line {line_num}: {e}")
                        continue
        except Exception as e:
            logger.error(f"Failed to load records from {self.records_path}: {e}")
            return []

        return records

    def _score_records(self, records: list[dict[str, Any]]) -> list[dict[str, Any]]:
        """Filter and score records that have user ratings."""
        scored_records = []

        for record in records:
            metadata = record.get("metadata", {})
            record_kind = str(metadata.get("record_kind") or "").strip()
            if record_kind and record_kind not in {"learning_experiment_rating", "review_tab_feedback"}:
                continue

            # Only consider records with user ratings
            user_rating = metadata.get("user_rating")
            if user_rating is None:
                continue

            try:
                rating = float(user_rating)
                if not (1 <= rating <= 5):
                    continue
            except (ValueError, TypeError):
                continue

            base_config = record.get("base_config", {}) or {}

            # Extract experiment context
            experiment_name = metadata.get("experiment_name", "")
            variable_under_test = metadata.get("variable_under_test", "")
            variant_value = metadata.get("variant_value")

            # Extract parameter values from the record
            primary_sampler = record.get("primary_sampler", "")
            primary_scheduler = record.get("primary_scheduler", "")
            primary_steps = record.get("primary_steps", 0)
            primary_cfg_scale = record.get("primary_cfg_scale", 0.0)

            # Get timestamp for recency weighting
            timestamp_str = record.get("timestamp", "")
            try:
                # Parse ISO timestamp
                timestamp = time.mktime(time.strptime(timestamp_str, "%Y-%m-%dT%H:%M:%S"))
            except (ValueError, TypeError):
                timestamp = time.time()  # Use current time if parsing fails

            scored_record = {
                "rating": rating,
                "record_kind": record_kind or "legacy",
                "experiment_name": experiment_name,
                "variable_under_test": variable_under_test,
                "variant_value": variant_value,
                "primary_sampler": primary_sampler,
                "primary_scheduler": primary_scheduler,
                "primary_steps": primary_steps,
                "primary_cfg_scale": primary_cfg_scale,
                "timestamp": timestamp,
                "metadata": metadata,
                "base_prompt": str(base_config.get("prompt", "")),
                "stage": str(
                    metadata.get("stage")
                    or base_config.get("stage")
                    or metadata.get("stage_name")
                    or "txt2img"
                ),
                "model": str(
                    record.get("primary_model")
                    or metadata.get("model")
                    or base_config.get("model")
                    or ""
                ),
                "style_bucket": str(metadata.get("style_bucket") or "default"),
                "resolution_bucket": self._resolution_bucket(
                    base_config.get("width"),
                    base_config.get("height"),
                ),
                # PR-046: normalized rating detail for context-aware weighting
                **self._normalize_metadata_detail(metadata),
            }
            scored_records.append(scored_record)

        return scored_records

    def _compute_context_weight(
        self,
        record: dict[str, Any],
        query_context: dict[str, str],
        query_prompt: str,
    ) -> tuple[float, str]:
        weight = 1.0
        rationale_bits = []
        if str(record.get("stage", "")) == str(query_context.get("stage", "")):
            weight += 0.6
            rationale_bits.append("stage-match")
        else:
            weight -= 0.35
            rationale_bits.append("stage-mismatch")

        query_model = str(query_context.get("model", "")).strip().lower()
        record_model = str(record.get("model", "")).strip().lower()
        if query_model and record_model:
            if query_model == record_model:
                weight += 0.3
                rationale_bits.append("model-match")
            else:
                weight -= 0.1
                rationale_bits.append("model-mismatch")

        prompt_bucket = self._prompt_similarity_bucket(
            query_prompt,
            str(record.get("base_prompt", "")),
        )
        if prompt_bucket == "high":
            weight += 0.45
        elif prompt_bucket == "medium":
            weight += 0.2
        elif prompt_bucket == "low":
            weight -= 0.2
        rationale_bits.append(f"prompt-{prompt_bucket}")

        # PR-046: conservative rating-detail adjustment (bounded ±0.15)
        query_has_people = str(query_context.get("has_people", "")).lower() == "true"
        weight, detail_tag = self._apply_rating_detail_adjustment(weight, record, query_has_people)
        if detail_tag:
            rationale_bits.append(detail_tag)

        return max(0.05, weight), ",".join(rationale_bits)

    @staticmethod
    def _normalize_metadata_detail(metadata: dict[str, Any]) -> dict[str, Any]:
        """Inline metadata normalization for scored records (PR-046).

        Returns {'subscores': {...}, 'context_flags': {...}} using the same
        logic as ``LearningRecord.extract_rating_detail`` but without the import.
        """
        subscores_raw = metadata.get("subscores") or metadata.get("rating_details") or {}
        subscores: dict[str, float] = {}
        if isinstance(subscores_raw, dict):
            for key in ("anatomy", "composition", "prompt_adherence"):
                val = subscores_raw.get(key)
                if val is not None:
                    try:
                        f = float(val)
                        if 1.0 <= f <= 5.0:
                            subscores[key] = f
                    except (TypeError, ValueError):
                        pass
        context_raw = metadata.get("rating_context") or metadata.get("review_context") or {}
        context_flags = dict(context_raw) if isinstance(context_raw, dict) else {}
        return {"subscores": subscores, "context_flags": context_flags}

    @staticmethod
    def _apply_rating_detail_adjustment(
        weight: float,
        scored_record: dict[str, Any],
        query_has_people: bool,
    ) -> tuple[float, str]:
        """Apply conservative bounded (±0.15) weight adjustment from rating detail.

        Two adjustments applied when detail is present:
        1. Subscore quality: avg subscore vs baseline 3.0 → ±0.05 max.
        2. Context-mismatch penalty: -0.10 when record has no people but query
           requires people AND anatomy subscore is poor (< 3.0).

        Returns (adjusted_weight, rationale_tag). ``rationale_tag`` is empty
        when no adjustment is made.
        """
        subscores = scored_record.get("subscores") or {}
        context_flags = scored_record.get("context_flags") or {}

        if not subscores:
            return weight, ""

        # 1. Subscore quality adjustment — maps avg [1,5] → [-0.05, +0.05]
        valid: list[float] = []
        for val in subscores.values():
            try:
                f = float(val)
                if 1.0 <= f <= 5.0:
                    valid.append(f)
            except (TypeError, ValueError):
                pass

        adjustment = 0.0
        tag_parts: list[str] = []
        if valid:
            avg_sub = sum(valid) / len(valid)
            quality_adj = (avg_sub - 3.0) * 0.025
            adjustment += quality_adj
            if quality_adj != 0.0:
                tag_parts.append(f"subscore-adj:{quality_adj:+.3f}")

        # 2. Context-mismatch penalty
        record_has_people = context_flags.get("has_people")
        if record_has_people is not None:
            record_has_people_bool = bool(record_has_people)
            if query_has_people and not record_has_people_bool:
                anatomy_score = subscores.get("anatomy")
                if anatomy_score is not None:
                    try:
                        if float(anatomy_score) < 3.0:
                            adjustment -= 0.10
                            tag_parts.append("ctx-mismatch:-0.10")
                    except (TypeError, ValueError):
                        pass

        new_weight = max(0.05, weight + adjustment)
        return new_weight, ",".join(tag_parts)

    def _compute_optimal_settings(
        self,
        records: list[dict[str, Any]],
        query_context: dict[str, str],
        query_prompt: str,
    ) -> dict[str, ParameterRecommendation]:
        """Compute optimal parameter settings from scored records."""
        recommendations = {}

        # Group records by parameter type and value
        param_groups: dict[str, dict[Any, list[float]]] = defaultdict(lambda: defaultdict(list))
        param_raw: dict[str, dict[Any, list[float]]] = defaultdict(lambda: defaultdict(list))
        param_reasons: dict[str, dict[Any, list[str]]] = defaultdict(lambda: defaultdict(list))
        param_context_weights: dict[str, dict[Any, list[float]]] = defaultdict(
            lambda: defaultdict(list)
        )

        for record in records:
            weight, rationale = self._compute_context_weight(record, query_context, query_prompt)
            rating = record["rating"] * weight

            # Collect ratings for each parameter type
            param_groups["sampler"][record["primary_sampler"]].append(rating)
            param_groups["scheduler"][record["primary_scheduler"]].append(rating)
            param_groups["steps"][record["primary_steps"]].append(rating)
            param_groups["cfg_scale"][record["primary_cfg_scale"]].append(rating)
            param_raw["sampler"][record["primary_sampler"]].append(float(record["rating"]))
            param_raw["scheduler"][record["primary_scheduler"]].append(float(record["rating"]))
            param_raw["steps"][record["primary_steps"]].append(float(record["rating"]))
            param_raw["cfg_scale"][record["primary_cfg_scale"]].append(float(record["rating"]))
            param_reasons["sampler"][record["primary_sampler"]].append(rationale)
            param_reasons["scheduler"][record["primary_scheduler"]].append(rationale)
            param_reasons["steps"][record["primary_steps"]].append(rationale)
            param_reasons["cfg_scale"][record["primary_cfg_scale"]].append(rationale)
            param_context_weights["sampler"][record["primary_sampler"]].append(weight)
            param_context_weights["scheduler"][record["primary_scheduler"]].append(weight)
            param_context_weights["steps"][record["primary_steps"]].append(weight)
            param_context_weights["cfg_scale"][record["primary_cfg_scale"]].append(weight)

            # If this record is from a variable test, also track that parameter
            if record["variable_under_test"] and record["variant_value"] is not None:
                param_name = record["variable_under_test"].lower().replace(" ", "_")
                param_groups[param_name][record["variant_value"]].append(rating)
                param_raw[param_name][record["variant_value"]].append(float(record["rating"]))
                param_reasons[param_name][record["variant_value"]].append(rationale)
                param_context_weights[param_name][record["variant_value"]].append(weight)

        # Compute recommendations for each parameter
        for param_name, value_ratings in param_groups.items():
            if not value_ratings:
                continue

            # Find the value with highest confidence score
            best_value = None
            best_confidence = 0.0
            best_mean = 0.0
            best_stddev = 0.0
            best_count = 0

            for value, ratings in value_ratings.items():
                if len(ratings) < 1:
                    continue

                mean_rating = statistics.mean(ratings)
                raw_ratings = param_raw[param_name][value]
                raw_mean = statistics.mean(raw_ratings) if raw_ratings else mean_rating
                try:
                    stddev = statistics.stdev(raw_ratings)
                except statistics.StatisticsError:
                    stddev = 0.0

                count = len(ratings)

                # Confidence with explicit sample-volume + variance terms.
                sample_confidence = min(1.0, count / 6.0)
                variance_penalty = min(1.0, stddev / 2.5)
                consistency_confidence = 1.0 - variance_penalty
                context_weights = param_context_weights[param_name][value]
                context_confidence = 0.0
                if context_weights:
                    context_confidence = max(
                        0.0,
                        min(1.0, statistics.mean(context_weights) / 2.0),
                    )
                confidence = max(
                    0.0,
                    min(
                        1.0,
                        (sample_confidence * 0.45)
                        + (consistency_confidence * 0.25)
                        + (context_confidence * 0.30),
                    ),
                )

                # Select based on confidence, break ties by highest rating
                if confidence > best_confidence or (
                    confidence == best_confidence and raw_mean > best_mean
                ):
                    best_value = value
                    best_confidence = confidence
                    best_mean = raw_mean
                    best_stddev = stddev
                    best_count = count

            if best_value is not None:
                reasons = param_reasons[param_name][best_value]
                reason = reasons[-1] if reasons else ""
                recommendations[param_name] = ParameterRecommendation(
                    parameter_name=param_name,
                    recommended_value=best_value,
                    confidence_score=round(best_confidence, 3),
                    sample_count=best_count,
                    mean_rating=round(best_mean, 2),
                    rating_stddev=round(best_stddev, 2),
                    confidence_rationale=(
                        f"samples={best_count}; stddev={round(best_stddev, 3)}; "
                        f"context={reason or 'mixed'}"
                    ),
                    context_key=(
                        f"{query_context.get('stage','')}|"
                        f"{query_context.get('model','')}|"
                        f"{query_context.get('style_bucket','default')}|"
                        f"{query_context.get('resolution_bucket','unknown')}"
                    ),
                )

        return recommendations

    def _find_trends_across_variables(self, records: list[dict[str, Any]]) -> dict[str, Any]:
        """Find trends and correlations across different variables."""
        # This is a placeholder for future trend analysis
        # Could implement correlation analysis between parameters
        return {}

    def recommend(self, prompt_text: str, stage: str) -> RecommendationSet:
        """Get recommendations for a specific prompt and stage combination."""
        query_context = self._build_query_context(prompt_text, stage)
        if self._should_reload_cache():
            records = self._load_records()
            scored_records = self._score_records(records)
            self._cache = {
                "scored_records": scored_records,
                "timestamp": time.time(),
                "raw_record_count": len(records),
                "record_count": len(scored_records),
            }
            self._cache_timestamp = time.time()
            self._cache_mtime = self.records_path.stat().st_mtime if self.records_path.exists() else 0.0
        scored_records = self._cache.get("scored_records", []) if self._cache else []
        stage_name = str(stage or "txt2img")
        relevant_records = [
            record
            for record in scored_records
            if str(record.get("stage", "") or "txt2img") == stage_name
        ]
        experiment_records = [
            record for record in relevant_records if str(record.get("record_kind", "")) == "learning_experiment_rating"
        ]
        review_records = [
            record for record in relevant_records if str(record.get("record_kind", "")) == "review_tab_feedback"
        ]
        # PR-044: deterministic evidence-tier policy — never suppress usable evidence
        if len(experiment_records) >= 3:
            evidence_records = experiment_records
            evidence_tier = EVIDENCE_TIER_EXPERIMENT_STRONG
            automation_eligible = True
        elif experiment_records:
            # Sparse experiment data: merge with any review feedback; flag manual-only
            evidence_records = experiment_records + review_records
            evidence_tier = EVIDENCE_TIER_SPARSE_PLUS_REVIEW
            automation_eligible = False
        elif review_records:
            evidence_records = review_records
            evidence_tier = EVIDENCE_TIER_REVIEW_ONLY
            automation_eligible = False
        else:
            evidence_records = []
            evidence_tier = EVIDENCE_TIER_NO_EVIDENCE
            automation_eligible = False

        if not evidence_records:
            return RecommendationSet(
                prompt_text=prompt_text,
                stage=stage,
                timestamp=time.time(),
                recommendations=[],
                evidence_tier=EVIDENCE_TIER_NO_EVIDENCE,
                automation_eligible=False,
            )

        optimal_settings = self._compute_optimal_settings(evidence_records, query_context, prompt_text)

        # Create recommendation set with PR-044 tier provenance
        rec_set = RecommendationSet(
            prompt_text=prompt_text,
            stage=stage,
            timestamp=time.time(),
            recommendations=list(optimal_settings.values()),
            evidence_tier=evidence_tier,
            automation_eligible=automation_eligible,
        )

        # Sort by confidence score (highest first)
        rec_set.recommendations.sort(key=lambda r: r.confidence_score, reverse=True)

        return rec_set

    def get_statistics(self) -> dict[str, Any]:
        """Get statistics about the recommendation engine's data."""
        if self._cache is None or self._should_reload_cache():
            records = self._load_records()
            scored_records = self._score_records(records)

            return {
                "total_records": len(records),
                "rated_records": len(scored_records),
                "cache_timestamp": self._cache_timestamp,
                "records_path": str(self.records_path),
            }
        else:
            return {
                "total_records": self._cache.get("raw_record_count", 0),
                "rated_records": self._cache.get("record_count", 0),
                "cache_timestamp": self._cache_timestamp,
                "records_path": str(self.records_path),
                "cached": True,
            }
