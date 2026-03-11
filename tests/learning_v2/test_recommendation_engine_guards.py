from __future__ import annotations

import json
from pathlib import Path

from src.learning.recommendation_engine import RecommendationEngine


def _write_records(path: Path, records: list[dict]) -> None:
    with open(path, "w", encoding="utf-8") as handle:
        for record in records:
            handle.write(json.dumps(record) + "\n")


def test_recommendation_engine_requires_sufficient_learning_records(tmp_path: Path) -> None:
    path = tmp_path / "records.jsonl"
    _write_records(
        path,
        [
            {
                "timestamp": "2026-03-10T21:00:00",
                "primary_sampler": "Euler a",
                "primary_scheduler": "normal",
                "primary_steps": 20,
                "primary_cfg_scale": 7.0,
                "base_config": {"prompt": "portrait", "stage": "txt2img"},
                "metadata": {"record_kind": "learning_experiment_rating", "user_rating": 4},
            },
            {
                "timestamp": "2026-03-10T21:01:00",
                "primary_sampler": "Euler a",
                "primary_scheduler": "normal",
                "primary_steps": 24,
                "primary_cfg_scale": 7.5,
                "base_config": {"prompt": "portrait", "stage": "txt2img"},
                "metadata": {"record_kind": "review_tab_feedback", "user_rating": 5},
            },
        ],
    )

    engine = RecommendationEngine(path)
    result = engine.recommend("portrait", "txt2img")

    assert result.recommendations == []


def test_recommendation_engine_ignores_review_tab_feedback_for_learning_recommendations(tmp_path: Path) -> None:
    path = tmp_path / "records.jsonl"
    records = []
    for idx, rating in enumerate((4, 5, 5), start=1):
        records.append(
            {
                "timestamp": f"2026-03-10T21:0{idx}:00",
                "primary_sampler": "Euler a",
                "primary_scheduler": "normal",
                "primary_steps": 20,
                "primary_cfg_scale": 7.0,
                "base_config": {"prompt": "portrait", "stage": "txt2img"},
                "metadata": {"record_kind": "learning_experiment_rating", "user_rating": rating},
            }
        )
    records.append(
        {
            "timestamp": "2026-03-10T21:10:00",
            "primary_sampler": "DPM++ 2M",
            "primary_scheduler": "Karras",
            "primary_steps": 32,
            "primary_cfg_scale": 9.0,
            "base_config": {"prompt": "portrait", "stage": "txt2img"},
            "metadata": {"record_kind": "review_tab_feedback", "user_rating": 1},
        }
    )
    _write_records(path, records)

    engine = RecommendationEngine(path)
    result = engine.recommend("portrait", "txt2img")

    assert result.recommendations
    assert all(rec.parameter_name != "sampler" or rec.recommended_value == "Euler a" for rec in result.recommendations)
