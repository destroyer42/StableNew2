from __future__ import annotations

from src.controller.pipeline_controller import PipelineController
from src.pipeline.stage_sequencer import StageExecutionPlan


def test_controller_stores_last_stage_execution_plan():
    controller = PipelineController()
    cfg = {
        "txt2img": {"enabled": True, "model": "m", "sampler_name": "Euler", "steps": 20, "cfg_scale": 7.0},
        "img2img": {"enabled": False, "model": "m", "sampler_name": "Euler", "steps": 10},
        "upscale": {"enabled": False, "upscaler": "R-ESRGAN 4x+"},
        "pipeline": {},
    }
    plan = controller.validate_stage_plan(cfg)
    assert isinstance(plan, StageExecutionPlan)
    assert controller.get_last_stage_execution_plan_for_tests() == plan
