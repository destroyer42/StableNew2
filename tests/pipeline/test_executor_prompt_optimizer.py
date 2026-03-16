from __future__ import annotations

from pathlib import Path
from typing import Any

from src.pipeline.executor import Pipeline
from src.utils import StructuredLogger


class _Client:
    options_write_enabled = True

    def generate_images(self, *, stage: str, payload: dict[str, Any]) -> dict[str, Any]:
        self.last_stage = stage
        self.last_payload = dict(payload)
        return {
            "images": ["ignored"],
            "info": {"seed": 123, "subseed": 456, "all_seeds": [123], "all_subseeds": [456]},
        }

    def get_current_model(self) -> str:
        return "model.safetensors"

    def get_current_vae(self) -> str:
        return "vae.pt"


def _fake_save_image(_data: str, path: Path, metadata_builder=None) -> Path:
    path.write_text("image", encoding="utf-8")
    return path


def test_txt2img_stage_uses_prompt_optimizer_and_records_manifest(
    tmp_path: Path,
    monkeypatch,
) -> None:
    client = _Client()
    pipeline = Pipeline(client=client, structured_logger=StructuredLogger())
    monkeypatch.setattr(pipeline, "_apply_webui_defaults_once", lambda: None)
    monkeypatch.setattr(pipeline, "_ensure_model_and_vae", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(pipeline, "_ensure_hypernetwork", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(
        pipeline,
        "_generate_images",
        lambda _stage, _payload: {
            "images": ["ignored"],
            "info": {"seed": 123, "subseed": 456, "all_seeds": [123], "all_subseeds": [456]},
        },
    )
    monkeypatch.setattr("src.pipeline.executor.save_image_from_base64", _fake_save_image)

    config = {
        "txt2img": {
            "steps": 20,
            "cfg_scale": 7.0,
            "width": 1024,
            "height": 1024,
            "sampler_name": "Euler a",
        },
        "pipeline": {
            "apply_global_positive_txt2img": False,
            "apply_global_negative_txt2img": False,
        },
        "aesthetic": {"enabled": False},
        "prompt_optimizer": {"enabled": True},
    }

    result = pipeline.run_txt2img_stage(
        "masterpiece, beautiful woman, cinematic lighting",
        "watermark, blurry, bad anatomy",
        config,
        tmp_path,
        "prompt_optimizer",
    )

    assert result is not None
    assert result["final_prompt"] == "beautiful woman, cinematic lighting, masterpiece"
    assert result["final_negative_prompt"] == "bad anatomy, blurry, watermark"
    assert result["prompt_optimization"]["positive"]["changed"] is True
    manifest_path = tmp_path / "manifests" / "prompt_optimizer.json"
    assert manifest_path.exists()
    sidecar_path = tmp_path / "manifests" / "prompt_optimizer.prompt_optimization.json"
    assert sidecar_path.exists()


def test_adetailer_stage_respects_prompt_optimizer_opt_out(tmp_path: Path, monkeypatch) -> None:
    client = _Client()
    pipeline = Pipeline(client=client, structured_logger=StructuredLogger())
    monkeypatch.setattr(pipeline, "_ensure_model_and_vae", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(
        pipeline,
        "_load_image_base64",
        lambda _path: "ignored",
    )
    monkeypatch.setattr(
        pipeline,
        "_generate_images",
        lambda _stage, _payload: {
            "images": ["ignored"],
            "info": {"seed": 123, "subseed": 456, "all_seeds": [123], "all_subseeds": [456]},
        },
    )
    monkeypatch.setattr(
        "src.pipeline.executor.save_image_from_base64",
        _fake_save_image,
    )

    input_image = tmp_path / "input.png"
    input_image.write_text("image", encoding="utf-8")
    config = {
        "adetailer_enabled": True,
        "adetailer_prompt": "masterpiece, beautiful woman",
        "adetailer_negative_prompt": "watermark, blurry",
        "prompt_optimizer": {"enabled": True, "opt_out_pipeline_names": ["adetailer"]},
    }

    result = pipeline.run_adetailer(input_image, "unused", "unused", config, tmp_path, image_name="adetailer_case")

    assert result is not None
    assert result["final_prompt"] == "masterpiece, beautiful woman"
    assert result["final_negative_prompt"] == "watermark, blurry"
    assert result["prompt_optimization"]["positive"]["changed"] is False
