"""Learning analytics contract tests — PR-055.

Purpose: Pin the stable public API surface of the learning analytics subsystem.
These tests are intentionally *not* integration tests — they document the
contracts of individual classes and constants in isolation so that:

1. Any rename, field removal, or semantic change immediately shows up here.
2. The suite can be read as a reference for what the API guarantees.

For integration-level evidence-tiering and rating-detail tests, see:
- tests/learning_v2/test_recommendation_engine_evidence_tiering.py
- tests/learning_v2/test_recommendation_engine_rating_detail_integration.py
"""

from __future__ import annotations

from dataclasses import fields as dataclass_fields
from typing import Any

import pytest

from src.learning.learning_record import LearningRecord
from src.learning.recommendation_engine import (
    EVIDENCE_TIER_EXPERIMENT_STRONG,
    EVIDENCE_TIER_NO_EVIDENCE,
    EVIDENCE_TIER_REVIEW_ONLY,
    EVIDENCE_TIER_SPARSE_PLUS_REVIEW,
    ParameterRecommendation,
    RecommendationSet,
)


# ---------------------------------------------------------------------------
# 1. Evidence-tier constant contract
#    These string values are used in JSONL records on disk — changing them is a
#    breaking migration.  Any rename MUST be detected here immediately.
# ---------------------------------------------------------------------------


class TestEvidenceTierConstants:

    def test_strong_tier_value(self):
        assert EVIDENCE_TIER_EXPERIMENT_STRONG == "experiment_strong"

    def test_sparse_plus_review_value(self):
        assert EVIDENCE_TIER_SPARSE_PLUS_REVIEW == "experiment_sparse_plus_review"

    def test_review_only_value(self):
        assert EVIDENCE_TIER_REVIEW_ONLY == "review_only"

    def test_no_evidence_value(self):
        assert EVIDENCE_TIER_NO_EVIDENCE == "no_evidence"

    def test_all_four_tiers_are_distinct(self):
        tiers = {
            EVIDENCE_TIER_EXPERIMENT_STRONG,
            EVIDENCE_TIER_SPARSE_PLUS_REVIEW,
            EVIDENCE_TIER_REVIEW_ONLY,
            EVIDENCE_TIER_NO_EVIDENCE,
        }
        assert len(tiers) == 4


# ---------------------------------------------------------------------------
# 2. RecommendationSet dataclass contract
# ---------------------------------------------------------------------------


class TestRecommendationSetContract:

    def _make_set(self, **overrides: Any) -> RecommendationSet:
        defaults: dict[str, Any] = {
            "prompt_text": "a photograph",
            "stage": "base",
            "timestamp": 1000.0,
        }
        defaults.update(overrides)
        return RecommendationSet(**defaults)

    # Field existence
    def test_required_fields_exist(self):
        rs = self._make_set()
        assert hasattr(rs, "prompt_text")
        assert hasattr(rs, "stage")
        assert hasattr(rs, "timestamp")

    def test_optional_fields_have_defaults(self):
        rs = self._make_set()
        assert rs.recommendations == []
        assert rs.evidence_tier == EVIDENCE_TIER_NO_EVIDENCE
        assert rs.automation_eligible is False

    # evidence_tier → automation_eligible semantic contract
    def test_strong_tier_can_have_automation_eligible_true(self):
        rs = self._make_set(
            evidence_tier=EVIDENCE_TIER_EXPERIMENT_STRONG,
            automation_eligible=True,
        )
        assert rs.automation_eligible is True

    def test_non_strong_tiers_have_automation_eligible_false_by_default(self):
        """Only EXPERIMENT_STRONG drives automation_eligible=True in the engine."""
        for tier in (
            EVIDENCE_TIER_SPARSE_PLUS_REVIEW,
            EVIDENCE_TIER_REVIEW_ONLY,
            EVIDENCE_TIER_NO_EVIDENCE,
        ):
            rs = self._make_set(evidence_tier=tier)
            assert rs.automation_eligible is False, (
                f"Expected automation_eligible=False for tier={tier!r}"
            )

    # get_best_for_parameter contract
    def test_get_best_for_parameter_returns_none_when_empty(self):
        rs = self._make_set()
        assert rs.get_best_for_parameter("cfg_scale") is None

    def test_get_best_for_parameter_returns_highest_confidence(self):
        low = ParameterRecommendation(
            parameter_name="cfg_scale",
            recommended_value=7.0,
            confidence_score=0.4,
            sample_count=1,
            mean_rating=3.0,
            rating_stddev=0.0,
        )
        high = ParameterRecommendation(
            parameter_name="cfg_scale",
            recommended_value=9.0,
            confidence_score=0.9,
            sample_count=5,
            mean_rating=4.5,
            rating_stddev=0.2,
        )
        rs = self._make_set(recommendations=[low, high])
        best = rs.get_best_for_parameter("cfg_scale")
        assert best is high

    def test_get_best_for_parameter_returns_none_for_unknown_param(self):
        rec = ParameterRecommendation(
            parameter_name="cfg_scale",
            recommended_value=7.0,
            confidence_score=0.8,
            sample_count=3,
            mean_rating=4.0,
            rating_stddev=0.1,
        )
        rs = self._make_set(recommendations=[rec])
        assert rs.get_best_for_parameter("sampler") is None

    # to_ui_format contract
    def test_to_ui_format_empty_returns_empty_list(self):
        rs = self._make_set()
        assert rs.to_ui_format() == []

    def test_to_ui_format_returns_list_of_dicts(self):
        rec = ParameterRecommendation(
            parameter_name="steps",
            recommended_value=20,
            confidence_score=0.75,
            sample_count=2,
            mean_rating=4.0,
            rating_stddev=0.5,
        )
        rs = self._make_set(recommendations=[rec])
        result = rs.to_ui_format()
        assert isinstance(result, list)
        assert len(result) == 1
        assert isinstance(result[0], dict)


