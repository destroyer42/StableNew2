from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import Mock

from src.pipeline.animatediff_models import AnimateDiffCapability
from src.pipeline.executor import Pipeline


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
    pipeline._ensure_webui_true_ready = lambda: None
    pipeline._check_webui_health_before_stage = lambda stage: None
    pipeline._load_image_base64 = lambda path: _TINY_PNG_BASE64

    def _fake_create_video(self, image_paths, output_path, fps=24, codec="libx264", quality="medium"):
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


def test_run_animatediff_stage_applies_secondary_motion_between_frames_and_encode(tmp_path: Path, monkeypatch) -> None:
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

    def _fake_create_video(self, image_paths, output_path, fps=24, codec="libx264", quality="medium"):
        output_path.write_bytes(b"video")
        return True

    monkeypatch.setattr("src.pipeline.executor._apply_secondary_motion_frame_directory", _fake_apply)
    monkeypatch.setattr("src.pipeline.executor.VideoCreator.create_video_from_images", _fake_create_video)
    monkeypatch.setattr("src.pipeline.executor.write_video_container_metadata", lambda *_args, **_kwargs: True)

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
    pipeline._ensure_webui_true_ready = lambda: None
    pipeline._check_webui_health_before_stage = lambda stage: None

    def _fake_create_video(self, image_paths, output_path, fps=24, codec="libx264", quality="medium"):
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
    sent_payload = client.txt2img.call_args.args[0]
    script_args = sent_payload["alwayson_scripts"]["AnimateDiff"]["args"][0]
    assert script_args["model"] == "mm_sdxl_hs.safetensors"


def test_run_animatediff_stage_defaults_img2img_denoising_strength(tmp_path: Path, monkeypatch) -> None:
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
    pipeline._ensure_webui_true_ready = lambda: None
    pipeline._check_webui_health_before_stage = lambda stage: None
    pipeline._load_image_base64 = lambda path: _TINY_PNG_BASE64

    def _fake_create_video(self, image_paths, output_path, fps=24, codec="libx264", quality="medium"):
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
    sent_payload = client.img2img.call_args.args[0]
    assert sent_payload["denoising_strength"] == 0.3
