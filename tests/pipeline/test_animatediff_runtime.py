from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import Mock

import pytest

from src.api.types import GenerateError, GenerateErrorCode, GenerateOutcome
from src.controller.runtime_state import CancellationError, CancelToken
from src.pipeline.animatediff_models import AnimateDiffCapability
from src.pipeline.executor import Pipeline, PipelineStageError

_TINY_PNG_BASE64 = (
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO+aRX0AAAAASUVORK5CYII="
)


def test_run_animatediff_stage_saves_frames_and_video(tmp_path: Path, monkeypatch) -> None:
    client = Mock()
    client.get_animatediff_capability.return_value = AnimateDiffCapability(
        available=True,
        script_name="AnimateDiff",
        motion_modules=["mm_sd_v15_v2.ckpt"],
    )
    client.img2img.return_value = {
        "images": [_TINY_PNG_BASE64, _TINY_PNG_BASE64],
        "info": json.dumps(
            {
                "seed": 123,
                "subseed": 456,
                "extra_generation_params": {"AnimateDiff": {"fps": 12}},
            }
        ),
    }

    pipeline = Pipeline(client, Mock())
    pipeline._generate_images_with_progress = Mock(return_value=client.img2img.return_value)
    pipeline._ensure_webui_true_ready = lambda: None
    pipeline._check_webui_health_before_stage = lambda stage: None
    pipeline._load_image_base64 = lambda path: _TINY_PNG_BASE64

    def _fake_create_video(
        self, image_paths, output_path, fps=24, codec="libx264", quality="medium"
    ):
        output_path.write_bytes(b"video")
        return True

    monkeypatch.setattr(
        "src.pipeline.executor.VideoCreator.create_video_from_images",
        _fake_create_video,
    )
    write_video_container_metadata = Mock(return_value=True)
    monkeypatch.setattr(
        "src.pipeline.executor.write_video_container_metadata",
        write_video_container_metadata,
    )

    result = pipeline.run_animatediff_stage(
        input_image_path=tmp_path / "seed.png",
        prompt="animate this",
        negative_prompt="",
        config={"enabled": True, "motion_module": "mm_sd_v15_v2.ckpt", "fps": 12},
        output_dir=tmp_path,
        image_name="animatediff_test",
    )

    assert result is not None
    pipeline._generate_images_with_progress.assert_called_once()
    assert pipeline._generate_images_with_progress.call_args.args[0] == "img2img"
    assert pipeline._generate_images_with_progress.call_args.kwargs["stage_label"] == "animatediff"
    client.img2img.assert_not_called()
    assert Path(result["video_path"]).exists()
    assert result["frame_count"] == 2
    assert len(result["frame_paths"]) == 2
    manifest_path = tmp_path / "manifests" / "animatediff_test.json"
    assert manifest_path.exists()
    assert result["output_path"] == result["video_path"]
    assert result["output_paths"] == [result["video_path"]]
    assert result["manifest_path"] == str(manifest_path)
    assert result["manifest_paths"] == [str(manifest_path)]
    assert result["count"] == 1
    assert result["artifact"]["schema"] == "stablenew.artifact.v2.6"
    assert result["artifact"]["manifest_path"] == str(manifest_path)
    assert result["artifact"]["primary_path"] == result["video_path"]
    write_video_container_metadata.assert_called_once()
    assert write_video_container_metadata.call_args.args[0] == Path(result["video_path"])


