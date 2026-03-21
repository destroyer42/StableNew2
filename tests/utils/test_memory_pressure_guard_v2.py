from __future__ import annotations

from unittest.mock import Mock

from src.pipeline.executor import Pipeline


def test_assess_stage_pressure_marks_high_gpu_saturation_as_unsafe(monkeypatch) -> None:
    pipeline = Pipeline(Mock(), Mock())
    monkeypatch.setattr(
        "src.pipeline.executor.collect_gpu_snapshot",
        lambda: {
            "provider": "nvidia-smi",
            "devices": [
                {
                    "index": 0,
                    "name": "RTX",
                    "utilization_gpu_pct": 97.0,
                    "memory_total_mb": 12282.0,
                    "memory_used_mb": 11850.0,
                    "memory_free_mb": 432.0,
                    "temperature_c": 70.0,
                }
            ],
        },
    )

    assessment = pipeline._assess_stage_pressure(
        stage_name="upscale",
        width=1536,
        height=2304,
        batch_size=1,
        steps=15,
    )

    assert assessment["status"] == "unsafe"
    assert any("VRAM" in reason for reason in assessment["reasons"])


def test_assess_stage_pressure_normal_for_small_txt2img(monkeypatch) -> None:
    pipeline = Pipeline(Mock(), Mock())
    monkeypatch.setattr("src.pipeline.executor.collect_gpu_snapshot", lambda: None)

    assessment = pipeline._assess_stage_pressure(
        stage_name="txt2img",
        width=768,
        height=1024,
        batch_size=1,
        steps=20,
    )

    assert assessment["status"] == "normal"
