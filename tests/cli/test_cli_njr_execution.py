from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

from src import cli
from src.pipeline.cli_njr_builder import build_cli_njr


def _base_config() -> dict[str, object]:
    return {
        "txt2img": {
            "steps": 24,
            "cfg_scale": 6.5,
            "width": 640,
            "height": 832,
            "sampler_name": "Euler a",
            "scheduler": "Karras",
            "negative_prompt": "bad anatomy",
            "model": "model-a.safetensors",
            "vae": "vae-a.safetensors",
            "enable_hr": True,
        },
        "img2img": {"steps": 10, "denoising_strength": 0.3},
        "adetailer": {"adetailer_model": "face_yolov8n.pt"},
        "upscale": {"upscaler": "4x-UltraSharp"},
        "aesthetic": {"enabled": True, "text": "cinematic"},
        "pipeline": {
            "txt2img_enabled": True,
            "img2img_enabled": True,
            "adetailer_enabled": True,
            "upscale_enabled": True,
        },
        "video": {"fps": 12},
        "api": {"base_url": "http://127.0.0.1:7860", "timeout": 30},
    }


def test_build_cli_njr_creates_canonical_stage_chain() -> None:
    record = build_cli_njr(
        prompt="test prompt",
        config=_base_config(),
        batch_size=3,
        run_name="cli-run",
    )

    assert record.job_id == "cli-run"
    assert record.images_per_prompt == 3
    assert record.run_mode == "QUEUE"
    assert record.queue_source == "RUN_NOW"
    assert [stage.stage_type for stage in record.stage_chain] == [
        "txt2img",
        "img2img",
        "adetailer",
        "upscale",
    ]
    assert record.config["model"] == "model-a.safetensors"
    assert record.config["pipeline"]["img2img_enabled"] is True
    assert record.config["aesthetic"]["enabled"] is True


def test_build_cli_njr_omits_inactive_txt2img_hires_fields() -> None:
    config = _base_config()
    config["txt2img"].update(
        {
            "enable_hr": False,
            "hr_scale": 1.5,
            "hr_upscaler": "Latent",
            "denoising_strength": 0.4,
            "hr_second_pass_steps": 8,
        }
    )
    config["hires_fix"] = {
        "enabled": False,
        "upscale_factor": 1.5,
        "upscaler_name": "Latent",
        "denoise": 0.4,
        "steps": 8,
    }

    record = build_cli_njr(
        prompt="test prompt",
        config=config,
        batch_size=1,
        run_name="cli-run",
    )

    assert record.config["enable_hr"] is False
    assert "hr_scale" not in record.config
    assert "hr_upscaler" not in record.config
    assert "denoising_strength" not in record.config
    assert "hr_second_pass_steps" not in record.config
    assert record.config["hires_fix"]["denoise"] == 0.4
    assert record.stage_chain[0].denoising_strength is None


class _FakeConfigManager:
    def __init__(self) -> None:
        self._config = _base_config()

    def load_preset(self, _name: str) -> dict[str, object]:
        return _base_config()

    def get_default_config(self) -> dict[str, object]:
        return _base_config()


class _FakeClient:
    def __init__(self, *, base_url: str, timeout: int) -> None:
        self.base_url = base_url
        self.timeout = timeout

    def check_api_ready(self) -> bool:
        return True


def test_cli_main_uses_pipeline_runner(monkeypatch, tmp_path: Path) -> None:
    captured: dict[str, object] = {}

    class _FakeRunner:
        def __init__(self, _client, _logger) -> None:
            pass

        def run_njr(self, njr, cancel_token=None):
            captured["record"] = njr
            captured["cancel_token"] = cancel_token
            return SimpleNamespace(
                success=True,
                error=None,
                run_id="cli-job",
                metadata={"output_dir": str(tmp_path / "run")},
                variants=[{"stage": "txt2img", "all_paths": [str(tmp_path / "run" / "image.png")]}],
            )

    monkeypatch.setattr(cli, "ConfigManager", _FakeConfigManager)
    monkeypatch.setattr(cli, "SDWebUIClient", _FakeClient)
    monkeypatch.setattr(cli, "PipelineRunner", _FakeRunner)
    monkeypatch.setattr(cli, "setup_logging", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(cli, "find_webui_api_port", lambda: None)
    monkeypatch.setattr(
        "sys.argv",
        [
            "stablenew",
            "--prompt",
            "cli prompt",
            "--preset",
            "default",
            "--batch-size",
            "2",
            "--run-name",
            "approved-run",
            "--no-img2img",
            "--no-upscale",
        ],
    )

    assert cli.main() == 0
    record = captured["record"]
    assert record.images_per_prompt == 2
    assert [stage.stage_type for stage in record.stage_chain] == ["txt2img", "adetailer"]
    assert record.positive_prompt == "cli prompt"
    assert record.job_id == "approved-run"
    assert captured["cancel_token"] is None


def test_cli_main_create_video_prefers_final_stage_artifacts(monkeypatch, tmp_path: Path) -> None:
    captured: dict[str, object] = {}

    class _FakeRunner:
        def __init__(self, _client, _logger) -> None:
            pass

        def run_njr(self, _njr, cancel_token=None):
            return SimpleNamespace(
                success=True,
                error=None,
                run_id="cli-job",
                metadata={"output_dir": str(tmp_path / "run")},
                variants=[
                    {"stage": "txt2img", "all_paths": [str(tmp_path / "run" / "txt.png")]},
                    {"stage": "upscale", "path": str(tmp_path / "run" / "up.png")},
                ],
            )

    class _FakeVideoCreator:
        def create_video_from_images(self, image_paths, output_path, fps=24):
            captured["image_paths"] = [Path(path) for path in image_paths]
            captured["output_path"] = output_path
            captured["fps"] = fps
            return True

    monkeypatch.setattr(cli, "ConfigManager", _FakeConfigManager)
    monkeypatch.setattr(cli, "SDWebUIClient", _FakeClient)
    monkeypatch.setattr(cli, "PipelineRunner", _FakeRunner)
    monkeypatch.setattr(cli, "VideoCreator", _FakeVideoCreator)
    monkeypatch.setattr(cli, "setup_logging", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(cli, "find_webui_api_port", lambda: None)
    monkeypatch.setattr(
        "sys.argv",
        [
            "stablenew",
            "--prompt",
            "cli prompt",
            "--preset",
            "default",
            "--create-video",
        ],
    )

    assert cli.main() == 0
    assert captured["image_paths"] == [tmp_path / "run" / "up.png"]
    assert captured["fps"] == 12
    assert captured["output_path"] == tmp_path / "run" / "video" / "cli_video.mp4"