def test_run_animatediff_stage_applies_secondary_motion_between_frames_and_encode(
    tmp_path: Path, monkeypatch
) -> None:
    client = Mock()
    client.get_animatediff_capability.return_value = AnimateDiffCapability(
        available=True,
        script_name="AnimateDiff",
        motion_modules=["mm_sd_v15_v2.ckpt"],
    )
    client.img2img.return_value = {
        "images": [_TINY_PNG_BASE64, _TINY_PNG_BASE64],
        "info": json.dumps(
            {
                "seed": 123,
                "subseed": 456,
                "extra_generation_params": {"AnimateDiff": {"fps": 12}},
            }
        ),
    }

    pipeline = Pipeline(client, Mock())
    pipeline._generate_images_with_progress = Mock(return_value=client.img2img.return_value)
    pipeline._ensure_webui_true_ready = lambda: None
    pipeline._check_webui_health_before_stage = lambda stage: None
    pipeline._load_image_base64 = lambda path: _TINY_PNG_BASE64

    def _fake_apply(*, runtime_block, input_dir, output_dir):
        output_dir.mkdir(parents=True, exist_ok=True)
        first = output_dir / "frame_000000.png"
        second = output_dir / "frame_000001.png"
        first.write_bytes(b"png")
        second.write_bytes(b"png")
        return {
            "status": "applied",
            "application_path": "frame_directory_worker",
            "output_paths": [str(first), str(second)],
        }

    encoded_paths: list[str] = []
    container_payloads: list[dict[str, object]] = []

    def _fake_create_video(
        self, image_paths, output_path, fps=24, codec="libx264", quality="medium"
    ):
        encoded_paths[:] = [str(path) for path in image_paths]
        output_path.write_bytes(b"video")
        return True

    monkeypatch.setattr(
        "src.pipeline.executor._apply_secondary_motion_frame_directory", _fake_apply
    )
    monkeypatch.setattr(
        "src.pipeline.executor.VideoCreator.create_video_from_images", _fake_create_video
    )
    monkeypatch.setattr(
        "src.pipeline.executor.write_video_container_metadata",
        lambda _path, payload: container_payloads.append(dict(payload)) or True,
    )

    result = pipeline.run_animatediff_stage(
        input_image_path=tmp_path / "seed.png",
        prompt="animate this",
        negative_prompt="",
        config={
            "enabled": True,
            "motion_module": "mm_sd_v15_v2.ckpt",
            "fps": 12,
            "secondary_motion": {
                "enabled": True,
                "intent": {"enabled": True, "mode": "apply", "intent": "micro_sway"},
                "policy": {"enabled": True, "policy_id": "animatediff_motion_v1"},
            },
        },
        output_dir=tmp_path,
        image_name="animatediff_motion_test",
    )

    assert result is not None
    assert result["secondary_motion"]["summary"]["status"] == "applied"
    assert result["secondary_motion_summary"]["status"] == "applied"
    assert encoded_paths == [
        str(tmp_path / "animatediff_motion_test_secondary_motion_frames" / "frame_000000.png"),
        str(tmp_path / "animatediff_motion_test_secondary_motion_frames" / "frame_000001.png"),
    ]
    assert container_payloads[0]["secondary_motion_summary"]["status"] == "applied"


def test_run_animatediff_stage_returns_none_when_capability_missing(tmp_path: Path) -> None:
    client = Mock()
    client.get_animatediff_capability.return_value = AnimateDiffCapability(
        available=False,
        reason="missing",
    )

    pipeline = Pipeline(client, Mock())
    pipeline._ensure_webui_true_ready = lambda: None
    pipeline._check_webui_health_before_stage = lambda stage: None

    result = pipeline.run_animatediff_stage(
        input_image_path=None,
        prompt="animate this",
        negative_prompt="",
        config={"enabled": True},
        output_dir=tmp_path,
        image_name="animatediff_missing",
    )

    assert result is None


def test_run_animatediff_stage_auto_selects_sdxl_motion_module(tmp_path: Path, monkeypatch) -> None:
    client = Mock()
    client.get_animatediff_capability.return_value = AnimateDiffCapability(
        available=True,
        script_name="AnimateDiff",
        motion_modules=[],
    )
    client.get_current_model.return_value = "realismFromHadesXL_2ndAnniversary"
    client.txt2img.return_value = {
        "images": [_TINY_PNG_BASE64, _TINY_PNG_BASE64],
        "info": json.dumps(
            {
                "seed": 789,
                "subseed": 101112,
                "extra_generation_params": {"AnimateDiff": "model: mm_sdxl_hs.safetensors"},
            }
        ),
    }

    pipeline = Pipeline(client, Mock())
    pipeline._generate_images_with_progress = Mock(return_value=client.txt2img.return_value)
    pipeline._ensure_webui_true_ready = lambda: None
    pipeline._check_webui_health_before_stage = lambda stage: None

    def _fake_create_video(
        self, image_paths, output_path, fps=24, codec="libx264", quality="medium"
    ):
        output_path.write_bytes(b"video")
        return True

    monkeypatch.setattr(
        "src.pipeline.executor.VideoCreator.create_video_from_images",
        _fake_create_video,
    )
    monkeypatch.setattr(
        "src.pipeline.executor.write_video_container_metadata",
        lambda *_args, **_kwargs: True,
    )

    result = pipeline.run_animatediff_stage(
        input_image_path=None,
        prompt="animate this",
        negative_prompt="",
        config={"enabled": True, "fps": 8, "video_length": 2},
        output_dir=tmp_path,
        image_name="animatediff_sdxl_default",
    )

    assert result is not None
    sent_payload = pipeline._generate_images_with_progress.call_args.args[1]
    script_args = sent_payload["alwayson_scripts"]["AnimateDiff"]["args"][0]
    assert script_args["model"] == "mm_sdxl_hs.safetensors"


