from __future__ import annotations

import pytest

from src.pipeline.stage_sequencer import StageExecutionPlan, build_stage_execution_plan, StageExecution


def _base_pipeline_config(**overrides) -> dict[str, dict]:
    config = {
        "pipeline": {
            "txt2img_enabled": True,
            "img2img_enabled": False,
            "upscale_enabled": False,
            "adetailer_enabled": False,
        },
        "txt2img": {
            "model": "sd_xl_base_1.0",
            "sampler_name": "Euler",
            "steps": 20,
            "cfg_scale": 7.0,
        },
        "img2img": {},
        "upscale": {},
        "adetailer": {},
        "hires_fix": {},
    }
    for key, value in overrides.items():
        if key in config and isinstance(config[key], dict):
            config[key].update(value)
        else:
            config[key] = value
    return config


def test_build_plan_txt2img_refiner_and_metadata():
    config = _base_pipeline_config(
        txt2img={
            "refiner_enabled": True,
            "refiner_model_name": "refiner_v1.pt",
            "refiner_switch_at": 0.6,
        },
        pipeline={"txt2img_enabled": True},
        hiresh={"dummy": "value"},
    )
    plan = build_stage_execution_plan(config)
    assert len(plan.stages) == 1
    stage = plan.stages[0]
    assert stage.stage_type == "txt2img"
    metadata = stage.config.metadata
    assert metadata.refiner_enabled is True
    assert metadata.refiner_model_name == "refiner_v1.pt"
    assert metadata.stage_flags["txt2img_enabled"]


def test_build_plan_txt2img_upscale_adetailer_order():
    config = _base_pipeline_config(
        pipeline={
            "txt2img_enabled": True,
            "upscale_enabled": True,
            "adetailer_enabled": True,
        },
        upscale={"upscaler": "UltraSharp", "upscale_factor": 2.0},
        adetailer={"adetailer_model": "adetailer_v1.pt"},
    )
    plan = build_stage_execution_plan(config)
    assert [stage.stage_type for stage in plan.stages] == ["txt2img", "upscale", "adetailer"]
    assert plan.stages[-1].stage_type == "adetailer"
    assert plan.stages[1].stage_type == "upscale"


def test_build_plan_img2img_and_adetailer():
    config = _base_pipeline_config(
        pipeline={
            "txt2img_enabled": False,
            "img2img_enabled": True,
            "adetailer_enabled": True,
        },
        img2img={"model": "sd_xl_base_1.0", "sampler_name": "Euler", "steps": 20},
        adetailer={"adetailer_model": "adetailer_v1.pt"},
    )
    plan = build_stage_execution_plan(config)
    assert [stage.stage_type for stage in plan.stages] == ["img2img", "adetailer"]


def test_build_plan_adetailer_without_generation_raises():
    config = _base_pipeline_config(
        pipeline={
            "txt2img_enabled": False,
            "img2img_enabled": False,
            "adetailer_enabled": True,
        },
        adetailer={"adetailer_model": "adetailer_v1.pt"},
    )
    with pytest.raises(ValueError):
        build_stage_execution_plan(config)
