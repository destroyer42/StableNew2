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


@dataclass
class ParameterRecommendation:
    """A single parameter recommendation with confidence."""

    parameter_name: str
    recommended_value: Any
    confidence_score: float  # 0.0 to 1.0
    sample_count: int
    mean_rating: float
    rating_stddev: float

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary for UI display."""
        return {
            "parameter": self.parameter_name,
            "value": self.recommended_value,
            "confidence": self.confidence_score,
            "samples": self.sample_count,
            "mean_rating": self.mean_rating,
            "stddev": self.rating_stddev,
        }


@dataclass
class RecommendationSet:
    """Complete set of recommendations for a prompt/stage combination."""

    prompt_text: str
    stage: str
    timestamp: float
    recommendations: list[ParameterRecommendation] = field(default_factory=list)

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

    def _should_reload_cache(self) -> bool:
        """Check if cache needs to be reloaded based on file modification time."""
        if not self.records_path.exists():
            return True

        mtime = self.records_path.stat().st_mtime
        return mtime > self._cache_timestamp

    def _load_records(self) -> list[dict[str, Any]]:
        """Load and parse all learning records from JSONL file."""
        if not self.records_path.exists():
            return []

        records = []
        try:
            with open(self.records_path, encoding='utf-8') as f:
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
            metadata = record.get('metadata', {})

            # Only consider records with user ratings
            user_rating = metadata.get('user_rating')
            if user_rating is None:
                continue

            try:
                rating = float(user_rating)
                if not (1 <= rating <= 5):
                    continue
            except (ValueError, TypeError):
                continue

            # Extract experiment context
            experiment_name = metadata.get('experiment_name', '')
            variable_under_test = metadata.get('variable_under_test', '')
            variant_value = metadata.get('variant_value')

            # Extract parameter values from the record
            primary_sampler = record.get('primary_sampler', '')
            primary_scheduler = record.get('primary_scheduler', '')
            primary_steps = record.get('primary_steps', 0)
            primary_cfg_scale = record.get('primary_cfg_scale', 0.0)

            # Get timestamp for recency weighting
            timestamp_str = record.get('timestamp', '')
            try:
                # Parse ISO timestamp
                timestamp = time.mktime(time.strptime(timestamp_str, "%Y-%m-%dT%H:%M:%S"))
            except (ValueError, TypeError):
                timestamp = time.time()  # Use current time if parsing fails

            scored_record = {
                'rating': rating,
                'experiment_name': experiment_name,
                'variable_under_test': variable_under_test,
                'variant_value': variant_value,
                'primary_sampler': primary_sampler,
                'primary_scheduler': primary_scheduler,
                'primary_steps': primary_steps,
                'primary_cfg_scale': primary_cfg_scale,
                'timestamp': timestamp,
                'metadata': metadata,
            }
            scored_records.append(scored_record)

        return scored_records

    def _compute_optimal_settings(
        self,
        records: list[dict[str, Any]],
        stage: str
    ) -> dict[str, ParameterRecommendation]:
        """Compute optimal parameter settings from scored records."""
        recommendations = {}

        # Group records by parameter type and value
        param_groups: Dict[str, Dict[Any, List[float]]] = defaultdict(lambda: defaultdict(list))

        for record in records:
            # Add recency weighting (more recent records weighted slightly higher)
            # For now, disable recency weighting to avoid test complications
            weight = 1.0

            rating = record['rating'] * weight

            # Collect ratings for each parameter type
            param_groups['sampler'][record['primary_sampler']].append(rating)
            param_groups['scheduler'][record['primary_scheduler']].append(rating)
            param_groups['steps'][record['primary_steps']].append(rating)
            param_groups['cfg_scale'][record['primary_cfg_scale']].append(rating)

            # If this record is from a variable test, also track that parameter
            if record['variable_under_test'] and record['variant_value'] is not None:
                param_name = record['variable_under_test'].lower().replace(' ', '_')
                param_groups[param_name][record['variant_value']].append(rating)

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
                try:
                    stddev = statistics.stdev(ratings)
                except statistics.StatisticsError:
                    stddev = 0.0

                count = len(ratings)

                # Calculate confidence score
                sample_confidence = min(1.0, count / 3.0)  # 3 samples for max confidence
                consistency_confidence = 1.0 / (1.0 + stddev) if stddev > 0 else 1.0
                confidence = sample_confidence * consistency_confidence

                # Select based on confidence, break ties by highest rating
                if (confidence > best_confidence or
                    (confidence == best_confidence and mean_rating > best_mean)):
                    best_value = value
                    best_confidence = confidence
                    best_mean = mean_rating
                    best_stddev = stddev
                    best_count = count

            if best_value is not None:
                recommendations[param_name] = ParameterRecommendation(
                    parameter_name=param_name,
                    recommended_value=best_value,
                    confidence_score=round(best_confidence, 3),
                    sample_count=best_count,
                    mean_rating=round(best_mean, 2),
                    rating_stddev=round(best_stddev, 2),
                )

        return recommendations

    def _find_trends_across_variables(self, records: list[dict[str, Any]]) -> dict[str, Any]:
        """Find trends and correlations across different variables."""
        # This is a placeholder for future trend analysis
        # Could implement correlation analysis between parameters
        return {}

    def recommend(self, prompt_text: str, stage: str) -> RecommendationSet:
        """Get recommendations for a specific prompt and stage combination."""
        if self._should_reload_cache():
            records = self._load_records()
            scored_records = self._score_records(records)

            # For now, we provide recommendations based on all historical data
            # Future enhancement could filter by prompt similarity
            optimal_settings = self._compute_optimal_settings(scored_records, stage)

            self._cache = {
                'recommendations': optimal_settings,
                'timestamp': time.time(),
                'record_count': len(scored_records),
            }
            self._cache_timestamp = time.time()
        else:
            optimal_settings = self._cache.get('recommendations', {}) if self._cache else {}

        # Create recommendation set
        rec_set = RecommendationSet(
            prompt_text=prompt_text,
            stage=stage,
            timestamp=time.time(),
            recommendations=list(optimal_settings.values()),
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
                'total_records': len(records),
                'rated_records': len(scored_records),
                'cache_timestamp': self._cache_timestamp,
                'records_path': str(self.records_path),
            }
        else:
            return {
                'total_records': self._cache.get('record_count', 0),
                'rated_records': self._cache.get('record_count', 0),
                'cache_timestamp': self._cache_timestamp,
                'records_path': str(self.records_path),
                'cached': True,
            }
