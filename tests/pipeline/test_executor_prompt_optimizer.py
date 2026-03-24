from __future__ import annotations

from pathlib import Path
from typing import Any
import json

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


def _allow_runtime(pipeline: Pipeline, monkeypatch) -> None:
    monkeypatch.setattr(
        pipeline,
        "_ensure_runtime_admissible",
        lambda **_kwargs: {"status": "healthy", "reasons": []},
    )


def test_txt2img_stage_uses_prompt_optimizer_and_records_manifest(
    tmp_path: Path,
    monkeypatch,
) -> None:
    client = _Client()
    pipeline = Pipeline(client=client, structured_logger=StructuredLogger())
    _allow_runtime(pipeline, monkeypatch)
    monkeypatch.setattr(pipeline, "_apply_webui_defaults_once", lambda: None)
    monkeypatch.setattr(pipeline, "_ensure_model_and_vae", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(pipeline, "_ensure_hypernetwork", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(
        pipeline,
        "_generate_images_with_progress",
        lambda _stage, _payload, **_kwargs: {
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
    assert result["prompt_optimizer_analysis"]["mode"] == "recommend_only_v1"
    assert result["prompt_optimizer_analysis"]["intent"]["intent_band"] == "portrait"
    assert result["prompt_optimizer_analysis"]["stage_policy"]["mode"] == "auto_safe_fill_v1"
    assert any(
        item["key"] == "sampler_name" and item["action"] == "preserved"
        for item in result["prompt_optimizer_analysis"]["stage_policy"]["preserved_decisions"]
    )
    manifest_path = tmp_path / "manifests" / "prompt_optimizer.json"
    assert manifest_path.exists()
    manifest_payload = json.loads(manifest_path.read_text(encoding="utf-8"))
    assert manifest_payload["prompt_optimizer_analysis"]["mode"] == "recommend_only_v1"
    assert manifest_payload["prompt_optimizer_v3"]["schema"] == "stablenew.prompt-optimizer.v3"
    assert manifest_payload["prompt_optimizer_v3"]["policy"]["stage_policy"]["mode"] == "auto_safe_fill_v1"
    v3_sidecar_path = tmp_path / "manifests" / "prompt_optimizer.prompt_optimizer_v3.json"
    assert v3_sidecar_path.exists()
    v3_sidecar_payload = json.loads(v3_sidecar_path.read_text(encoding="utf-8"))
    assert v3_sidecar_payload == manifest_payload["prompt_optimizer_v3"]
    sidecar_path = tmp_path / "manifests" / "prompt_optimizer.prompt_optimization.json"
    assert sidecar_path.exists()


def test_txt2img_stage_auto_fills_missing_or_auto_policy_keys(tmp_path: Path, monkeypatch) -> None:
    client = _Client()
    pipeline = Pipeline(client=client, structured_logger=StructuredLogger())
    _allow_runtime(pipeline, monkeypatch)
    monkeypatch.setattr(pipeline, "_apply_webui_defaults_once", lambda: None)
    monkeypatch.setattr(pipeline, "_ensure_model_and_vae", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(pipeline, "_ensure_hypernetwork", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(
        pipeline,
        "_generate_images_with_progress",
        lambda _stage, _payload, **_kwargs: {
            "images": ["ignored"],
            "info": {"seed": 123, "subseed": 456, "all_seeds": [123], "all_subseeds": [456]},
        },
    )
    monkeypatch.setattr("src.pipeline.executor.save_image_from_base64", _fake_save_image)

    config = {
        "txt2img": {
            "width": 1024,
            "height": 1024,
            "sampler_name": "AUTO",
            "scheduler": "AUTO",
        },
        "pipeline": {
            "apply_global_positive_txt2img": False,
            "apply_global_negative_txt2img": False,
        },
        "aesthetic": {"enabled": False},
        "prompt_optimizer": {"enabled": True},
    }

    result = pipeline.run_txt2img_stage(
        "masterpiece, beautiful woman, natural skin texture",
        "watermark, blurry",
        config,
        tmp_path,
        "prompt_optimizer_auto",
    )

    assert result is not None
    assert result["config"]["sampler_name"] == "DPM++ 2M"
    assert result["config"]["scheduler"] == "Karras"
    assert result["config"]["steps"] == 28
    assert result["config"]["cfg_scale"] == 6.5
    assert result["prompt_optimizer_v3"]["outputs"]["positive_final"] == "beautiful woman, natural skin texture, masterpiece"
    assert result["prompt_optimizer_analysis"]["stage_policy"]["applied_settings"] == {
        "cfg_scale": 6.5,
        "steps": 28,
        "sampler_name": "DPM++ 2M",
        "scheduler": "Karras",
    }


def test_adetailer_stage_records_stage_policy_auto_fills(tmp_path: Path, monkeypatch) -> None:
    client = _Client()
    pipeline = Pipeline(client=client, structured_logger=StructuredLogger())
    _allow_runtime(pipeline, monkeypatch)
    monkeypatch.setattr(pipeline, "_ensure_model_and_vae", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(pipeline, "_load_image_base64", lambda _path: "ignored")
    monkeypatch.setattr(
        pipeline,
        "_generate_images_with_progress",
        lambda _stage, _payload, **_kwargs: {
            "images": ["ignored"],
            "info": {"seed": 123, "subseed": 456, "all_seeds": [123], "all_subseeds": [456]},
        },
    )
    monkeypatch.setattr("src.pipeline.executor.save_image_from_base64", _fake_save_image)

    input_image = tmp_path / "input.png"
    input_image.write_text("image", encoding="utf-8")
    config = {
        "adetailer_enabled": True,
        "adetailer_prompt": "beautiful woman, natural skin texture",
        "adetailer_negative_prompt": "watermark, blurry",
        "adetailer_sampler": "AUTO",
        "adetailer_scheduler": "AUTO",
        "prompt_optimizer": {"enabled": True},
    }

    result = pipeline.run_adetailer(input_image, "unused", "unused", config, tmp_path, image_name="adetailer_policy")

    assert result is not None
    stage_policy = result["prompt_optimizer_analysis"]["stage_policy"]
    assert stage_policy["applied_settings"]["enable_face_pass"] is True
    assert stage_policy["applied_settings"]["adetailer_sampler"] == "DPM++ 2M"
    assert result["prompt_optimizer_v3"]["policy"]["stage_policy"]["applied_settings"]["enable_face_pass"] is True
    face_args = result["config"]["alwayson_scripts"]["ADetailer"]["args"][2]
    assert face_args["ad_confidence"] == 0.28
    assert face_args["ad_sampler"] == "DPM++ 2M"
    assert face_args["ad_scheduler"] == "Use same scheduler"


def test_adetailer_stage_respects_prompt_optimizer_opt_out(tmp_path: Path, monkeypatch) -> None:
    client = _Client()
    pipeline = Pipeline(client=client, structured_logger=StructuredLogger())
    _allow_runtime(pipeline, monkeypatch)
    monkeypatch.setattr(pipeline, "_ensure_model_and_vae", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(
        pipeline,
        "_load_image_base64",
        lambda _path: "ignored",
    )
    monkeypatch.setattr(
        pipeline,
        "_generate_images_with_progress",
        lambda _stage, _payload, **_kwargs: {
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
    assert result["prompt_optimizer_analysis"]["mode"] == "recommend_only_v1"


def test_adetailer_stage_applies_prompt_patch_before_optimizer(tmp_path: Path, monkeypatch) -> None:
    client = _Client()
    pipeline = Pipeline(client=client, structured_logger=StructuredLogger())
    _allow_runtime(pipeline, monkeypatch)
    monkeypatch.setattr(pipeline, "_ensure_model_and_vae", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(pipeline, "_load_image_base64", lambda _path: "ignored")
    monkeypatch.setattr(
        pipeline,
        "_generate_images_with_progress",
        lambda _stage, _payload, **_kwargs: {
            "images": ["ignored"],
            "info": {"seed": 123, "subseed": 456, "all_seeds": [123], "all_subseeds": [456]},
        },
    )
    monkeypatch.setattr("src.pipeline.executor.save_image_from_base64", _fake_save_image)

    input_image = tmp_path / "input.png"
    input_image.write_text("image", encoding="utf-8")
    config = {
        "adetailer_enabled": True,
        "adetailer_prompt": "masterpiece, beautiful woman, soft face",
        "adetailer_negative_prompt": "watermark, blurry",
        "prompt_optimizer": {"enabled": True},
        "adaptive_refinement": {
            "intent": {"mode": "full"},
            "decision_bundle": {
                "prompt_patch": {
                    "add_positive": ["clear irises"],
                    "remove_positive": ["soft face"],
                    "add_negative": ["blurred eyes"],
                }
            },
        },
    }

    result = pipeline.run_adetailer(
        input_image,
        "unused",
        "unused",
        config,
        tmp_path,
        image_name="adetailer_patch_case",
    )

    assert result is not None
    assert result["final_prompt"] == "beautiful woman, masterpiece, clear irises"
    assert "blurred eyes" in result["final_negative_prompt"]
    assert "blurry" in result["final_negative_prompt"]
    assert "watermark" in result["final_negative_prompt"]
    refinement = result["adaptive_refinement"]
    assert refinement["prompt_patch_provenance"]["positive"]["applied_remove"] == ["soft face"]
    assert refinement["prompt_patch_provenance"]["positive"]["applied_add"] == ["clear irises"]


def test_txt2img_stage_ignores_forbidden_prompt_patch_tokens(tmp_path: Path, monkeypatch) -> None:
    client = _Client()
    pipeline = Pipeline(client=client, structured_logger=StructuredLogger())
    _allow_runtime(pipeline, monkeypatch)
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
        "pipeline": {
            "apply_global_positive_txt2img": False,
            "apply_global_negative_txt2img": False,
        },
        "aesthetic": {"enabled": False},
        "prompt_optimizer": {"enabled": False},
        "adaptive_refinement": {
            "intent": {"mode": "full"},
            "decision_bundle": {
                "prompt_patch": {
                    "add_positive": ["<lora:detail:1>", "embedding:foo", "(sharp eyes:1.2)", "clear irises"],
                }
            },
        },
    }

    result = pipeline.run_txt2img_stage(
        "masterpiece, beautiful woman",
        "watermark",
        config,
        tmp_path,
        "forbidden_prompt_patch",
    )

    assert result is not None
    assert result["final_prompt"] == "masterpiece, beautiful woman, clear irises"
    ignored = result["adaptive_refinement"]["prompt_patch_provenance"]["ignored_patch"]["positive"]
    assert "<lora:detail:1>" in ignored
    assert "embedding:foo" in ignored
    assert "(sharp eyes:1.2)" in ignored
