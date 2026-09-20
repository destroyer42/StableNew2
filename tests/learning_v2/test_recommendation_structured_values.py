"""RecommendationEngine must group structured (composite) controlled variant values."""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any

import pytest

from src.learning.recommendation_engine import RecommendationEngine
from src.learning.value_identity import VariantValueError, canonical_value_key, plain_value

LORA = "add-detail-xl"


def _lora(weight: float, name: str = LORA) -> dict[str, Any]:
    return {"name": name, "weight": weight}


def _controlled(
    value: Any,
    rating: int,
    *,
    variable: str = "LoRA Strength",
    experiment: str = "exp-1",
    proven: bool = True,
) -> dict[str, Any]:
    frozen: dict[str, Any] = {
        "snapshot": {},
        "executed_config": {"lora_override": value} if isinstance(value, dict) else {},
        "controlled_evidence_valid": True,
    }
    if proven:
        frozen["variable_validation_reason"] = "valid"
    return {
        "timestamp": "2026-09-20T12:00:00",
        "primary_sampler": "Euler a",
        "primary_scheduler": "normal",
        "primary_steps": 8,
        "primary_cfg_scale": 7.0,
        "base_config": {},
        "metadata": {
            "record_kind": "learning_experiment_rating",
            "experiment_id": experiment,
            "experiment_name": "structured values",
            "variable_under_test": variable,
            "variant_value": value,
            "user_rating": rating,
            "frozen_experiment": frozen,
        },
    }


def _engine(tmp_path: Path, records: list[dict[str, Any]]) -> RecommendationEngine:
    path = tmp_path / "learning_records.jsonl"
    path.write_text("\n".join(json.dumps(r) for r in records) + "\n", encoding="utf-8")
    return RecommendationEngine(path)


def _by_name(engine: RecommendationEngine) -> dict[str, Any]:
    result = engine.recommend("portrait of a warrior", "txt2img")
    return {rec.parameter_name: rec for rec in result.recommendations}


def test_scalar_variant_values_group_exactly_as_before(tmp_path: Path) -> None:
    records = [_controlled(5.0, 2, variable="CFG Scale"), _controlled(7.0, 5, variable="CFG Scale")]
    recs = _by_name(_engine(tmp_path, records))
    assert set(recs) == {"cfg_scale"}
    assert recs["cfg_scale"].recommended_value == 7.0 and recs["cfg_scale"].sample_count == 1


def test_lora_strength_values_do_not_raise_and_return_the_structured_value(tmp_path: Path) -> None:
    records = [_controlled(_lora(0.0), 3), _controlled(_lora(1.0), 4), _controlled(_lora(2.0), 5)]
    recs = _by_name(_engine(tmp_path, records))
    best = recs["lora_strength"].recommended_value
    assert best == _lora(2.0) and type(best) is dict  # meaningful data, not an opaque key


def test_three_weights_for_one_lora_stay_three_distinct_groups(tmp_path: Path) -> None:
    records = [
        _controlled(_lora(0.0), 1),
        _controlled(_lora(0.0), 1),
        _controlled(_lora(1.0), 5),
        _controlled(_lora(1.0), 5),
        _controlled(_lora(2.0), 3),
    ]
    rec = _by_name(_engine(tmp_path, records))["lora_strength"]
    # Merged groups would have averaged these ratings together.
    assert rec.recommended_value == _lora(1.0)
    assert (rec.sample_count, rec.mean_rating) == (2, 5.0)


def test_same_weight_for_different_loras_does_not_collide(tmp_path: Path) -> None:
    records = [
        _controlled(_lora(1.0, "lora-a"), 5),
        _controlled(_lora(1.0, "lora-a"), 5),
        _controlled(_lora(1.0, "lora-b"), 1),
        _controlled(_lora(1.0, "lora-b"), 1),
    ]
    rec = _by_name(_engine(tmp_path, records))["lora_strength"]
    assert rec.recommended_value == _lora(1.0, "lora-a")
    assert (rec.sample_count, rec.mean_rating) == (2, 5.0)


def test_mapping_insertion_order_does_not_create_duplicate_groups(tmp_path: Path) -> None:
    reordered = {"weight": 1.0, "name": LORA}
    records = [_controlled(_lora(1.0), 4), _controlled(reordered, 5)]
    rec = _by_name(_engine(tmp_path, records))["lora_strength"]
    assert rec.sample_count == 2 and rec.mean_rating == 4.5


def test_nested_json_like_values_are_canonicalized_deterministically(tmp_path: Path) -> None:
    first = {"name": LORA, "weight": 1.0, "extra": {"tags": ["a", "b"], "n": [1, 2]}}
    second = {"extra": {"n": [1, 2], "tags": ["a", "b"]}, "weight": 1, "name": LORA}
    other = {"name": LORA, "weight": 1.0, "extra": {"tags": ["b", "a"], "n": [1, 2]}}
    assert canonical_value_key(first) == canonical_value_key(second)  # 1 == 1.0, key order free
    assert canonical_value_key(first) != canonical_value_key(other)  # list order is meaningful
    rec = _by_name(_engine(tmp_path, [_controlled(first, 4), _controlled(second, 5)]))
    assert rec["lora_strength"].sample_count == 2
    assert rec["lora_strength"].recommended_value == first  # first-seen semantic value


def test_unsupported_values_raise_a_controlled_error_and_are_skipped(
    tmp_path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    with pytest.raises(VariantValueError):
        canonical_value_key({"weight": {1, 2}})
    with pytest.raises(VariantValueError):
        canonical_value_key({"weight": float("nan")})
    engine = _engine(tmp_path, [_controlled(_lora(1.0), 4)])
    scored = engine._score_records(engine._load_records())
    poisoned = {**scored[0], "variant_value": {"weight": {1, 2}}}
    with caplog.at_level(logging.WARNING):
        result = engine._compute_optimal_settings([scored[0], poisoned], {}, "prompt")
    assert result["lora_strength"].sample_count == 1  # the bad record was skipped
    assert "Skipping lora_strength recommendation value" in caplog.text


def test_fixed_context_never_becomes_a_recommendation(tmp_path: Path) -> None:
    records = [_controlled(_lora(w), r) for w, r in ((0.0, 3), (1.0, 4), (2.0, 5))]
    assert set(_by_name(_engine(tmp_path, records))) == {"lora_strength"}


def test_historical_lora_ratings_without_executed_proof_are_not_evidence(tmp_path: Path) -> None:
    records = [_controlled(_lora(w), r, proven=False) for w, r in ((1.0, 4), (2.0, 5))]
    assert _by_name(_engine(tmp_path, records)) == {}


def test_scalar_keys_are_unchanged_and_composites_never_equal_scalars() -> None:
    assert [canonical_value_key(v) for v in (7, 7.5, "Euler a", True, None)] == [
        7,
        7.5,
        "Euler a",
        True,
        None,
    ]
    assert canonical_value_key(_lora(1.0)) != canonical_value_key([_lora(1.0)])
    assert canonical_value_key(_lora(1.0)) != canonical_value_key("composite")
    assert hash(canonical_value_key(_lora(1.0))) == hash(canonical_value_key(dict(_lora(1.0))))
    assert plain_value({"a": (1, {"b": [2]})}) == {"a": [1, {"b": [2]}]}
