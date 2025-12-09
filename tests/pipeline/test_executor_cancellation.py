from pathlib import Path
from types import SimpleNamespace

import pytest

import src.pipeline.executor as executor_module
from src.api.types import GenerateResult
from src.pipeline.executor import Pipeline
from src.gui.state import CancellationError
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
        result = GenerateResult(images=["fake-image-1", "fake-image-2"], info={}, stage=stage)
        return SimpleNamespace(ok=True, result=result)

    def set_model(self, *_args, **_kwargs):
        return None

    def set_vae(self, *_args, **_kwargs):
        return None


def _fake_structured_logger(tmp_path: Path) -> StructuredLogger:
    return StructuredLogger(output_dir=tmp_path / "logs")


def test_run_txt2img_raises_when_cancelled_during_save(tmp_path, monkeypatch):
    token = ToggleToken()
    pipeline = Pipeline(DummyClient(), _fake_structured_logger(tmp_path))

    save_calls = {"count": 0}

    def fake_saver(_image_data, output_path):
        output_path = Path(output_path)
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_text("placeholder")
        save_calls["count"] += 1
        if save_calls["count"] == 1:
            token.cancel()
        return True

    monkeypatch.setattr(executor_module, "save_image_from_base64", fake_saver)

    with pytest.raises(CancellationError):
        pipeline.run_txt2img(
            prompt="test prompt",
            config={"negative_prompt": "", "steps": 1},
            run_dir=tmp_path,
            batch_size=1,
            cancel_token=token,
        )

    assert save_calls["count"] == 1


def test_run_full_pipeline_bails_after_txt2img_when_cancelled(tmp_path):
    token = ToggleToken()
    pipeline = Pipeline(DummyClient(), _fake_structured_logger(tmp_path))

    generated_path = tmp_path / "generated.png"
    generated_path.parent.mkdir(parents=True, exist_ok=True)
    generated_path.write_text("img")

    def fake_run_txt2img(prompt, cfg, run_dir, batch_size, cancel_token):
        token.cancel()
        return [
            {
                "name": "img0",
                "timestamp": "now",
                "path": str(generated_path),
            }
        ]

    pipeline.run_txt2img = fake_run_txt2img  # type: ignore[assignment]

    with pytest.raises(CancellationError):
        pipeline.run_full_pipeline(
            prompt="test prompt",
            config={
                "txt2img": {"negative_prompt": ""},
                "pipeline": {"img2img_enabled": False, "upscale_enabled": False},
            },
            batch_size=1,
            cancel_token=token,
        )
