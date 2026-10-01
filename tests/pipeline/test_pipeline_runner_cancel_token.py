import uuid
from copy import deepcopy
from pathlib import Path
from unittest.mock import MagicMock

import pytest

from src.controller.runtime_state import CancellationError, CancelToken
from src.pipeline.job_models_v2 import NormalizedJobRecord
from src.pipeline.pipeline_runner import PipelineRunner
from tests.helpers.njr_factory import make_pipeline_njr, make_stage_config


class FakeConfigManager:
    def __init__(self, default_config: dict):
        self._default_config = default_config

    def get_default_config(self) -> dict:
        return deepcopy(self._default_config)


class RecordingPipeline:
    """Fake executor whose stage signatures mirror the real ``Pipeline`` stage entry points."""

    def __init__(self):
        self.cancel_tokens = []
        self.stage_events: list[dict] = []

    def reset_stage_events(self):
        self.stage_events = []

    def get_stage_events(self):
        return list(self.stage_events)

    def run_txt2img_stage(
        self,
        prompt,
        negative_prompt,
        config,
        output_dir,
        image_name,
        cancel_token=None,
        learning_sample_names=False,
    ):
        self.cancel_tokens.append(cancel_token)
        # Simulate stage metadata without touching the filesystem
        return {"path": str(Path(output_dir) / f"{image_name}.png"), "stage": "txt2img"}

    def run_img2img_stage(
        self, input_image_path, prompt, config, output_dir, image_name, cancel_token=None
    ):
        self.cancel_tokens.append(cancel_token)
        return {"path": str(Path(output_dir) / f"{image_name}_i2i.png"), "stage": "img2img"}

    def run_upscale_stage(
        self, input_image_path, config, output_dir, image_name, cancel_token=None
    ):
        self.cancel_tokens.append(cancel_token)
        return {"path": str(Path(output_dir) / f"{image_name}_up.png"), "stage": "upscale"}

    def run_adetailer_stage(
        self,
        input_image_path,
        config,
        output_dir,
        image_name,
        prompt=None,
        negative_prompt=None,
        cancel_token=None,
    ):
        self.cancel_tokens.append(cancel_token)
        return {"path": str(Path(output_dir) / f"{image_name}_ad.png"), "stage": "adetailer"}


class CancelAfterTxt2ImgPipeline(RecordingPipeline):
    """Cancels during txt2img; later stages abort at stage start like the real executor."""

    def __init__(self):
        super().__init__()
        self.upscale_saw_cancelled_token = False

    def run_txt2img_stage(
        self,
        prompt,
        negative_prompt,
        config,
        output_dir,
        image_name,
        cancel_token=None,
        learning_sample_names=False,
    ):
        self.cancel_tokens.append(cancel_token)
        if cancel_token:
            cancel_token.cancel()
        return {"path": str(Path(output_dir) / f"{image_name}.png"), "stage": "txt2img"}

    def run_upscale_stage(
        self, input_image_path, config, output_dir, image_name, cancel_token=None
    ):
        self.upscale_saw_cancelled_token = bool(cancel_token and cancel_token.is_cancelled())
        if self.upscale_saw_cancelled_token:
            raise CancellationError("Cancelled during upscale stage start")
        return super().run_upscale_stage(
            input_image_path, config, output_dir, image_name, cancel_token=cancel_token
        )


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


def _build_record(
    tmp_path: Path, prompt: str, include_upscale: bool = False
) -> NormalizedJobRecord:
    chain = [
        make_stage_config("txt2img", model="model-a", sampler_name="Euler", steps=20, cfg_scale=7.0)
    ]
    if include_upscale:
        chain.append(make_stage_config("upscale", extra={"upscaler": "nearest"}))
    return make_pipeline_njr(
        job_id=str(uuid.uuid4()),
        config={
            "prompt": prompt,
            "model": "model-a",
            "sampler_name": "Euler",
            "steps": 20,
            "cfg_scale": 7.0,
            "width": 512,
            "height": 512,
        },
        path_output_dir=str(tmp_path / "runs"),
        filename_template="{seed}",
        seed=123,
        stage_chain=chain,
        base_model="model-a",
        positive_prompt=prompt,
    )


def test_pipeline_runner_passes_cancel_token_to_stages(monkeypatch, tmp_path):
    config_manager = FakeConfigManager(_minimal_config())
    pipeline = RecordingPipeline()
    runner = _build_runner(tmp_path, config_manager, pipeline)
    monkeypatch.setattr(
        "src.pipeline.pipeline_runner.write_run_metadata", lambda *args, **kwargs: None
    )

    cancel_token = CancelToken()
    record = _build_record(tmp_path, "hello world")

    result = runner.run_njr(record, cancel_token)

    assert result.success is True
    assert pipeline.cancel_tokens == [cancel_token]


def test_pipeline_runner_propagates_stage_cancellation_after_earlier_stage_cancels(
    monkeypatch, tmp_path
):
    """Stage-level guards own cancellation: the runner hands the cancelled token to the next
    stage and lets that stage's CancellationError propagate instead of recording a failure."""
    config_manager = FakeConfigManager(_minimal_config(enable_upscale=True))
    pipeline = CancelAfterTxt2ImgPipeline()
    runner = _build_runner(tmp_path, config_manager, pipeline)
    monkeypatch.setattr(
        "src.pipeline.pipeline_runner.write_run_metadata", lambda *args, **kwargs: None
    )

    cancel_token = CancelToken()
    record = _build_record(tmp_path, "cancel me", include_upscale=True)

    with pytest.raises(CancellationError):
        runner.run_njr(record, cancel_token)

    assert pipeline.upscale_saw_cancelled_token is True
    assert pipeline.cancel_tokens[0] is cancel_token
    assert all(token is cancel_token for token in pipeline.cancel_tokens)
