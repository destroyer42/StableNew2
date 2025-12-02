import base64
from io import BytesIO
from pathlib import Path

import pytest
from PIL import Image

import src.pipeline.executor as executor_module
from src.pipeline.executor import Pipeline
from src.utils.logger import StructuredLogger


def _tiny_image_base64(width: int = 8, height: int = 6) -> str:
    """Return base64 PNG for a solid-color image."""
    img = Image.new("RGB", (width, height), color=(255, 0, 0))
    buffer = BytesIO()
    img.save(buffer, format="PNG")
    return base64.b64encode(buffer.getvalue()).decode("utf-8")


class DummyClient:
    """Fake SD client capturing payloads."""

    def __init__(self, response_image: str):
        self._response_image = response_image
        self.img2img_calls: list[dict] = []
        self.upscale_calls: list[tuple] = []

    def img2img(self, payload):
        self.img2img_calls.append(payload)
        return {"images": [self._response_image]}

    def upscale_image(
        self,
        image_b64,
        upscaler,
        resize,
        gfpgan_visibility,
        codeformer_visibility,
        codeformer_weight,
    ):
        self.upscale_calls.append(
            (
                image_b64,
                upscaler,
                resize,
                gfpgan_visibility,
                codeformer_visibility,
                codeformer_weight,
            )
        )
        return {"image": self._response_image}

    # Legacy fallback API – keep signature simple
    def upscale(self, payload):
        self.upscale_calls.append(payload)
        return {"image": self._response_image}

    def set_model(self, *_args, **_kwargs):
        return None

    def set_vae(self, *_args, **_kwargs):
        return None


@pytest.fixture()
def base64_image():
    return _tiny_image_base64()


@pytest.fixture()
def fake_pipeline(tmp_path, base64_image, monkeypatch):
    """Create a Pipeline instance with patched IO helpers."""

    def fake_loader(_path):
        return base64_image

    def fake_saver(image_data, output_path):
        output_path = Path(output_path)
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_text("fake-image")
        assert image_data == base64_image
        return True

    monkeypatch.setattr(executor_module, "load_image_to_base64", fake_loader)
    monkeypatch.setattr(executor_module, "save_image_from_base64", fake_saver)

    structured_logger = StructuredLogger(output_dir=tmp_path / "logs")
    dummy_client = DummyClient(response_image=base64_image)
    pipeline = Pipeline(dummy_client, structured_logger)
    return pipeline, dummy_client


def test_upscale_img2img_respects_steps(tmp_path, fake_pipeline):
    pipeline, dummy_client = fake_pipeline
    input_image = tmp_path / "input.png"
    input_image.write_text("placeholder")
    output_dir = tmp_path / "pack" / "upscaled"
    output_dir.mkdir(parents=True, exist_ok=True)

    config = {
        "upscale_mode": "img2img",
        "steps": 17,
        "denoising_strength": 0.42,
        "cfg_scale": 6.5,
        "sampler_name": "DPM++ 2M",
        "scheduler": "Karras",
        "upscaling_resize": 1.5,
    }

    metadata = pipeline.run_upscale_stage(input_image, config, output_dir, "001_test")

    assert dummy_client.img2img_calls, "img2img mode should dispatch img2img request"
    payload = dummy_client.img2img_calls[-1]
    assert payload["steps"] == 17
    assert payload["denoising_strength"] == pytest.approx(0.42)
    assert payload["sampler_name"] == "DPM++ 2M"
    assert payload["scheduler"] == "Karras"
    assert metadata["config"]["steps"] == 17
    assert metadata["stage"] == "upscale"


def test_upscale_single_mode_uses_extras_endpoint(tmp_path, fake_pipeline):
    pipeline, dummy_client = fake_pipeline
    input_image = tmp_path / "input.png"
    input_image.write_text("placeholder")
    output_dir = tmp_path / "pack" / "upscaled"
    output_dir.mkdir(parents=True, exist_ok=True)

    config = {
        "upscale_mode": "single",
        "upscaler": "R-ESRGAN 4x+",
        "upscaling_resize": 2.0,
        "gfpgan_visibility": 0.2,
        "codeformer_visibility": 0.0,
        "codeformer_weight": 0.5,
    }

    metadata = pipeline.run_upscale_stage(input_image, config, output_dir, "002_test")

    assert not dummy_client.img2img_calls, "single mode must not invoke img2img"
    assert dummy_client.upscale_calls, "single mode should call extras upscaler"
    call_args = dummy_client.upscale_calls[-1]
    assert call_args[1] == "R-ESRGAN 4x+"
    assert call_args[2] == pytest.approx(2.0)
    assert metadata["stage"] == "upscale"


def test_run_pack_pipeline_runs_adetailer_when_enabled(tmp_path):
    pipeline = Pipeline(object(), StructuredLogger(output_dir=tmp_path / "logs"))

    def fake_txt2img(prompt, neg, cfg, output_dir, image_name):
        output_dir.mkdir(parents=True, exist_ok=True)
        img_path = output_dir / f"{image_name}.png"
        img_path.write_text("txt2img")
        return {"path": str(img_path)}

    def fake_img2img(input_path, prompt, cfg, output_dir, image_name):
        output_dir.mkdir(parents=True, exist_ok=True)
        img_path = output_dir / f"{image_name}.png"
        img_path.write_text("img2img")
        return {"path": str(img_path)}

    adetailer_calls = []

    def fake_adetailer(input_image_path, prompt, cfg, run_dir, cancel_token=None):
        adetailer_calls.append({"input": str(input_image_path), "config": cfg})
        out_dir = run_dir / "adetailer"
        out_dir.mkdir(exist_ok=True)
        img_path = out_dir / "adetailer_result.png"
        img_path.write_text("adetailer")
        return {"path": str(img_path)}

    pipeline.run_txt2img_stage = fake_txt2img  # type: ignore[assignment]
    pipeline.run_img2img_stage = fake_img2img  # type: ignore[assignment]
    pipeline.run_upscale_stage = lambda *args, **kwargs: None  # type: ignore[assignment]
    pipeline.run_adetailer = fake_adetailer  # type: ignore[assignment]

    config = {
        "txt2img": {"negative_prompt": "", "width": 512, "height": 640},
        "img2img": {},
        "adetailer": {
            "adetailer_enabled": True,
            "adetailer_model": "face_yolov8n.pt",
            "adetailer_steps": 12,
        },
        "pipeline": {
            "img2img_enabled": True,
            "adetailer_enabled": True,
            "upscale_enabled": False,
        },
    }

    run_dir = pipeline.logger.create_run_directory("test_run")
    results = pipeline.run_pack_pipeline(
        pack_name="TestPack",
        prompt="portrait",
        config=config,
        run_dir=run_dir,
        prompt_index=0,
        batch_size=1,
    )

    assert adetailer_calls, "ADetailer should run when pipeline toggle is enabled"
    assert results["adetailer"], "Results should include ADetailer metadata"
    assert "adetailer" in results["summary"][0]["steps_completed"]
