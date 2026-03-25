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
    monkeypatch.setattr(
        pipeline,
        "_attempt_runtime_soft_recovery",
        lambda **kwargs: (
            {
                "status": "degraded",
                "launch_profile": "standard",
                "runtime_causes": [{"code": "unguarded_heavy_workload", "severity": "degraded", "message": "guarded WebUI launch profile not active for heavy workload"}],
                "reasons": ["guarded WebUI launch profile not active for heavy workload"],
            },
            [{"step": "reprobe", "status": "degraded"}],
        ),
    )
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


def test_runtime_admission_does_not_restart_guarded_high_pressure_runtime_when_only_degraded(monkeypatch) -> None:
    client = Mock()
    pipeline = Pipeline(client, Mock())

    monkeypatch.setattr(
        pipeline,
        "_assess_runtime_state",
        lambda **kwargs: {
            "status": "degraded",
            "launch_profile": "sdxl_guarded",
            "reasons": ["suspicious long-lived StableNew-like processes detected"],
        },
    )
    monkeypatch.setattr(
        pipeline,
        "_attempt_webui_recovery",
        lambda **kwargs: pytest.fail("recovery should not run for guarded degraded runtime"),
    )

    result = pipeline._ensure_runtime_admissible(
        stage_name="upscale",
        pressure_assessment={"status": "high_pressure"},
    )

    assert result["status"] == "degraded"


def test_runtime_admission_uses_soft_recovery_for_stale_progress_before_restart(monkeypatch) -> None:
    client = Mock()
    pipeline = Pipeline(client, Mock())

    monkeypatch.setattr(
        pipeline,
        "_assess_runtime_state",
        lambda **kwargs: {
            "status": "poisoned",
            "launch_profile": "sdxl_guarded",
            "runtime_causes": [{"code": "stale_progress", "severity": "poisoned", "message": "stale progress state present (job)"}],
            "reasons": ["stale progress state present (job)"],
        },
    )
    monkeypatch.setattr(
        pipeline,
        "_attempt_runtime_soft_recovery",
        lambda **kwargs: (
            {
                "status": "healthy",
                "launch_profile": "sdxl_guarded",
                "runtime_causes": [],
                "reasons": [],
            },
            [{"step": "interrupt", "success": True}],
        ),
    )
    monkeypatch.setattr(
        pipeline,
        "_attempt_webui_recovery",
        lambda **kwargs: pytest.fail("restart should not run after successful soft recovery"),
    )

    result = pipeline._ensure_runtime_admissible(
        stage_name="upscale",
        pressure_assessment={"status": "normal"},
    )

    assert result["status"] == "healthy"
    assert result["recovery_trace"][0]["step"] == "interrupt"


def test_unsafe_upscale_pressure_autodowngrades_resize() -> None:
    client = Mock()
    pipeline = Pipeline(client, Mock())
    config = {"upscaling_resize": 2.0, "steps": 20}

    assessment = pipeline._assess_stage_pressure(
        stage_name="upscale",
        width=2048,
        height=3072,
        batch_size=1,
        steps=20,
    )

    downgraded = pipeline._maybe_autodowngrade_upscale_for_pressure(
        config=config,
        orig_width=1024,
        orig_height=1536,
        pressure_assessment=assessment,
    )

    assert config["upscaling_resize"] < 2.0
    assert downgraded["status"] != "unsafe"


def test_workload_launch_policy_upgrades_standard_profile_for_heavy_sdxl(monkeypatch) -> None:
    client = Mock()
    pipeline = Pipeline(client, Mock())
    pipeline._current_stage_chain = ["txt2img", "adetailer", "upscale"]
    pipeline._current_stage_index = 0

    class _Manager:
        def get_launch_profile(self) -> str:
            return "standard"

    monkeypatch.setattr("src.pipeline.executor.get_global_webui_process_manager", lambda: _Manager())
    recovered = []
    monkeypatch.setattr(
        pipeline,
        "_attempt_webui_recovery",
        lambda **kwargs: recovered.append(kwargs) or True,
    )

    profile = pipeline._maybe_apply_workload_launch_policy(
        stage_name="txt2img",
        requested_model="juggernautXL_ragnarokBy.safetensors",
        pressure_assessment={
            "width": 1024,
            "height": 1536,
            "batch_size": 1,
            "steps": 30,
            "megapixels": 1.573,
            "effective_load": 1.77,
        },
    )

    assert profile == "sdxl_guarded"
    assert recovered
    assert recovered[0]["profile_override"] == "sdxl_guarded"


def test_workload_launch_policy_respects_existing_low_memory_profile(monkeypatch) -> None:
    client = Mock()
    pipeline = Pipeline(client, Mock())

    class _Manager:
        def get_launch_profile(self) -> str:
            return "low_memory"

    monkeypatch.setattr("src.pipeline.executor.get_global_webui_process_manager", lambda: _Manager())
    monkeypatch.setattr(pipeline, "_attempt_webui_recovery", lambda **kwargs: pytest.fail("recovery should not run"))

    profile = pipeline._maybe_apply_workload_launch_policy(
        stage_name="upscale",
        requested_model="juggernautXL_ragnarokBy.safetensors",
        pressure_assessment={
            "width": 1536,
            "height": 2304,
            "batch_size": 1,
            "steps": 20,
            "megapixels": 3.539,
            "effective_load": 4.777,
        },
    )

    assert profile == "low_memory"


def test_workload_launch_policy_can_force_adetailer_experiment_profile(monkeypatch) -> None:
    client = Mock()
    pipeline = Pipeline(client, Mock())

    class _Manager:
        def get_launch_profile(self) -> str:
            return "standard"

    monkeypatch.setenv(
        "STABLENEW_ADETAILER_EXPERIMENT_LAUNCH_PROFILE",
        "sdxl_adetailer_guarded",
    )
    monkeypatch.setattr("src.pipeline.executor.get_global_webui_process_manager", lambda: _Manager())
    recovered = []
    monkeypatch.setattr(
        pipeline,
        "_attempt_webui_recovery",
        lambda **kwargs: recovered.append(kwargs) or True,
    )

    profile = pipeline._maybe_apply_workload_launch_policy(
        stage_name="adetailer",
        requested_model="epicrealismXL_vxviiCrystalclear.safetensors",
        pressure_assessment={
            "width": 768,
            "height": 1024,
            "batch_size": 1,
            "steps": 10,
            "megapixels": 0.786,
            "effective_load": 1.2,
        },
    )

    assert profile == "sdxl_adetailer_guarded"
    assert recovered
    assert recovered[0]["profile_override"] == "sdxl_adetailer_guarded"
