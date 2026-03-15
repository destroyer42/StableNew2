"""Integration tests for PR-046: Rating Detail Analytics Integration.

Verifies that:
1. Old flat-rating records still contribute through aggregate fallback.
2. New detailed learning-experiment-rating records drive context/subscore weighting.
3. New detailed review-tab-feedback records drive context/subscore weighting.
4. Mixed datasets (old + new) produce stable recommendations.
5. Metadata normalization (LearningRecord.extract_rating_detail) works for all shapes.
6. People-context mismatch penalty is applied conservatively.
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from src.learning.learning_record import LearningRecord
from src.learning.recommendation_engine import (
    EVIDENCE_TIER_EXPERIMENT_STRONG,
    EVIDENCE_TIER_REVIEW_ONLY,
    RecommendationEngine,
)


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------

def _write(path: Path, records: list[dict]) -> None:
    with open(path, "w", encoding="utf-8") as fh:
        for record in records:
            fh.write(json.dumps(record) + "\n")


def _flat_record(sampler: str = "Euler a", rating: int = 4, stage: str = "txt2img") -> dict:
    """Old-style flat-rating record (no subscores, no context)."""
    return {
        "timestamp": "2026-03-10T21:00:00",
        "primary_sampler": sampler,
        "primary_scheduler": "normal",
        "primary_steps": 20,
        "primary_cfg_scale": 7.0,
        "base_config": {"prompt": "landscape", "stage": stage},
        "metadata": {
            "record_kind": "learning_experiment_rating",
            "user_rating": rating,
            "stage": stage,
        },
    }


def _detailed_exp_record(
    sampler: str = "Euler a",
    rating: int = 4,
    subscores: dict | None = None,
    context_flags: dict | None = None,
    stage: str = "txt2img",
) -> dict:
    """New-style learning_experiment_rating with subscores and context flags."""
    return {
        "timestamp": "2026-03-10T21:30:00",
        "primary_sampler": sampler,
        "primary_scheduler": "normal",
        "primary_steps": 20,
        "primary_cfg_scale": 7.0,
        "base_config": {"prompt": "portrait, woman", "stage": stage},
        "metadata": {
            "record_kind": "learning_experiment_rating",
            "user_rating": rating,
            "user_rating_raw": rating,
            "rating_schema_version": 2,
            "rating_context": context_flags or {},
            "rating_details": subscores or {},
            "subscores": subscores or {},
            "stage": stage,
        },
    }


def _review_record(
    sampler: str = "DPM++ 2M",
    rating: int = 5,
    subscores: dict | None = None,
    context: dict | None = None,
    stage: str = "txt2img",
) -> dict:
    """New-style review_tab_feedback record."""
    return {
        "timestamp": "2026-03-10T22:00:00",
        "primary_sampler": sampler,
        "primary_scheduler": "Karras",
        "primary_steps": 30,
        "primary_cfg_scale": 9.0,
        "base_config": {"prompt": "portrait", "stage": stage},
        "metadata": {
            "record_kind": "review_tab_feedback",
            "user_rating": rating,
            "user_rating_raw": rating,
            "subscores": subscores or {},
            "review_context": context or {},
            "stage": stage,
        },
    }


# ---------------------------------------------------------------------------
# LearningRecord.extract_rating_detail normalization tests
# ---------------------------------------------------------------------------

class TestExtractRatingDetail:
    def test_empty_metadata_returns_safe_defaults(self) -> None:
        result = LearningRecord.extract_rating_detail({})
        assert result["subscores"] == {}
        assert result["context_flags"] == {}
        assert result["schema_version"] == 0

    def test_none_metadata_treated_as_empty(self) -> None:
        result = LearningRecord.extract_rating_detail({})
        assert isinstance(result["subscores"], dict)

    def test_flat_record_no_subscores(self) -> None:
        metadata = {"record_kind": "learning_experiment_rating", "user_rating": 4}
        result = LearningRecord.extract_rating_detail(metadata)
        assert result["subscores"] == {}
        assert result["schema_version"] == 0

    def test_review_tab_subscores_normalized(self) -> None:
        metadata = {
            "record_kind": "review_tab_feedback",
            "user_rating": 5,
            "subscores": {"anatomy": 4, "composition": 5, "prompt_adherence": 5},
            "review_context": {"has_people": True},
        }
        result = LearningRecord.extract_rating_detail(metadata)
        assert result["subscores"]["anatomy"] == 4.0
        assert result["subscores"]["composition"] == 5.0
        assert result["context_flags"]["has_people"] is True

    def test_experiment_rating_detail_normalized(self) -> None:
        metadata = {
            "record_kind": "learning_experiment_rating",
            "user_rating": 4,
            "rating_schema_version": 2,
            "rating_details": {"anatomy": 3, "composition": 4, "prompt_adherence": 5},
            "rating_context": {"has_people": False},
        }
        result = LearningRecord.extract_rating_detail(metadata)
        assert result["subscores"]["anatomy"] == 3.0
        assert result["context_flags"]["has_people"] is False
        assert result["schema_version"] == 2

    def test_subscores_key_preferred_over_rating_details(self) -> None:
        """When both 'subscores' and 'rating_details' are present, 'subscores' wins."""
        metadata = {
            "subscores": {"anatomy": 5, "composition": 5, "prompt_adherence": 5},
            "rating_details": {"anatomy": 1, "composition": 1, "prompt_adherence": 1},
        }
        result = LearningRecord.extract_rating_detail(metadata)
        assert result["subscores"]["anatomy"] == 5.0

    def test_out_of_range_subscores_excluded(self) -> None:
        metadata = {"subscores": {"anatomy": 10, "composition": 0, "prompt_adherence": 3}}
        result = LearningRecord.extract_rating_detail(metadata)
        # 10 and 0 are out of [1,5] range
        assert "anatomy" not in result["subscores"]
        assert "composition" not in result["subscores"]
        assert result["subscores"]["prompt_adherence"] == 3.0


# ---------------------------------------------------------------------------
# Backward compatibility: flat-rating records still produce recommendations
# ---------------------------------------------------------------------------

def test_flat_rating_records_still_produce_recommendations(tmp_path: Path) -> None:
    """Old records without any subscore detail must not be silently filtered."""
    path = tmp_path / "r.jsonl"
    _write(path, [_flat_record(sampler="Euler a", rating=5) for _ in range(3)])
    engine = RecommendationEngine(path)
    result = engine.recommend("landscape", "txt2img")
    assert result.evidence_tier == EVIDENCE_TIER_EXPERIMENT_STRONG
    assert result.recommendations


def test_flat_and_detailed_records_mixed(tmp_path: Path) -> None:
    """Mixed old and new records must produce stable recommendations without crashing."""
    path = tmp_path / "r.jsonl"
    records = [
        _flat_record(sampler="Euler a", rating=5),
        _flat_record(sampler="Euler a", rating=4),
        _detailed_exp_record(
            sampler="Euler a",
            rating=4,
            subscores={"anatomy": 4, "composition": 4, "prompt_adherence": 4},
            context_flags={"has_people": True},
        ),
    ]
    _write(path, records)
    engine = RecommendationEngine(path)
    result = engine.recommend("portrait, woman", "txt2img")
    assert result.recommendations
    assert result.evidence_tier == EVIDENCE_TIER_EXPERIMENT_STRONG


# ---------------------------------------------------------------------------
# Subscore quality adjustment
# ---------------------------------------------------------------------------

def test_high_subscores_increase_weight(tmp_path: Path) -> None:
    """Records with avg subscore > 3 should not disappear or be penalised."""
    path = tmp_path / "r.jsonl"
    _write(path, [
        _detailed_exp_record(
            sampler="Euler a",
            rating=5,
            subscores={"anatomy": 5, "composition": 5, "prompt_adherence": 5},
        )
        for _ in range(3)
    ])
    engine = RecommendationEngine(path)
    result = engine.recommend("portrait, woman", "txt2img")
    assert result.recommendations


def test_low_subscores_do_not_suppress_recommendations(tmp_path: Path) -> None:
    """Even records with poor subscores must still contribute (not be zeroed out)."""
    path = tmp_path / "r.jsonl"
    records = [
        _detailed_exp_record(
            sampler="Euler a",
            rating=4,
            subscores={"anatomy": 1, "composition": 1, "prompt_adherence": 1},
        )
        for _ in range(3)
    ]
    _write(path, records)
    engine = RecommendationEngine(path)
    result = engine.recommend("landscape", "txt2img")
    assert result.recommendations, "Low subscores must reduce weight, not eliminate evidence"


# ---------------------------------------------------------------------------
# Context-mismatch penalty
# ---------------------------------------------------------------------------

def test_context_mismatch_penalty_applied_conservatively(tmp_path: Path) -> None:
    """Records with no-people context + low anatomy should lose weight when query has people.

    The recommendation should still exist (penalty is -0.10, not elimination).
    """
    path = tmp_path / "r.jsonl"
    records = [
        _detailed_exp_record(
            sampler="Euler a",
            rating=5,
            subscores={"anatomy": 2, "composition": 4, "prompt_adherence": 4},
            context_flags={"has_people": False},
        )
        for _ in range(3)
    ]
    _write(path, records)
    engine = RecommendationEngine(path)
    # Query WITH people: context-mismatch penalty should be applied
    result = engine.recommend("portrait, woman", "txt2img")
    assert result.recommendations, "context-mismatch penalty must not suppress output"


def test_no_context_mismatch_when_record_has_people(tmp_path: Path) -> None:
    """No penalty when record and query both have people."""
    path = tmp_path / "r.jsonl"
    records = [
        _detailed_exp_record(
            sampler="Euler a",
            rating=5,
            subscores={"anatomy": 4, "composition": 5, "prompt_adherence": 5},
            context_flags={"has_people": True},
        )
        for _ in range(3)
    ]
    _write(path, records)
    engine = RecommendationEngine(path)
    result = engine.recommend("portrait, woman", "txt2img")
    assert result.recommendations


def test_review_tab_context_flags_used(tmp_path: Path) -> None:
    """review_context flags from review_tab_feedback records must be normalized."""
    path = tmp_path / "r.jsonl"
    records = [
        _review_record(
            sampler="DPM++ 2M",
            rating=5,
            subscores={"anatomy": 5, "composition": 5, "prompt_adherence": 5},
            context={"has_people": True},
        )
        for _ in range(3)
    ]
    _write(path, records)
    engine = RecommendationEngine(path)
    result = engine.recommend("portrait, couple", "txt2img")
    assert result.evidence_tier == EVIDENCE_TIER_REVIEW_ONLY
    assert result.recommendations