# ---------------------------------------------------------------------------
# 3. ParameterRecommendation.to_dict() contract
# ---------------------------------------------------------------------------


class TestParameterRecommendationContract:

    @pytest.fixture
    def rec(self) -> ParameterRecommendation:
        return ParameterRecommendation(
            parameter_name="cfg_scale",
            recommended_value=7.5,
            confidence_score=0.82,
            sample_count=4,
            mean_rating=4.2,
            rating_stddev=0.3,
            confidence_rationale="High experimental agreement",
            context_key="portrait",
        )

    def test_to_dict_has_required_keys(self, rec):
        d = rec.to_dict()
        required = {"parameter", "value", "confidence", "samples", "mean_rating", "stddev"}
        assert required.issubset(d.keys())

    def test_to_dict_parameter_matches(self, rec):
        assert rec.to_dict()["parameter"] == "cfg_scale"

    def test_to_dict_value_matches(self, rec):
        assert rec.to_dict()["value"] == 7.5

    def test_to_dict_confidence_matches(self, rec):
        assert rec.to_dict()["confidence"] == 0.82

    def test_to_dict_includes_rationale_and_context(self, rec):
        d = rec.to_dict()
        assert d["rationale"] == "High experimental agreement"
        assert d["context"] == "portrait"

    def test_to_dict_optional_fields_default_empty_string(self):
        rec = ParameterRecommendation(
            parameter_name="steps",
            recommended_value=20,
            confidence_score=0.5,
            sample_count=1,
            mean_rating=3.0,
            rating_stddev=0.0,
        )
        d = rec.to_dict()
        assert d["rationale"] == ""
        assert d["context"] == ""


# ---------------------------------------------------------------------------
# 4. LearningRecord.extract_rating_detail static method contract
# ---------------------------------------------------------------------------


class TestExtractRatingDetailContract:

    # ----- Null / empty inputs -----

    def test_empty_dict_returns_safe_defaults(self):
        result = LearningRecord.extract_rating_detail({})
        assert result == {"subscores": {}, "context_flags": {}, "schema_version": 0}

    def test_none_treated_as_empty(self):
        result = LearningRecord.extract_rating_detail(None)  # type: ignore[arg-type]
        assert result == {"subscores": {}, "context_flags": {}, "schema_version": 0}

    # ----- Schema version -----

    def test_schema_version_extracted(self):
        meta = {"rating_schema_version": 2, "subscores": {"anatomy": 4.0}}
        result = LearningRecord.extract_rating_detail(meta)
        assert result["schema_version"] == 2

    def test_schema_version_defaults_to_zero(self):
        meta = {"subscores": {"anatomy": 4.0}}
        result = LearningRecord.extract_rating_detail(meta)
        assert result["schema_version"] == 0

    # ----- Review-tab shape -----

    def test_review_tab_subscores_key_used(self):
        meta = {
            "subscores": {"anatomy": 4.0, "composition": 3.5, "prompt_adherence": 5.0},
            "review_context": {"has_people": True},
        }
        result = LearningRecord.extract_rating_detail(meta)
        assert result["subscores"] == {
            "anatomy": 4.0,
            "composition": 3.5,
            "prompt_adherence": 5.0,
        }
        assert result["context_flags"] == {"has_people": True}

    # ----- Experiment shape -----

    def test_experiment_rating_details_key_used(self):
        meta = {
            "rating_details": {"anatomy": 4.5, "composition": 4.0},
            "rating_context": {"lighting": "natural"},
        }
        result = LearningRecord.extract_rating_detail(meta)
        assert result["subscores"]["anatomy"] == 4.5
        assert result["subscores"]["composition"] == 4.0
        assert result["context_flags"] == {"lighting": "natural"}

    # ----- Range enforcement -----

    def test_subscore_below_range_excluded(self):
        meta = {"subscores": {"anatomy": 0.9, "composition": 3.0}}
        result = LearningRecord.extract_rating_detail(meta)
        assert "anatomy" not in result["subscores"]
        assert "composition" in result["subscores"]

    def test_subscore_above_range_excluded(self):
        meta = {"subscores": {"anatomy": 5.1, "composition": 3.0}}
        result = LearningRecord.extract_rating_detail(meta)
        assert "anatomy" not in result["subscores"]
        assert "composition" in result["subscores"]

    def test_subscore_boundary_values_included(self):
        meta = {"subscores": {"anatomy": 1.0, "composition": 5.0}}
        result = LearningRecord.extract_rating_detail(meta)
        assert result["subscores"]["anatomy"] == 1.0
        assert result["subscores"]["composition"] == 5.0

    def test_non_numeric_subscores_excluded_silently(self):
        meta = {"subscores": {"anatomy": "bad", "composition": 3.0}}
        result = LearningRecord.extract_rating_detail(meta)
        assert "anatomy" not in result["subscores"]
        assert result["subscores"]["composition"] == 3.0

    # ----- Key priority: 'subscores' beats 'rating_details' -----

    def test_subscores_preferred_over_rating_details(self):
        meta = {
            "subscores": {"anatomy": 4.0},
            "rating_details": {"anatomy": 2.0},
        }
        result = LearningRecord.extract_rating_detail(meta)
        assert result["subscores"]["anatomy"] == 4.0
