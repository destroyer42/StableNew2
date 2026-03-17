from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from src.pipeline.cli_njr_builder import build_cli_njr
from src.pipeline.pipeline_runner import PipelineRunner
from src.utils.config import build_sampler_scheduler_payload
from src.utils.logger import StructuredLogger


def _success_outcome(images: list[str]) -> SimpleNamespace:
    return SimpleNamespace(
        ok=True,
        result=SimpleNamespace(images=images, info={}, stage="txt2img", timings={}),
    )


class _CapturingClient:
    def __init__(self) -> None:
        self.calls: list[dict[str, object]] = []

    def generate_images(self, *, stage, payload, **kwargs):
        self.calls.append({"stage": stage, "payload": dict(payload), "kwargs": dict(kwargs)})
        return _success_outcome(["fake_base64"])

    def set_model(self, *_args, **_kwargs):
        return None

    def set_vae(self, *_args, **_kwargs):
        return None

    def get_current_model(self):
        return "model-a.safetensors"

    def get_current_vae(self):
        return "vae-a.safetensors"

    def free_vram(self, **_kwargs):
        return True

    def check_connection(self, **_kwargs):
        return True


def test_txt2img_config_passes_through_canonical_runner_path(tmp_path: Path) -> None:
    client = _CapturingClient()
    runner = PipelineRunner(client, StructuredLogger(output_dir=tmp_path / "logs"), runs_base_dir=str(tmp_path / "runs"))
    config = {
        "txt2img": {
            "steps": 28,
            "cfg_scale": 6.0,
            "width": 768,
            "height": 960,
            "sampler_name": "DPM++ 2M",
            "scheduler": "Karras",
            "negative_prompt": "ugly",
            "seed": 1234,
            "clip_skip": 2,
            "model": "model-a.safetensors",
            "vae": "vae-a.safetensors",
            "enable_hr": True,
            "hr_scale": 1.5,
            "hr_upscaler": "Latent",
            "denoising_strength": 0.4,
        },
        "pipeline": {"txt2img_enabled": True},
        "aesthetic": {"enabled": False},
    }
    record = build_cli_njr(prompt="validation prompt", config=config, batch_size=2, run_name="cfg-check")

    def _fake_save(_image_data, output_path, metadata_builder=None):
        output_path = Path(output_path)
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_text("image")
        return output_path

    with (
        patch("src.pipeline.executor.save_image_from_base64", side_effect=_fake_save),
        patch.object(runner._pipeline, "_ensure_webui_true_ready", return_value=None),
    ):
        result = runner.run_njr(record, cancel_token=None)

    assert result.success is True
    assert len(client.calls) == 1
    payload = client.calls[0]["payload"]
    assert str(payload["prompt"]).endswith("validation prompt")
    assert "ugly" in str(payload["negative_prompt"])
    assert payload["steps"] == 28
    assert payload["cfg_scale"] == 6.0
    assert payload["width"] == 768
    assert payload["height"] == 960
    assert payload["batch_size"] == 1
    assert payload["n_iter"] == 2
    assert payload["seed"] == 1234
    assert payload["enable_hr"] is True
    assert payload["hr_scale"] == 1.5
    assert payload["denoising_strength"] == 0.4
    assert payload["do_not_save_samples"] is True
    assert payload["do_not_save_grid"] is True
    assert payload["sd_model"] == "model-a.safetensors"
    assert payload["sd_vae"] == "vae-a.safetensors"
    assert payload["sampler_name"] == "DPM++ 2M"
    assert payload["scheduler"] == "Karras"


def test_sampler_scheduler_payload_with_explicit_scheduler():
    payload = build_sampler_scheduler_payload("DPM++ 2M", "Karras")
    assert payload["sampler_name"] == "DPM++ 2M Karras"
    assert payload["scheduler"] == "Karras"


def test_sampler_scheduler_payload_without_scheduler():
    for raw in (None, "", "None", "none", "Automatic", "automatic"):
        payload = build_sampler_scheduler_payload("DPM++ 2M", raw)
        assert payload["sampler_name"] == "DPM++ 2M"
        assert "scheduler" not in payload
