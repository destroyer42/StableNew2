from __future__ import annotations

import json
from pathlib import Path

from src.learning.recommendation_engine import RecommendationEngine


def _write(path: Path, records: list[dict]) -> None:
    with open(path, "w", encoding="utf-8") as handle:
        for record in records:
            handle.write(json.dumps(record) + "\n")


def _record(*, sampler: str, rating: int, policy_id: str, scale_band: str) -> dict:
    return {
        "timestamp": "2026-03-20T12:00:00",
        "primary_sampler": sampler,
        "primary_scheduler": "normal",
        "primary_steps": 20,
        "primary_cfg_scale": 7.0,
        "base_config": {"prompt": "portrait woman", "stage": "txt2img"},
        "metadata": {
            "record_kind": "learning_experiment_rating",
            "user_rating": rating,
            "stage": "txt2img",
            "adaptive_refinement": {
                "mode": "full",
                "policy_id": policy_id,
                "policy_ids": [policy_id],
                "scale_band": scale_band,
                "prompt_intent_band": "portrait",
                "has_prompt_patch": True,
                "has_applied_overrides": True,
            },
        },
    }


def test_recommendation_engine_prefers_matching_refinement_context(tmp_path: Path) -> None:
    path = tmp_path / "records.jsonl"
    _write(
        path,
        [
            _record(sampler="Euler a", rating=4, policy_id="full_upscale_detail_v1", scale_band="small"),
            _record(sampler="Euler a", rating=5, policy_id="full_upscale_detail_v1", scale_band="small"),
            _record(sampler="Euler a", rating=4, policy_id="full_upscale_detail_v1", scale_band="small"),
            _record(sampler="DPM++ 2M", rating=5, policy_id="adetailer_micro_face_v1", scale_band="large"),
            _record(sampler="DPM++ 2M", rating=5, policy_id="adetailer_micro_face_v1", scale_band="large"),
            _record(sampler="DPM++ 2M", rating=5, policy_id="adetailer_micro_face_v1", scale_band="large"),
        ],
    )

    engine = RecommendationEngine(path)
    result = engine.recommend(
        "portrait woman",
        "txt2img",
        refinement_context={
            "mode": "full",
            "policy_id": "full_upscale_detail_v1",
            "scale_band": "small",
            "prompt_intent_band": "portrait",
        },
    )

    best = result.get_best_for_parameter("sampler")
    assert best is not None
    assert best.recommended_value == "Euler a"
    assert "refinement-policy-match" in best.confidence_rationale or "context=" in best.confidence_rationale
