from __future__ import annotations

from types import SimpleNamespace

from src.api.webui_process_manager import WebUIProcessConfig, WebUIProcessManager


def test_restart_webui_applies_guarded_profile_override(monkeypatch, tmp_path) -> None:
    manager = WebUIProcessManager(
        WebUIProcessConfig(
            command=["webui-user.bat", "--api", "--xformers"],
            working_dir=str(tmp_path),
            launch_profile="standard",
            base_url="http://127.0.0.1:7860",
        )
    )

    monkeypatch.setattr(
        "src.utils.single_instance.SingleInstanceLock.is_gui_running",
        staticmethod(lambda: True),
    )
    monkeypatch.setattr(manager, "stop_webui", lambda *args, **kwargs: True)
    monkeypatch.setattr(manager, "start", lambda: object())

    class _DummyClient:
        def __init__(self, base_url: str) -> None:
            self.base_url = base_url

        def close(self) -> None:
            return None

    class _DummyAPI:
        def __init__(self, client) -> None:
            self.client = client

        def wait_until_true_ready(self, **kwargs) -> None:
            return None

    monkeypatch.setattr("src.api.client.SDWebUIClient", _DummyClient)
    monkeypatch.setattr("src.api.webui_api.WebUIAPI", _DummyAPI)

    assert manager.restart_webui(profile_override="sdxl_guarded", max_attempts=1) is True
    assert manager.get_launch_profile() == "sdxl_guarded"
    assert "--medvram-sdxl" in manager._config.command

