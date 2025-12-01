from __future__ import annotations

import pytest

from src.pipeline.pipeline_runner import PipelineRunner, PipelineConfig
from src.pipeline.stage_sequencer import build_stage_execution_plan
from src.utils import StructuredLogger


class DummyClient:
    def txt2img(self, *args, **kwargs):
        return {}
    def img2img(self, *args, **kwargs):
        return {}
    def upscale(self, *args, **kwargs):
        return {}


def _build_runner() -> PipelineRunner:
    return PipelineRunner(
        api_client=DummyClient(),
        structured_logger=StructuredLogger(),
    )


def _base_config() -> PipelineConfig:
    return PipelineConfig(
        prompt="test",
        model="demo",
        sampler="Euler a",
        width=512,
        height=512,
        steps=20,
        cfg_scale=7.5,
    )


def test_executor_config_includes_adetailer_when_metadata_enabled():
    runner = _build_runner()
    cfg = _base_config()
    cfg.metadata = {"adetailer_enabled": True}

    executor_config = runner._build_executor_config(cfg)
    plan = build_stage_execution_plan(executor_config)

    assert any(stage.stage_type == "adetailer" for stage in plan.stages)


def test_executor_config_excludes_adetailer_by_default():
    runner = _build_runner()
    cfg = _base_config()
    executor_config = runner._build_executor_config(cfg)

    plan = build_stage_execution_plan(executor_config)
    assert all(stage.stage_type != "adetailer" for stage in plan.stages)


def test_executor_config_preserves_selected_model_and_detector():
    runner = _build_runner()
    cfg = _base_config()
    cfg.metadata = {
        "adetailer_enabled": True,
        "adetailer": {"adetailer_model": "face_yolov8n.pt", "detector": "face"},
    }

    executor_config = runner._build_executor_config(cfg)
    plan = build_stage_execution_plan(executor_config)
    ad_stage = next((stage for stage in plan.stages if stage.stage_type == "adetailer"), None)
    assert ad_stage is not None
    payload = ad_stage.config.payload
    assert payload.get("adetailer_model") == "face_yolov8n.pt"
    assert payload.get("detector") == "face"
