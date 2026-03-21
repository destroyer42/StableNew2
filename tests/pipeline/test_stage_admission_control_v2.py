from __future__ import annotations

from unittest.mock import Mock

import pytest

from src.pipeline.executor import Pipeline, PipelineStageError


def test_runtime_admission_recovers_guarded_profile_for_heavy_stage(monkeypatch) -> None:
    client = Mock()
    pipeline = Pipeline(client, Mock())

    states = [
        {
            "status": "degraded",
            "launch_profile": "standard",
            "reasons": ["guarded WebUI launch profile not active for heavy workload"],
        },
        {
            "status": "healthy",
            "launch_profile": "sdxl_guarded",
            "reasons": [],
        },
    ]

    monkeypatch.setattr(pipeline, "_assess_runtime_state", lambda **kwargs: states.pop(0))
    recovered = []
    monkeypatch.setattr(
        pipeline,
        "_attempt_webui_recovery",
        lambda **kwargs: recovered.append(kwargs) or True,
    )

    result = pipeline._ensure_runtime_admissible(
        stage_name="txt2img",
        pressure_assessment={"status": "high_pressure"},
    )

    assert result["status"] == "healthy"
    assert recovered
    assert recovered[0]["profile_override"] == "sdxl_guarded"


def test_runtime_admission_refuses_unsafe_upscale_when_runtime_stays_poisoned(monkeypatch) -> None:
    client = Mock()
    pipeline = Pipeline(client, Mock())

    monkeypatch.setattr(
        pipeline,
        "_assess_runtime_state",
        lambda **kwargs: {"status": "poisoned", "launch_profile": "standard", "reasons": ["webui connection check failed"]},
    )
    monkeypatch.setattr(pipeline, "_attempt_webui_recovery", lambda **kwargs: False)

    with pytest.raises(PipelineStageError) as excinfo:
        pipeline._ensure_runtime_admissible(
            stage_name="upscale",
            pressure_assessment={"status": "unsafe"},
        )

    assert "Runtime admission refused before upscale" in str(excinfo.value)
