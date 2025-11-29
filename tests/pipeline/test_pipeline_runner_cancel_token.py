import uuid
from copy import deepcopy
from pathlib import Path
from unittest.mock import MagicMock

import pytest

from src.gui.state import CancelToken, CancellationError
from src.pipeline.pipeline_runner import PipelineConfig, PipelineRunner


class FakeConfigManager:
    def __init__(self, default_config: dict):
        self._default_config = default_config

    def get_default_config(self) -> dict:
        return deepcopy(self._default_config)


class RecordingPipeline:
    def __init__(self):
        self.cancel_tokens = []
        self.stage_events: list[dict] = []

    def reset_stage_events(self):
        self.stage_events = []

    def get_stage_events(self):
        return list(self.stage_events)

    def run_txt2img_stage(self, prompt, negative_prompt, config, run_dir, image_name, cancel_token=None):
        self.cancel_tokens.append(cancel_token)
        # Simulate stage metadata without touching the filesystem
        return {"path": str(Path(run_dir) / f"{image_name}.png"), "stage": "txt2img"}

    def run_img2img_stage(self, input_image_path, prompt, config, run_dir, image_name, cancel_token=None):
        self.cancel_tokens.append(cancel_token)
        return {"path": str(Path(run_dir) / f"{image_name}_i2i.png"), "stage": "img2img"}

    def run_upscale_stage(self, input_image_path, config, run_dir, image_name, cancel_token=None):
        self.cancel_tokens.append(cancel_token)
        return {"path": str(Path(run_dir) / f"{image_name}_up.png"), "stage": "upscale"}

    def run_adetailer_stage(self, input_image_path, config, run_dir, image_name, prompt=None, cancel_token=None):
        self.cancel_tokens.append(cancel_token)
        return {"path": str(Path(run_dir) / f"{image_name}_ad.png"), "stage": "adetailer"}


class CancelAfterTxt2ImgPipeline(RecordingPipeline):
    def __init__(self):
        super().__init__()
        self.upscale_called = False

    def run_txt2img_stage(self, prompt, negative_prompt, config, run_dir, image_name, cancel_token=None):
        self.cancel_tokens.append(cancel_token)
        if cancel_token:
            cancel_token.cancel()
        return {"path": str(Path(run_dir) / f"{image_name}.png"), "stage": "txt2img"}

    def run_upscale_stage(self, input_image_path, config, run_dir, image_name, cancel_token=None):
        self.upscale_called = True
        self.cancel_tokens.append(cancel_token)
        return super().run_upscale_stage(input_image_path, config, run_dir, image_name, cancel_token=cancel_token)


def _build_runner(tmp_path, config_manager, pipeline):
    runner = PipelineRunner(
        api_client=MagicMock(),
        structured_logger=MagicMock(),
        config_manager=config_manager,
        runs_base_dir=tmp_path,
    )
    runner._pipeline = pipeline
    return runner


def _minimal_config(enable_upscale: bool = False):
    base = {
        "txt2img": {
            "model": "model-a",
            "sampler_name": "Euler",
            "steps": 20,
            "cfg_scale": 7.0,
            "width": 512,
            "height": 512,
        },
        "pipeline": {
            "img2img_enabled": False,
            "adetailer_enabled": False,
            "upscale_enabled": enable_upscale,
        },
    }
    if enable_upscale:
        base["upscale"] = {"enabled": True, "upscaler": "nearest"}
    return base


def test_pipeline_runner_passes_cancel_token_to_stages(monkeypatch, tmp_path):
    config_manager = FakeConfigManager(_minimal_config())
    pipeline = RecordingPipeline()
    runner = _build_runner(tmp_path, config_manager, pipeline)
    monkeypatch.setattr("src.pipeline.pipeline_runner.write_run_metadata", lambda *args, **kwargs: None)

    cancel_token = CancelToken()
    config = PipelineConfig(
        prompt="hello world",
        model="model-a",
        sampler="Euler",
        width=512,
        height=512,
        steps=20,
        cfg_scale=7.0,
    )

    result = runner.run(config, cancel_token)

    assert result.success is True
    assert pipeline.cancel_tokens == [cancel_token]


def test_pipeline_runner_honors_cancellation_between_stages(monkeypatch, tmp_path):
    config_manager = FakeConfigManager(_minimal_config(enable_upscale=True))
    pipeline = CancelAfterTxt2ImgPipeline()
    runner = _build_runner(tmp_path, config_manager, pipeline)
    monkeypatch.setattr("src.pipeline.pipeline_runner.write_run_metadata", lambda *args, **kwargs: None)

    cancel_token = CancelToken()
    config = PipelineConfig(
        prompt="cancel me",
        model="model-a",
        sampler="Euler",
        width=512,
        height=512,
        steps=20,
        cfg_scale=7.0,
    )

    result = runner.run(config, cancel_token)

    assert pipeline.upscale_called is False
    assert result.success is False
    assert result.stage_events[-1]["cancelled"] is True
    assert result.stage_events[-1]["stage"] == "txt2img"
    assert pipeline.cancel_tokens[0] is cancel_token
