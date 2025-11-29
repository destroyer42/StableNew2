from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import pytest

from src.pipeline.pipeline_runner import PipelineConfig, PipelineRunner


class FakePipeline:
    def __init__(self, *_args, **_kwargs):
        self.calls = []
        self.stage_events: list[dict] = []

    def run_txt2img_stage(self, prompt, negative_prompt, config, output_dir, image_name):
        self.calls.append(("txt2img", prompt, output_dir, image_name))
        return {"path": str(Path(output_dir) / f"{image_name}.png")}

    def run_img2img_stage(self, input_image_path, prompt, config, output_dir):
        self.calls.append(("img2img", prompt, str(input_image_path)))
        return {"path": str(Path(output_dir) / "img2img.png")}

    def run_upscale_stage(self, input_image_path, config, output_dir, image_name):
        self.calls.append(("upscale", str(input_image_path), image_name))
        return {"path": str(Path(output_dir) / "upscaled.png")}

    def run_adetailer_stage(self, input_image_path, config, output_dir, image_name, prompt=None):
        self.calls.append(("adetailer", str(input_image_path), image_name))
        return {"path": str(Path(output_dir) / "adetailer.png")}

    def reset_stage_events(self):
        self.stage_events = []

    def get_stage_events(self):
        return list(self.stage_events)


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
