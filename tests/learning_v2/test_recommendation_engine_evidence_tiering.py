"""Regression coverage for PR-044: Recommendation evidence-tier policy.

Verifies that:
1. sparse experiment evidence no longer suppresses all recommendations
2. evidence tier and automation_eligible are set correctly
3. automation is blocked for fallback tiers
4. experiment_strong tier enables automation and ignores review noise
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from src.learning.recommendation_engine import (
    EVIDENCE_TIER_EXPERIMENT_STRONG,
    EVIDENCE_TIER_NO_EVIDENCE,
    EVIDENCE_TIER_REVIEW_ONLY,
    EVIDENCE_TIER_SPARSE_PLUS_REVIEW,
    RecommendationEngine,
)


def _write(path: Path, records: list[dict]) -> None:
    with open(path, "w", encoding="utf-8") as fh:
        for record in records:
            fh.write(json.dumps(record) + "\n")


def _exp_record(sampler: str = "Euler a", steps: int = 20, cfg: float = 7.0, rating: int = 4) -> dict:
    return {
        "timestamp": "2026-03-10T21:00:00",
        "primary_sampler": sampler,
        "primary_scheduler": "normal",
        "primary_steps": steps,
        "primary_cfg_scale": cfg,
        "base_config": {"prompt": "portrait", "stage": "txt2img"},
        "metadata": {"record_kind": "learning_experiment_rating", "user_rating": rating, "stage": "txt2img"},
    }


def _review_record(sampler: str = "DPM++ 2M", steps: int = 30, cfg: float = 9.0, rating: int = 5) -> dict:
    return {
        "timestamp": "2026-03-10T21:30:00",
        "primary_sampler": sampler,
        "primary_scheduler": "Karras",
        "primary_steps": steps,
        "primary_cfg_scale": cfg,
        "base_config": {"prompt": "portrait", "stage": "txt2img"},
        "metadata": {"record_kind": "review_tab_feedback", "user_rating": rating, "stage": "txt2img"},
    }


# ---------------------------------------------------------------------------
# no_evidence tier
# ---------------------------------------------------------------------------

def test_no_evidence_returns_empty_and_no_evidence_tier(tmp_path: Path) -> None:
    path = tmp_path / "r.jsonl"
    path.write_text("")
    engine = RecommendationEngine(path)
    result = engine.recommend("portrait", "txt2img")
    assert result.recommendations == []
    assert result.evidence_tier == EVIDENCE_TIER_NO_EVIDENCE
    assert result.automation_eligible is False


# ---------------------------------------------------------------------------
# review_only tier
# ---------------------------------------------------------------------------

def test_review_only_returns_recommendations_not_empty(tmp_path: Path) -> None:
    """review_only: review feedback alone must produce recommendations (not empty)."""
    path = tmp_path / "r.jsonl"
    _write(path, [_review_record(rating=5), _review_record(rating=4), _review_record(rating=5)])
    engine = RecommendationEngine(path)
    result = engine.recommend("portrait", "txt2img")
    assert result.evidence_tier == EVIDENCE_TIER_REVIEW_ONLY
    assert result.automation_eligible is False
    assert result.recommendations, "review-only evidence should produce recommendations"


def test_review_only_single_record_produces_recommendations(tmp_path: Path) -> None:
    path = tmp_path / "r.jsonl"
    _write(path, [_review_record(rating=4)])
    engine = RecommendationEngine(path)
    result = engine.recommend("portrait", "txt2img")
    assert result.evidence_tier == EVIDENCE_TIER_REVIEW_ONLY
    assert result.automation_eligible is False
    assert result.recommendations


# ---------------------------------------------------------------------------
# experiment_sparse_plus_review tier  (PR-044 regression fix)
# ---------------------------------------------------------------------------

def test_sparse_experiment_plus_review_not_empty(tmp_path: Path) -> None:
    """Core regression: 1 experiment record + review feedback must NOT return empty recommendations."""
    path = tmp_path / "r.jsonl"
    _write(path, [_exp_record(rating=4), _review_record(rating=5)])
    engine = RecommendationEngine(path)
    result = engine.recommend("portrait", "txt2img")
    assert result.evidence_tier == EVIDENCE_TIER_SPARSE_PLUS_REVIEW
    assert result.automation_eligible is False
    assert result.recommendations, (
        "PR-044 regression: sparse experiment + review evidence must not return empty recommendations"
    )


def test_two_experiment_records_plus_review_is_sparse_tier(tmp_path: Path) -> None:
    path = tmp_path / "r.jsonl"
    _write(path, [_exp_record(), _exp_record(rating=5), _review_record()])
    engine = RecommendationEngine(path)
    result = engine.recommend("portrait", "txt2img")
    assert result.evidence_tier == EVIDENCE_TIER_SPARSE_PLUS_REVIEW
    assert result.automation_eligible is False
    assert result.recommendations


def test_two_experiment_records_alone_is_sparse_tier(tmp_path: Path) -> None:
    """2 experiment-only records → sparse tier, automation blocked."""
    path = tmp_path / "r.jsonl"
    _write(path, [_exp_record(), _exp_record(rating=5)])
    engine = RecommendationEngine(path)
    result = engine.recommend("portrait", "txt2img")
    assert result.evidence_tier == EVIDENCE_TIER_SPARSE_PLUS_REVIEW
    assert result.automation_eligible is False
    assert result.recommendations


# ---------------------------------------------------------------------------
# experiment_strong tier
# ---------------------------------------------------------------------------

def test_three_experiment_records_gives_strong_tier(tmp_path: Path) -> None:
    path = tmp_path / "r.jsonl"
    _write(path, [_exp_record(rating=4), _exp_record(rating=5), _exp_record(rating=4)])
    engine = RecommendationEngine(path)
    result = engine.recommend("portrait", "txt2img")
    assert result.evidence_tier == EVIDENCE_TIER_EXPERIMENT_STRONG
    assert result.automation_eligible is True
    assert result.recommendations


def test_strong_tier_ignores_review_poor_ratings(tmp_path: Path) -> None:
    """3 experiment records with good ratings + 1 bad review → sampler follows experiments."""
    path = tmp_path / "r.jsonl"
    records = [
        _exp_record(sampler="Euler a", rating=5),
        _exp_record(sampler="Euler a", rating=5),
        _exp_record(sampler="Euler a", rating=5),
        _review_record(sampler="DPM++ 2M", rating=1),
    ]
    _write(path, records)
    engine = RecommendationEngine(path)
    result = engine.recommend("portrait", "txt2img")
    assert result.evidence_tier == EVIDENCE_TIER_EXPERIMENT_STRONG
    assert result.automation_eligible is True
    sampler_rec = result.recommendations and next(
        (r for r in result.recommendations if r.parameter_name == "sampler"), None
    )
    if sampler_rec:
        assert sampler_rec.recommended_value == "Euler a"


def test_strong_tier_many_records(tmp_path: Path) -> None:
    path = tmp_path / "r.jsonl"
    _write(path, [_exp_record(rating=i % 5 + 1) for i in range(10)])
    engine = RecommendationEngine(path)
    result = engine.recommend("portrait", "txt2img")
    assert result.evidence_tier == EVIDENCE_TIER_EXPERIMENT_STRONG
    assert result.automation_eligible is True


# ---------------------------------------------------------------------------
# Stage isolation (records for different stage must not bleed through)
# ---------------------------------------------------------------------------

def test_stage_isolation(tmp_path: Path) -> None:
    path = tmp_path / "r.jsonl"
    img2img_records = [
        {
            "timestamp": "2026-03-10T21:00:00",
            "primary_sampler": "Euler a",
            "primary_scheduler": "normal",
            "primary_steps": 20,
            "primary_cfg_scale": 7.0,
            "base_config": {"prompt": "portrait", "stage": "img2img"},
            "metadata": {"record_kind": "learning_experiment_rating", "user_rating": 5, "stage": "img2img"},
        }
        for _ in range(5)
    ]
    _write(path, img2img_records)
    engine = RecommendationEngine(path)
    # Querying txt2img while only img2img records exist → no_evidence
    result = engine.recommend("portrait", "txt2img")
    assert result.evidence_tier == EVIDENCE_TIER_NO_EVIDENCE
    assert result.recommendations == []


# ---------------------------------------------------------------------------
# RecommendationSet field presence (backward compat for callers)
# ---------------------------------------------------------------------------

def test_recommendation_set_has_evidence_tier_and_automation_eligible(tmp_path: Path) -> None:
    path = tmp_path / "r.jsonl"
    path.write_text("")
    engine = RecommendationEngine(path)
    result = engine.recommend("test", "txt2img")
    assert hasattr(result, "evidence_tier")
    assert hasattr(result, "automation_eligible")
