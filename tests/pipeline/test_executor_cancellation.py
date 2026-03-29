from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch

import pytest

from src.controller.runtime_state import CancellationError
from src.pipeline.executor import Pipeline
from src.pipeline.job_models_v2 import NormalizedJobRecord, StageConfig
from src.pipeline.pipeline_runner import PipelineRunner
from src.utils.logger import StructuredLogger


class ToggleToken:
    def __init__(self):
        self._cancelled = False

    def cancel(self):
        self._cancelled = True

    def is_cancelled(self):
        return self._cancelled


class DummyClient:
    def generate_images(self, *, stage, payload, **kwargs):
        return SimpleNamespace(
            ok=True,
            result=SimpleNamespace(
                images=["fake-image-1", "fake-image-2"],
                info={},
                stage=stage,
                timings={},
            ),
        )

    def set_model(self, *_args, **_kwargs):
        return None

    def set_vae(self, *_args, **_kwargs):
        return None

    def get_current_model(self):
        return "model-a"

    def get_current_vae(self):
        return "Automatic"

    def check_connection(self, **_kwargs):
        return True


def _fake_structured_logger(tmp_path: Path) -> StructuredLogger:
    return StructuredLogger(output_dir=tmp_path / "logs")


def test_run_txt2img_stage_raises_when_cancelled_before_start(tmp_path):
    token = ToggleToken()
    token.cancel()
    pipeline = Pipeline(DummyClient(), _fake_structured_logger(tmp_path))

    with (
        patch.object(pipeline, "_ensure_webui_true_ready", return_value=None),
        pytest.raises(CancellationError),
    ):
        pipeline.run_txt2img_stage(
            prompt="test prompt",
            negative_prompt="",
            config={"steps": 1, "batch_size": 2},
            output_dir=tmp_path,
            image_name="txt2img_test",
            cancel_token=token,
        )


def test_runner_honors_cancellation_between_stages(tmp_path):
    token = ToggleToken()
    runner = PipelineRunner(Mock(), _fake_structured_logger(tmp_path), runs_base_dir=str(tmp_path / "runs"))

    class _FakePipeline:
        def __init__(self):
            self.upscale_saw_cancelled_token = False
            self._current_job_id = None
            self._current_njr_sha256 = None
            self._current_stage_chain = []
            self._current_stage_index = 0

        def _begin_run_metrics(self):
            return None

        def get_run_efficiency_metrics(self, _images_processed):
            return {}

        def run_txt2img_stage(self, prompt, negative_prompt, config, run_dir, image_name, cancel_token=None):
            cancel_token.cancel()
            output_path = Path(run_dir) / f"{image_name}.png"
            output_path.parent.mkdir(parents=True, exist_ok=True)
            output_path.write_text("image")
            return {"path": str(output_path), "all_paths": [str(output_path)], "stage": "txt2img"}

        def run_upscale_stage(self, *args, **kwargs):
            cancel_token = kwargs.get("cancel_token")
            self.upscale_saw_cancelled_token = bool(cancel_token and cancel_token.is_cancelled())
            return None

    fake_pipeline = _FakePipeline()
    runner._pipeline = fake_pipeline

    record = NormalizedJobRecord(
        job_id="cancelled-runner-job",
        config={"steps": 20, "cfg_scale": 7.0, "width": 512, "height": 512},
        path_output_dir=str(tmp_path / "runs"),
        filename_template="{seed}",
        seed=123,
        positive_prompt="cancel me",
        negative_prompt="",
        steps=20,
        cfg_scale=7.0,
        width=512,
        height=512,
        sampler_name="Euler a",
        base_model="model-a",
        stage_chain=[
            StageConfig(stage_type="txt2img", enabled=True, steps=20, cfg_scale=7.0),
            StageConfig(stage_type="upscale", enabled=True, extra={"upscaler": "nearest"}),
        ],
    )

    result = runner.run_njr(record, cancel_token=token)

    assert result.success is False
    assert result.error == "No images were generated successfully"
    assert fake_pipeline.upscale_saw_cancelled_token is True
