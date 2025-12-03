from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import pytest

from src.pipeline.pipeline_runner import PipelineConfig, PipelineRunner
from tests.helpers.pipeline_fakes import FakePipeline


class DummyClient:
    pass


class DummyLogger:
    pass


@pytest.fixture(autouse=True)
def stub_pipeline(monkeypatch):
    monkeypatch.setattr("src.pipeline.pipeline_runner.Pipeline", FakePipeline)


def _cancel_token():
    return SimpleNamespace(is_cancelled=lambda: False)


def test_stage_runner_executes_in_order_txt2img_only(tmp_path):
    runner = PipelineRunner(DummyClient(), DummyLogger(), runs_base_dir=tmp_path / "runs")
    base_default = runner._config_manager.get_default_config()  # type: ignore[attr-defined]
    base_default["pipeline"]["img2img_enabled"] = False
    base_default["pipeline"]["upscale_enabled"] = False
    base_default["upscale"]["enabled"] = False
    runner._config_manager.get_default_config = lambda: base_default  # type: ignore[assignment]
    config = PipelineConfig(
        prompt="p",
        model="m",
        sampler="Euler",
        width=512,
        height=512,
        steps=20,
        cfg_scale=7.0,
    )
    result = runner.run(config, cancel_token=_cancel_token())
    pipeline = runner._pipeline  # type: ignore[attr-defined]
    assert [c[0] for c in pipeline.calls] == ["txt2img"]
    assert result.success is True
    assert result.stage_plan is not None


def test_stage_runner_executes_txt2img_then_upscale(tmp_path):
    runner = PipelineRunner(DummyClient(), DummyLogger(), runs_base_dir=tmp_path / "runs")
    base_default = runner._config_manager.get_default_config()  # type: ignore[attr-defined]
    base_default["pipeline"]["img2img_enabled"] = False
    base_default["pipeline"]["upscale_enabled"] = True
    base_default["upscale"]["enabled"] = True
    runner._config_manager.get_default_config = lambda: base_default  # type: ignore[assignment]
    config = PipelineConfig(
        prompt="p",
        model="m",
        sampler="Euler",
        width=512,
        height=512,
        steps=20,
        cfg_scale=7.0,
    )
    # enable upscale in default config via variant override
    runner._config_manager.get_default_config()["upscale"]["enabled"] = True  # type: ignore[attr-defined]
    result = runner.run(config, cancel_token=_cancel_token())
    pipeline = runner._pipeline  # type: ignore[attr-defined]
    assert [c[0] for c in pipeline.calls] == ["txt2img", "upscale"]
    assert result.success is True


def test_stage_runner_executes_adetailer_stage(tmp_path):
    runner = PipelineRunner(DummyClient(), DummyLogger(), runs_base_dir=tmp_path / "runs")
    base_default = runner._config_manager.get_default_config()  # type: ignore[attr-defined]
    base_default["pipeline"]["img2img_enabled"] = False
    base_default["pipeline"]["adetailer_enabled"] = True
    base_default["pipeline"]["upscale_enabled"] = False
    base_default.setdefault("adetailer", {})["enabled"] = True
    runner._config_manager.get_default_config = lambda: base_default  # type: ignore[assignment]
    config = PipelineConfig(
        prompt="p",
        model="m",
        sampler="Euler",
        width=512,
        height=512,
        steps=20,
        cfg_scale=7.0,
    )
    result = runner.run(config, cancel_token=_cancel_token())
    pipeline = runner._pipeline  # type: ignore[attr-defined]
    assert [c[0] for c in pipeline.calls] == ["txt2img", "adetailer"]
    assert any(evt["stage"] == "adetailer" for evt in result.stage_events)