def test_run_animatediff_stage_defaults_img2img_denoising_strength(
    tmp_path: Path, monkeypatch
) -> None:
    client = Mock()
    client.get_animatediff_capability.return_value = AnimateDiffCapability(
        available=True,
        script_name="AnimateDiff",
        motion_modules=["mm_sd_v15_v2.ckpt"],
    )
    client.get_current_model.return_value = "stable-diffusion-v1-5"
    client.img2img.return_value = {
        "images": [_TINY_PNG_BASE64, _TINY_PNG_BASE64],
        "info": json.dumps(
            {
                "seed": 123,
                "subseed": 456,
                "extra_generation_params": {"AnimateDiff": "model: mm_sd_v15_v2.ckpt"},
            }
        ),
    }

    pipeline = Pipeline(client, Mock())
    pipeline._generate_images_with_progress = Mock(return_value=client.img2img.return_value)
    pipeline._ensure_webui_true_ready = lambda: None
    pipeline._check_webui_health_before_stage = lambda stage: None
    pipeline._load_image_base64 = lambda path: _TINY_PNG_BASE64

    def _fake_create_video(
        self, image_paths, output_path, fps=24, codec="libx264", quality="medium"
    ):
        output_path.write_bytes(b"video")
        return True

    monkeypatch.setattr(
        "src.pipeline.executor.VideoCreator.create_video_from_images",
        _fake_create_video,
    )
    monkeypatch.setattr(
        "src.pipeline.executor.write_video_container_metadata",
        lambda *_args, **_kwargs: True,
    )

    result = pipeline.run_animatediff_stage(
        input_image_path=tmp_path / "seed.png",
        prompt="animate this",
        negative_prompt="",
        config={"enabled": True, "motion_module": "mm_sd_v15_v2.ckpt", "denoising_strength": None},
        output_dir=tmp_path,
        image_name="animatediff_img2img_default_denoise",
    )

    assert result is not None
    sent_payload = pipeline._generate_images_with_progress.call_args.args[1]
    assert sent_payload["denoising_strength"] == 0.3


def test_run_animatediff_stage_cancel_after_response_skips_artifacts(tmp_path: Path) -> None:
    client = Mock()
    client.get_animatediff_capability.return_value = AnimateDiffCapability(
        available=True,
        script_name="AnimateDiff",
        motion_modules=["mm_sdxl_hs.safetensors"],
    )
    client.get_current_model.return_value = "cyberrealisticXL_v90-16fp.safetensors"
    pipeline = Pipeline(client, Mock())
    pipeline._ensure_webui_true_ready = lambda: None
    pipeline._check_webui_health_before_stage = lambda stage: None
    pipeline._load_image_base64 = lambda path: _TINY_PNG_BASE64
    token = CancelToken()

    def return_then_cancel(stage, payload, **kwargs):
        assert stage == "img2img"
        assert kwargs["stage_label"] == "animatediff"
        assert kwargs["cancel_token"] is token
        token.cancel()
        return {"images": [_TINY_PNG_BASE64] * 8, "info": {}}

    pipeline._generate_images_with_progress = Mock(side_effect=return_then_cancel)

    with pytest.raises(CancellationError, match="animatediff post-call"):
        pipeline.run_animatediff_stage(
            input_image_path=tmp_path / "seed.png",
            prompt="small wave",
            negative_prompt="bad anatomy",
            config={"enabled": True, "video_length": 8, "batch_size": 8},
            output_dir=tmp_path,
            image_name="cancelled_animatediff",
            cancel_token=token,
        )

    pipeline._generate_images_with_progress.assert_called_once()
    client.img2img.assert_not_called()
    assert not list(tmp_path.rglob("*.mp4"))


