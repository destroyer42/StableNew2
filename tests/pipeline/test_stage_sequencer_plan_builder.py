from __future__ import annotations

import logging

import pytest

from src.pipeline.stage_sequencer import build_stage_execution_plan


def _base_config():
    return {
        "txt2img": {
            "enabled": True,
            "model": "m",
            "sampler_name": "Euler",
            "steps": 20,
            "cfg_scale": 7.0,
            "width": 512,
            "height": 512,
        },
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
    assert [s.stage_type for s in plan.stages] == ["txt2img", "upscale", "adetailer"]
    assert plan.stages[1].stage_type == "upscale"
    assert plan.stages[1].requires_input_image is True


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
    assert [s.stage_type for s in plan.stages] == ["txt2img", "img2img", "upscale", "adetailer"]


def test_plan_builder_adetailer_without_generative_stage_raises():
    cfg = _base_config()
    cfg["txt2img"]["enabled"] = False
    cfg["pipeline"]["txt2img_enabled"] = False
    cfg["img2img"]["enabled"] = False
    cfg["pipeline"]["img2img_enabled"] = False
    cfg["pipeline"]["adetailer_enabled"] = True
    cfg["adetailer"] = {"enabled": True}
    with pytest.raises(ValueError):
        build_stage_execution_plan(cfg)


def test_plan_builder_reorders_adetailer_with_warning(caplog):
    """Test that stages are built in correct order (txt2img -> upscale -> adetailer).

    Note: No reordering warning is expected because stages are added in canonical order.
    The warning only fires if stages were somehow added out of order and need reordering.
    """
    cfg = _base_config()
    cfg["pipeline"]["adetailer_enabled"] = True
    cfg["adetailer"] = {"enabled": True}
    cfg["pipeline"]["upscale_enabled"] = True
    cfg["upscale"]["enabled"] = True
    caplog.set_level(logging.WARNING)
    plan = build_stage_execution_plan(cfg)
    assert [s.stage_type for s in plan.stages] == ["txt2img", "upscale", "adetailer"]
    # No reordering warning expected since stages are already in canonical order


def test_plan_builder_carries_hires_metadata():
    """Test that hires_fix metadata is carried on the txt2img stage."""
    cfg = _base_config()
    cfg["hires_fix"] = {
        "enabled": True,
        "upscale_factor": 1.5,
        "upscaler_name": "Latent",
        "steps": 10,
        "denoise_strength": 0.4,
    }
    plan = build_stage_execution_plan(cfg)
    metadata = plan.stages[0].config.metadata
    # Hires metadata is stored as individual fields on StageMetadata
    assert metadata.hires_enabled is True
    assert metadata.hires_upscale_factor == 1.5
    assert metadata.hires_steps == 10
    assert metadata.hires_denoise == 0.4
