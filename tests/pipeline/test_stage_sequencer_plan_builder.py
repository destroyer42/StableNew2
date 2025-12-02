from __future__ import annotations

import pytest

from src.pipeline.stage_sequencer import build_stage_execution_plan


def _base_config():
    return {
        "txt2img": {"enabled": True, "model": "m", "sampler_name": "Euler", "steps": 20, "cfg_scale": 7.0, "width": 512, "height": 512},
        "img2img": {"enabled": False, "model": "m", "sampler_name": "Euler", "steps": 10},
        "upscale": {"enabled": False, "upscaler": "R-ESRGAN 4x+"},
        "pipeline": {"txt2img_enabled": True, "img2img_enabled": False, "upscale_enabled": False},
    }


def test_plan_builder_txt2img_only():
    cfg = _base_config()
    plan = build_stage_execution_plan(cfg)
    assert [s.stage_type for s in plan.stages] == ["txt2img"]
    assert plan.stages[0].order_index == 0


def test_plan_builder_img2img_only_requires_input_flag():
    cfg = _base_config()
    cfg["txt2img"]["enabled"] = False
    cfg["img2img"]["enabled"] = True
    cfg["pipeline"]["img2img_enabled"] = True
    plan = build_stage_execution_plan(cfg)
    assert [s.stage_type for s in plan.stages] == ["img2img"]
    assert plan.stages[0].requires_input_image is True


def test_plan_builder_txt2img_upscale_ordering():
    cfg = _base_config()
    cfg["upscale"]["enabled"] = True
    cfg["pipeline"]["upscale_enabled"] = True
    plan = build_stage_execution_plan(cfg)
    assert [s.stage_type for s in plan.stages] == ["txt2img", "upscale"]
    assert plan.stages[1].order_index == 1
    assert plan.stages[1].requires_input_image is True


def test_plan_builder_missing_required_fields_raises():
    cfg = _base_config()
    cfg["txt2img"]["model"] = ""
    with pytest.raises(ValueError):
        build_stage_execution_plan(cfg)


def test_plan_builder_includes_adetailer_before_upscale():
    cfg = _base_config()
    cfg["pipeline"]["adetailer_enabled"] = True
    cfg["pipeline"]["upscale_enabled"] = True
    cfg["upscale"]["enabled"] = True
    cfg["adetailer"] = {"enabled": True}
    plan = build_stage_execution_plan(cfg)
    assert [s.stage_type for s in plan.stages] == ["txt2img", "adetailer", "upscale"]
    assert plan.stages[1].requires_input_image is True
    assert plan.stages[2].order_index == 2


def test_plan_builder_excludes_adetailer_by_default():
    cfg = _base_config()
    plan = build_stage_execution_plan(cfg)
    assert all(stage.stage_type != "adetailer" for stage in plan.stages)


def test_plan_builder_txt2img_and_adetailer():
    cfg = _base_config()
    cfg["pipeline"]["adetailer_enabled"] = True
    cfg["adetailer"] = {"enabled": True}
    plan = build_stage_execution_plan(cfg)
    assert [s.stage_type for s in plan.stages] == ["txt2img", "adetailer"]


def test_plan_builder_img2img_and_adetailer():
    cfg = _base_config()
    cfg["txt2img"]["enabled"] = False
    cfg["pipeline"]["txt2img_enabled"] = False
    cfg["img2img"]["enabled"] = True
    cfg["pipeline"]["img2img_enabled"] = True
    cfg["pipeline"]["adetailer_enabled"] = True
    cfg["adetailer"] = {"enabled": True}
    plan = build_stage_execution_plan(cfg)
    assert [s.stage_type for s in plan.stages] == ["img2img", "adetailer"]


def test_plan_builder_txt2img_img2img_adetailer():
    cfg = _base_config()
    cfg["img2img"]["enabled"] = True
    cfg["pipeline"]["img2img_enabled"] = True
    cfg["pipeline"]["adetailer_enabled"] = True
    cfg["adetailer"] = {"enabled": True}
    plan = build_stage_execution_plan(cfg)
    assert [s.stage_type for s in plan.stages] == ["txt2img", "img2img", "adetailer"]


def test_plan_builder_adetailer_and_upscale_sequence():
    cfg = _base_config()
    cfg["img2img"]["enabled"] = True
    cfg["pipeline"]["img2img_enabled"] = True
    cfg["pipeline"]["adetailer_enabled"] = True
    cfg["upscale"]["enabled"] = True
    cfg["pipeline"]["upscale_enabled"] = True
    cfg["adetailer"] = {"enabled": True}
    plan = build_stage_execution_plan(cfg)
    assert [s.stage_type for s in plan.stages] == ["txt2img", "img2img", "adetailer", "upscale"]


def test_plan_builder_adetailer_without_generative_stage_skipped():
    cfg = _base_config()
    cfg["txt2img"]["enabled"] = False
    cfg["pipeline"]["txt2img_enabled"] = False
    cfg["img2img"]["enabled"] = False
    cfg["pipeline"]["img2img_enabled"] = False
    cfg["pipeline"]["adetailer_enabled"] = True
    cfg["adetailer"] = {"enabled": True}
    plan = build_stage_execution_plan(cfg)
    assert all(stage.stage_type != "adetailer" for stage in plan.stages)
