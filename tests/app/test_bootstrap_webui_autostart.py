from unittest import mock

from src import main


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
