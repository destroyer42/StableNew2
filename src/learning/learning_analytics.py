"""Analytics engine for learning experiments.

PR-LEARN-010: Provides statistical analysis and trend detection.
"""
from __future__ import annotations

import json
from collections import Counter, defaultdict
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

from src.learning.learning_record import LearningRecordWriter


@dataclass
class ParameterStats:
    """Statistics for a parameter value."""

    parameter_name: str
    value: Any
    rating_count: int
    mean_rating: float
    median_rating: float
    std_dev: float
    min_rating: int
    max_rating: int


@dataclass
class ExperimentSummary:
    """Summary of an experiment's results."""

    experiment_id: str
    parameter_name: str
    total_variants: int
    total_ratings: int
    best_value: Any
    best_rating: float
    worst_value: Any
    worst_rating: float
    completion_rate: float


@dataclass
class AnalyticsSummary:
    """Complete analytics summary."""

    total_experiments: int
    total_ratings: int
    avg_rating: float
    experiments: list[ExperimentSummary]
    parameter_stats: list[ParameterStats]
    evidence_class_counts: dict[str, int] = field(default_factory=dict)
    decision_counts: dict[str, int] = field(default_factory=dict)
    reason_tag_counts: dict[str, int] = field(default_factory=dict)


class LearningAnalytics:
    """Compute analytics from learning records."""

    def __init__(self, record_writer: LearningRecordWriter):
        self.record_writer = record_writer

    def get_experiment_summary(self, experiment_id: str) -> ExperimentSummary | None:
        """Get summary statistics for a specific experiment."""
        records = [
            record
            for record in self._read_all_records()
            if self._extract_experiment_identifier(record) == experiment_id
        ]
        if not records:
            return None

        value_ratings: dict[Any, list[int]] = {}
        parameter_name = ""
        for record in records:
            metadata = record.get("metadata", {}) or {}
            parameter_name = parameter_name or str(
                metadata.get("variable_under_test")
                or metadata.get("advancement_decision")
                or ""
            )
            rating = metadata.get("user_rating")
            if rating is None:
                continue
            try:
                rating_int = int(round(float(rating)))
            except (TypeError, ValueError):
                continue
            group_value = metadata.get("variant_value")
            if group_value is None:
                group_value = metadata.get("image_path") or record.get("run_id")
            value_ratings.setdefault(group_value, []).append(rating_int)

        if not value_ratings:
            return None

        # Compute statistics
        all_ratings = [r for rs in value_ratings.values() for r in rs]
        avg_rating = sum(all_ratings) / len(all_ratings) if all_ratings else 0

        # Find best and worst
        value_avgs = {
            val: sum(ratings) / len(ratings) for val, ratings in value_ratings.items()
        }
        best_value = max(value_avgs, key=value_avgs.get, default=None)
        worst_value = min(value_avgs, key=value_avgs.get, default=None)

        return ExperimentSummary(
            experiment_id=experiment_id,
            parameter_name=parameter_name,
            total_variants=len(value_ratings),
            total_ratings=len(all_ratings),
            best_value=best_value,
            best_rating=value_avgs.get(best_value, 0) if best_value else 0,
            worst_value=worst_value,
            worst_rating=value_avgs.get(worst_value, 0) if worst_value else 0,
            completion_rate=1.0,  # Would calculate from planned vs actual
        )

    def get_parameter_statistics(self, parameter_name: str) -> list[ParameterStats]:
        """Get statistics for all values of a parameter across experiments."""
        # This would aggregate across all experiments
        # For now, return empty list as stub
        return []

    def get_overall_summary(self) -> AnalyticsSummary:
        """Get overall analytics summary."""
        # Read all records
        all_records = self._read_all_records()

        experiment_ids = {
            experiment_id
            for record in all_records
            if (experiment_id := self._extract_experiment_identifier(record))
        }

        # Count total ratings
        total_ratings = sum(
            1
            for r in all_records
            if r.get("metadata", {}).get("user_rating") is not None
        )

        # Calculate average rating
        ratings = [
            r.get("metadata", {}).get("user_rating", 0)
            for r in all_records
            if r.get("metadata", {}).get("user_rating") is not None
        ]
        avg_rating = sum(ratings) / len(ratings) if ratings else 0

        # Get summaries for each experiment
        experiment_summaries = []
        for exp_id in experiment_ids:
            summary = self.get_experiment_summary(exp_id)
            if summary:
                experiment_summaries.append(summary)

        evidence_counts: Counter[str] = Counter()
        decision_counts: Counter[str] = Counter()
        reason_tag_counts: Counter[str] = Counter()
        for record in all_records:
            metadata = record.get("metadata", {}) or {}
            evidence_class = str(metadata.get("evidence_class") or "").strip()
            if evidence_class:
                evidence_counts[evidence_class] += 1
            decision = str(metadata.get("advancement_decision") or "").strip()
            if decision:
                decision_counts[decision] += 1
            for tag in list(metadata.get("reason_tags") or metadata.get("selection_reason_tags") or []):
                clean = str(tag or "").strip()
                if clean:
                    reason_tag_counts[clean] += 1

        return AnalyticsSummary(
            total_experiments=len(experiment_ids),
            total_ratings=total_ratings,
            avg_rating=avg_rating,
            experiments=experiment_summaries,
            parameter_stats=[],
            evidence_class_counts=dict(evidence_counts),
            decision_counts=dict(decision_counts),
            reason_tag_counts=dict(reason_tag_counts),
        )

    @staticmethod
    def _extract_experiment_identifier(record: dict[str, Any]) -> str:
        metadata = record.get("metadata", {}) or {}
        if not isinstance(metadata, dict):
            return ""
        for key in ("experiment_name", "curation_workflow_id"):
            value = str(metadata.get(key) or "").strip()
            if value:
                return value
        return ""

    def _read_all_records(self) -> list[dict[str, Any]]:
        """Read all records from the JSONL file."""
        import json

        records: list[dict[str, Any]] = []
        records_path = self.record_writer.records_path

        if not records_path.exists():
            return records

        try:
            with open(records_path, encoding="utf-8") as f:
                for line in f:
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        record = json.loads(line)
                        records.append(record)
                    except json.JSONDecodeError:
                        continue
        except Exception:
            pass

        return records

    def export_to_json(self, output_path: Path) -> None:
        """Export analytics to JSON file."""
        summary = self.get_overall_summary()
        with open(output_path, 'w') as f:
            json.dump(asdict(summary), f, indent=2, default=str)

    def export_to_csv(self, output_path: Path) -> None:
        """Export analytics to CSV file."""
        import csv

        summary = self.get_overall_summary()

        with open(output_path, 'w', newline='') as f:
            writer = csv.writer(f)
            writer.writerow([
                "Experiment ID",
                "Parameter",
                "Total Variants",
                "Total Ratings",
                "Best Value",
                "Best Rating",
                "Worst Value",
                "Worst Rating",
            ])

            for exp in summary.experiments:
                writer.writerow([
                    exp.experiment_id,
                    exp.parameter_name,
                    exp.total_variants,
                    exp.total_ratings,
                    exp.best_value,
                    exp.best_rating,
                    exp.worst_value,
                    exp.worst_rating,
                ])
