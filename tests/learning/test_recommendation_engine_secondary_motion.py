from __future__ import annotations

import json
from pathlib import Path

from src.learning.recommendation_engine import RecommendationEngine


def _write_records(path: Path, records: list[dict]) -> None:
    with open(path, "w", encoding="utf-8") as handle:
        for row in records:
            handle.write(json.dumps(row) + "\n")


def _motion_record(
    *,
    run_id: str,
    rating: int,
    sampler: str,
    backend_id: str,
    status: str,
    policy_id: str = "workflow_motion_v1",
    application_path: str = "video_reencode_worker",
) -> dict:
    return {
        "run_id": run_id,
        "timestamp": "2026-03-08T12:00:00",
        "base_config": {"prompt": "portrait studio", "stage": "video_workflow", "model": "m.safetensors"},
        "variant_configs": [],
        "randomizer_mode": "",
        "randomizer_plan_size": 0,
        "primary_model": "m.safetensors",
        "primary_sampler": sampler,
        "primary_scheduler": "karras",
        "primary_steps": 20,
        "primary_cfg_scale": 7.0,
        "metadata": {
            "user_rating": rating,
            "stage": "video_workflow",
            "secondary_motion": {
                "backend_id": backend_id,
                "enabled": True,
                "status": status,
                "policy_id": policy_id,
                "application_path": application_path,
                "backend_mode": "apply_shared_postprocess_candidate",
                "intent_mode": "apply",
                "applied_motion_strength": 0.25 if status == "applied" else 0.0,
                "quality_risk_score": 0.15 if status == "applied" else 0.0,
            },
        },
    }


def test_recommendation_engine_stratifies_by_secondary_motion_backend(tmp_path: Path) -> None:
    records_path = tmp_path / "learning_records.jsonl"
    _write_records(
        records_path,
        [
            _motion_record(run_id="comfy-a", rating=5, sampler="Euler a", backend_id="comfy", status="applied"),
            _motion_record(run_id="comfy-b", rating=4, sampler="Euler a", backend_id="comfy", status="applied"),
            _motion_record(run_id="animatediff-a", rating=5, sampler="DPM++ 2M", backend_id="animatediff", status="applied"),
            _motion_record(run_id="animatediff-b", rating=5, sampler="DPM++ 2M", backend_id="animatediff", status="applied"),
        ],
    )

    engine = RecommendationEngine(records_path)
    recs = engine.recommend(
        "portrait studio",
        "video_workflow",
        secondary_motion_context={
            "backend_id": "comfy",
            "status": "applied",
            "policy_id": "workflow_motion_v1",
            "application_path": "video_reencode_worker",
            "backend_mode": "apply_shared_postprocess_candidate",
            "intent_mode": "apply",
        },
    )

    best = recs.get_best_for_parameter("sampler")
    assert best is not None
    assert best.recommended_value == "Euler a"
    assert "comfy" in best.context_key


def test_recommendation_engine_excludes_unavailable_motion_runs_from_positive_tuning(tmp_path: Path) -> None:
    records_path = tmp_path / "learning_records.jsonl"
    _write_records(
        records_path,
        [
            _motion_record(run_id="applied", rating=3, sampler="Euler a", backend_id="comfy", status="applied"),
            _motion_record(run_id="unavailable-a", rating=5, sampler="DPM++ 2M", backend_id="comfy", status="unavailable"),
            _motion_record(run_id="unavailable-b", rating=5, sampler="DPM++ 2M", backend_id="comfy", status="unavailable"),
        ],
    )

    engine = RecommendationEngine(records_path)
    recs = engine.recommend(
        "portrait studio",
        "video_workflow",
        secondary_motion_context={
            "backend_id": "comfy",
            "status": "applied",
            "policy_id": "workflow_motion_v1",
            "application_path": "video_reencode_worker",
            "backend_mode": "apply_shared_postprocess_candidate",
            "intent_mode": "apply",
        },
    )

    best = recs.get_best_for_parameter("sampler")
    assert best is not None
    assert best.recommended_value == "Euler a"