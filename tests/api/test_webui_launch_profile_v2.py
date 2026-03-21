from __future__ import annotations

from src.api.webui_process_manager import build_default_webui_process_config
from src.config import app_config


def test_resolve_webui_launch_command_supports_guarded_profiles() -> None:
    assert "--medvram-sdxl" in app_config.resolve_webui_launch_command("sdxl_guarded")
    assert "--medvram" in app_config.resolve_webui_launch_command("low_memory")
    assert "--medvram-sdxl" not in app_config.resolve_webui_launch_command("standard")


def test_build_default_webui_process_config_carries_launch_profile(monkeypatch, tmp_path) -> None:
    monkeypatch.setattr("src.api.webui_process_manager._load_webui_cache", lambda: {})
    monkeypatch.setattr("src.api.webui_process_manager.detect_default_webui_workdir", lambda *args, **kwargs: None)
    monkeypatch.setattr(app_config, "get_webui_workdir", lambda: str(tmp_path))
    monkeypatch.setattr(app_config, "get_webui_command", lambda: ["webui-user.bat", "--api", "--xformers", "--medvram-sdxl"])
    monkeypatch.setattr(app_config, "get_webui_launch_profile", lambda: "sdxl_guarded")
    monkeypatch.setattr(app_config, "is_webui_autostart_enabled", lambda: True)

    config = build_default_webui_process_config()

    assert config is not None
    assert config.launch_profile == "sdxl_guarded"
    assert "--medvram-sdxl" in config.command


def test_recommend_webui_launch_profile_for_heavy_sdxl_chain() -> None:
    recommended = app_config.recommend_webui_launch_profile_for_workload(
        model_name="juggernautXL_ragnarokBy.safetensors",
        stage_name="txt2img",
        width=1024,
        height=1536,
        batch_size=1,
        steps=30,
        downstream_stages=["adetailer", "upscale"],
    )

    assert recommended == "sdxl_guarded"


def test_recommend_webui_launch_profile_keeps_light_jobs_standard() -> None:
    recommended = app_config.recommend_webui_launch_profile_for_workload(
        model_name="juggernautXL_ragnarokBy.safetensors",
        stage_name="txt2img",
        width=768,
        height=1024,
        batch_size=1,
        steps=20,
        downstream_stages=[],
    )

    assert recommended == "standard"


def test_low_memory_profile_counts_as_guarded() -> None:
    assert app_config.is_guarded_webui_launch_profile("low_memory") is True
