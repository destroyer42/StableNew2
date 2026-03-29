from unittest import mock

from src import main
from src.api.webui_process_manager import build_default_webui_process_config


def test_bootstrap_autostart_invokes_process_manager(monkeypatch):
    config = {
        "webui_autostart_enabled": True,
        "webui_command": ["python", "webui.py"],
        "webui_base_url": "http://127.0.0.1:7860",
        "webui_startup_timeout_seconds": 0.5,
    }

    started = mock.Mock()
    waited = mock.Mock()

    fake_manager = mock.Mock()
    fake_manager.start.side_effect = started
    monkeypatch.setattr(main, "WebUIProcessManager", mock.Mock(return_value=fake_manager))
    monkeypatch.setattr(main, "wait_for_webui_ready", waited)

    main.bootstrap_webui(config)

    fake_manager.start.assert_called_once()
    waited.assert_called_once_with("http://127.0.0.1:7860", timeout=0.5, poll_interval=0.5)


def test_bootstrap_checks_health_when_disabled(monkeypatch):
    config = {"webui_autostart_enabled": False, "webui_base_url": "http://127.0.0.1:7860"}
    checker = mock.Mock()
    monkeypatch.setattr(main, "wait_for_webui_ready", checker)

    main.bootstrap_webui(config)

    checker.assert_called_once()


def test_async_bootstrap_uses_daemon_thread(monkeypatch):
    recorded = {}

    class _FakeRegistry:
        def spawn(self, **kwargs):
            recorded.update(kwargs)
            return mock.Mock()

    monkeypatch.setattr("src.utils.thread_registry.get_thread_registry", lambda: _FakeRegistry())

    main._async_bootstrap_webui(mock.Mock(), mock.Mock(), mock.Mock())

    assert recorded["name"] == "WebUI-Bootstrap"
    assert recorded["daemon"] is True
    assert recorded["suppress_daemon_warning"] is True


def test_build_default_webui_process_config_prefers_persisted_settings(monkeypatch, tmp_path):
    workdir = tmp_path / "webui"
    workdir.mkdir()
    (workdir / "webui-user.bat").write_text("@echo off\n", encoding="utf-8")

    fake_manager = mock.Mock()
    fake_manager.load_settings.return_value = {
        "webui_workdir": str(workdir),
        "webui_base_url": "http://127.0.0.1:9999",
        "webui_autostart_enabled": True,
        "webui_health_total_timeout_seconds": 45.0,
    }

    monkeypatch.setattr("src.utils.config.ConfigManager", lambda: fake_manager)
    monkeypatch.setattr("src.api.webui_process_manager._load_webui_cache", lambda: {})
    monkeypatch.setattr("src.config.app_config.get_webui_launch_profile", lambda: "standard")
    monkeypatch.setattr(
        "src.config.app_config.resolve_webui_launch_command",
        lambda _profile: ["webui-user.bat"],
    )
    monkeypatch.setattr("src.config.app_config.is_webui_autostart_enabled", lambda: False)
    monkeypatch.setattr(
        "src.config.app_config.get_webui_health_total_timeout_seconds",
        lambda: 60.0,
    )

    config = build_default_webui_process_config()

    assert config is not None
    assert config.working_dir == str(workdir)
    assert config.command == ["webui-user.bat"]
    assert config.autostart_enabled is True
    assert config.base_url == "http://127.0.0.1:9999"
    assert config.startup_timeout_seconds == 45.0


def test_load_webui_config_uses_process_config_base_url(monkeypatch) -> None:
    proc_config = mock.Mock(
        base_url="http://127.0.0.1:7861",
        command=["webui-user.bat"],
        working_dir="C:/webui",
        autostart_enabled=True,
        startup_timeout_seconds=45.0,
    )
    monkeypatch.setattr(main, "build_default_webui_process_config", lambda: proc_config)
    monkeypatch.delenv("STABLENEW_WEBUI_BASE_URL", raising=False)
    monkeypatch.delenv("STABLENEW_WEBUI_COMMAND", raising=False)
    monkeypatch.delenv("STABLENEW_WEBUI_WORKDIR", raising=False)
    monkeypatch.delenv("STABLENEW_WEBUI_AUTOSTART", raising=False)
    monkeypatch.delenv("STABLENEW_WEBUI_TIMEOUT", raising=False)

    config = main._load_webui_config()

    assert config["webui_base_url"] == "http://127.0.0.1:7861"
    assert config["process_config"] is proc_config
