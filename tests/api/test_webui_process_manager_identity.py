"""PR-IMG-FORGE-100: one WebUI-family manager, with an explicit declared runtime identity."""

from __future__ import annotations

from pathlib import Path

import src.api.webui_process_manager as manager_module
from src.api.webui_process_manager import WebUIProcessConfig, WebUIProcessManager


def test_config_defaults_to_the_legacy_a1111_identity() -> None:
    assert WebUIProcessConfig(command=["webui.bat"]).runtime_identity == "a1111_webui"
    assert WebUIProcessManager(WebUIProcessConfig(command=["x"])).runtime_identity == "a1111_webui"


def test_manager_exposes_the_configured_identity_without_launching_anything() -> None:
    manager = WebUIProcessManager(
        WebUIProcessConfig(command=["launch"], runtime_identity="forge_webui")
    )
    assert manager.runtime_identity == "forge_webui"
    assert manager.owns_process is False and manager.is_running() is False
    assert manager.get_status()["runtime_identity"] == "forge_webui"


def test_there_is_no_second_webui_family_process_manager() -> None:
    assert not hasattr(manager_module, "ForgeProcessManager")
    assert not Path("src/api/forge_process_manager.py").exists()


def test_default_config_carries_the_configured_identity(monkeypatch, tmp_path: Path) -> None:
    workdir = tmp_path / "webui"
    workdir.mkdir()
    (workdir / "webui.bat").write_text("")
    (workdir / "webui.sh").write_text("")

    class _Settings:
        def load_settings(self) -> dict[str, object]:
            return {
                "webui_workdir": str(workdir),
                "webui_base_url": "http://127.0.0.1:7861",
                "webui_runtime_identity": "forge_webui",
            }

    import src.config.app_config as app_config
    import src.utils.config as config_module

    monkeypatch.setattr(config_module, "ConfigManager", lambda *a, **k: _Settings())
    monkeypatch.setattr(app_config, "resolve_webui_launch_command", lambda _p: ["webui.bat"])
    monkeypatch.setattr(manager_module, "_save_webui_cache", lambda _cache: None)
    monkeypatch.delenv("STABLENEW_WEBUI_RUNTIME_IDENTITY", raising=False)

    config = manager_module.build_default_webui_process_config()

    assert config is not None
    assert config.runtime_identity == "forge_webui"
    assert config.base_url == "http://127.0.0.1:7861"
