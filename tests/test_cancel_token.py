from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import pytest

from src.controller.runtime_state import CancelToken, CancellationError
from src.pipeline.executor import Pipeline
from src.utils import StructuredLogger


def _success_outcome(images):
    return SimpleNamespace(ok=True, result={"images": images})


class _MockClient:
    def __init__(self):
        self.generate_images = lambda **_kwargs: _success_outcome(["base64_image_data"])
        self.set_model = lambda *_args, **_kwargs: None
        self.set_vae = lambda *_args, **_kwargs: None
        self.get_current_model = lambda: "model-a"
        self.get_current_vae = lambda: "Automatic"


@pytest.fixture
def pipeline(tmp_path: Path):
    logger = StructuredLogger()
    logger.output_dir = tmp_path
    return Pipeline(_MockClient(), logger)


def test_cancel_before_txt2img_stage(pipeline, tmp_path):
    cancel_token = CancelToken()
    cancel_token.cancel()

    with pytest.raises(CancellationError):
        pipeline.run_txt2img_stage(
            "test prompt",
            "",
            {"steps": 1, "batch_size": 1},
            tmp_path,
            "txt2img_cancelled",
            cancel_token=cancel_token,
        )


def test_cancel_before_img2img_stage_returns_none(pipeline, tmp_path):
    cancel_token = CancelToken()
    cancel_token.cancel()
    input_path = tmp_path / "test.png"
    input_path.write_text("image")

    with pytest.raises(CancellationError):
        with patch("src.pipeline.executor.load_image_to_base64", return_value="base64"):
            pipeline.run_img2img_stage(
                input_path,
                "test prompt",
                {},
                tmp_path,
                "img2img_cancelled",
                cancel_token=cancel_token,
            )


def test_cancel_before_upscale_stage_returns_none(pipeline, tmp_path):
    cancel_token = CancelToken()
    cancel_token.cancel()
    input_path = tmp_path / "test.png"
    input_path.write_text("image")

    with pytest.raises(CancellationError):
        with patch("src.pipeline.executor.load_image_to_base64", return_value="base64"):
            pipeline.run_upscale_stage(
                input_path,
                {},
                tmp_path,
                image_name="upscale_cancelled",
                cancel_token=cancel_token,
            )