def test_run_animatediff_stage_builds_eight_frame_sdxl_request(
    tmp_path: Path, monkeypatch
) -> None:
    client = Mock()
    client.get_animatediff_capability.return_value = AnimateDiffCapability(
        available=True,
        script_name="AnimateDiff",
        motion_modules=["mm_sdxl_hs.safetensors"],
    )
    client.get_current_model.return_value = "cyberrealisticXL_v90-16fp.safetensors"
    pipeline = Pipeline(client, Mock())
    pipeline._ensure_model_and_vae = Mock()
    pipeline._ensure_webui_true_ready = lambda: None
    pipeline._check_webui_health_before_stage = lambda stage: None
    pipeline._load_image_base64 = lambda path: _TINY_PNG_BASE64
    pipeline._generate_images_with_progress = Mock(
        return_value={
            "images": [_TINY_PNG_BASE64] * 8,
            "info": {"seed": 1733123036, "extra_generation_params": {"AnimateDiff": "on"}},
        }
    )

    def fake_create_video(self, image_paths, output_path, **kwargs):
        output_path.write_bytes(b"video")
        return True

    monkeypatch.setattr(
        "src.pipeline.executor.VideoCreator.create_video_from_images", fake_create_video
    )
    monkeypatch.setattr(
        "src.pipeline.executor.write_video_container_metadata", lambda *_args, **_kwargs: True
    )
    config = {
        "enabled": True,
        "model": "cyberrealisticXL_v90-16fp.safetensors",
        "vae": "Automatic",
        "seed": 1733123036,
        "width": 512,
        "height": 512,
        "sampler_name": "Euler a",
        "scheduler": "Karras",
        "steps": 20,
        "cfg_scale": 6.0,
        "clip_skip": 2,
        "denoising_strength": 0.30,
        "video_length": 8,
        "fps": 8,
        "batch_size": 8,
        "closed_loop": "N",
        "stride": 1,
        "overlap": -1,
        "format": ["PNG", "Frame"],
    }
    result = pipeline.run_animatediff_stage(
        input_image_path=tmp_path / "source.png",
        prompt="small wave",
        negative_prompt="bad anatomy",
        config=config,
        output_dir=tmp_path,
        image_name="hotshot_payload",
    )

    assert result is not None
    pipeline._ensure_model_and_vae.assert_called_once_with(config["model"], "Automatic")
    pipeline._generate_images_with_progress.assert_called_once()
    stage, payload = pipeline._generate_images_with_progress.call_args.args
    assert stage == "img2img"
    assert pipeline._generate_images_with_progress.call_args.kwargs["stage_label"] == "animatediff"
    assert payload["init_images"] == [_TINY_PNG_BASE64]
    for key in (
        "prompt",
        "negative_prompt",
        "seed",
        "width",
        "height",
        "sampler_name",
        "scheduler",
        "steps",
        "cfg_scale",
        "clip_skip",
        "denoising_strength",
    ):
        expected = {"prompt": "small wave", "negative_prompt": "bad anatomy"}.get(
            key, config.get(key)
        )
        assert payload[key] == expected
    assert payload["batch_size"] == 1
    assert payload["n_iter"] == 1
    assert payload["alwayson_scripts"]["AnimateDiff"]["args"] == [
        {
            "enable": True,
            "model": "mm_sdxl_hs.safetensors",
            "video_length": 8,
            "fps": 8,
            "loop_number": 0,
            "closed_loop": "N",
            "batch_size": 8,
            "stride": 1,
            "overlap": -1,
            "format": ["PNG", "Frame"],
        }
    ]
    client.img2img.assert_not_called()


def test_animatediff_ambiguous_post_is_not_replayed_or_hidden(tmp_path: Path) -> None:
    client = Mock()
    client.get_animatediff_capability.return_value = AnimateDiffCapability(
        available=True,
        script_name="AnimateDiff",
        motion_modules=["mm_sdxl_hs.safetensors"],
    )
    client.get_current_model.return_value = "cyberrealisticXL_v90-16fp.safetensors"
    client.generate_images.return_value = GenerateOutcome(
        error=GenerateError(
            code=GenerateErrorCode.OUTCOME_UNKNOWN,
            message="request may have executed",
            stage="img2img",
        )
    )
    pipeline = Pipeline(client, Mock())
    pipeline._ensure_model_and_vae = Mock()
    pipeline._ensure_webui_true_ready = lambda: None
    pipeline._check_webui_health_before_stage = lambda stage: None
    pipeline._load_image_base64 = lambda path: _TINY_PNG_BASE64
    pipeline._poll_progress_loop = Mock()

    with pytest.raises(PipelineStageError) as error:
        pipeline.run_animatediff_stage(
            input_image_path=tmp_path / "seed.png",
            prompt="small wave",
            negative_prompt="bad anatomy",
            config={"enabled": True, "video_length": 8, "batch_size": 8},
            output_dir=tmp_path,
            image_name="ambiguous_animatediff",
        )

    assert error.value.error.code is GenerateErrorCode.OUTCOME_UNKNOWN
    client.generate_images.assert_called_once()
    client.img2img.assert_not_called()
    assert not list(tmp_path.rglob("*.mp4"))
