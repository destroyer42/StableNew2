from __future__ import annotations

import json
from pathlib import Path

from src.learning.recommendation_engine import RecommendationEngine


def _record(
    *,
    rating: int,
    stage: str,
    sampler: str,
    prompt: str,
    model: str = "m.safetensors",
) -> dict:
    return {
        "run_id": f"{stage}-{sampler}-{rating}",
        "timestamp": "2026-03-08T12:00:00",
        "base_config": {"prompt": prompt, "stage": stage, "model": model},
        "variant_configs": [],
        "randomizer_mode": "",
        "randomizer_plan_size": 0,
        "primary_model": model,
        "primary_sampler": sampler,
        "primary_scheduler": "karras",
        "primary_steps": 20,
        "primary_cfg_scale": 7.0,
        "metadata": {"user_rating": rating, "stage": stage},
    }


def _write_records(path: Path, records: list[dict]) -> None:
    with open(path, "w", encoding="utf-8") as handle:
        for row in records:
            handle.write(json.dumps(row) + "\n")


def test_recommendations_differ_by_stage_context(tmp_path) -> None:
    records_path = tmp_path / "learning_records.jsonl"
    _write_records(
        records_path,
        [
            _record(rating=5, stage="txt2img", sampler="Euler a", prompt="portrait studio"),
            _record(rating=4, stage="txt2img", sampler="Euler a", prompt="portrait studio"),
            _record(rating=5, stage="upscale", sampler="DPM++ 2M", prompt="portrait studio"),
            _record(rating=4, stage="upscale", sampler="DPM++ 2M", prompt="portrait studio"),
        ],
    )
    engine = RecommendationEngine(records_path)

    txt2img = engine.recommend("portrait studio", "txt2img")
    upscale = engine.recommend("portrait studio", "upscale")

    txt2img_sampler = txt2img.get_best_for_parameter("sampler")
    upscale_sampler = upscale.get_best_for_parameter("sampler")
    assert txt2img_sampler is not None
    assert upscale_sampler is not None
    assert txt2img_sampler.recommended_value != upscale_sampler.recommended_value


def test_confidence_rationale_is_exposed(tmp_path) -> None:
    records_path = tmp_path / "learning_records.jsonl"
    _write_records(
        records_path,
        [
            _record(rating=5, stage="txt2img", sampler="Euler a", prompt="hero portrait"),
            _record(rating=5, stage="txt2img", sampler="Euler a", prompt="hero portrait"),
            _record(rating=4, stage="txt2img", sampler="Euler a", prompt="hero portrait"),
        ],
    )
    engine = RecommendationEngine(records_path)

    recs = engine.recommend("hero portrait", "txt2img")
    best = recs.get_best_for_parameter("sampler")
    assert best is not None
    assert "samples=" in best.confidence_rationale
    assert "context=" in best.confidence_rationale
    assert best.context_key.startswith("txt2img|")


def test_recommendations_stratify_by_secondary_motion_context(tmp_path) -> None:
    records_path = tmp_path / "learning_records.jsonl"
    _write_records(
        records_path,
        [
            {
                **_record(rating=5, stage="video_workflow", sampler="Euler a", prompt="portrait studio"),
                "metadata": {
                    "user_rating": 5,
                    "stage": "video_workflow",
                    "secondary_motion": {
                        "backend_id": "comfy",
                        "enabled": True,
                        "status": "applied",
                        "policy_id": "workflow_motion_v1",
                        "application_path": "video_reencode_worker",
                        "backend_mode": "apply_shared_postprocess_candidate",
                        "intent_mode": "apply",
                    },
                },
            },
            {
                **_record(rating=2, stage="video_workflow", sampler="DPM++ 2M", prompt="portrait studio"),
                "metadata": {
                    "user_rating": 2,
                    "stage": "video_workflow",
                    "secondary_motion": {
                        "backend_id": "animatediff",
                        "enabled": True,
                        "status": "applied",
                        "policy_id": "other_motion_v1",
                        "application_path": "frame_directory_worker",
                        "backend_mode": "apply_shared_postprocess_candidate",
                        "intent_mode": "apply",
                    },
                },
            },
        ],
    )
    engine = RecommendationEngine(records_path)

    recs = engine.recommend(
        "portrait studio",
        "video_workflow",
        secondary_motion_context={
            "backend_id": "comfy",
            "enabled": True,
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
    assert "workflow_motion_v1" in best.context_key

