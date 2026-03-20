from __future__ import annotations

from unittest import mock

from src import main


def test_bootstrap_comfy_invokes_process_manager_when_autostart_enabled(monkeypatch) -> None:
    config = {
        "comfy_autostart_enabled": True,
        "comfy_command": ["python", "main.py"],
        "comfy_base_url": "http://127.0.0.1:8188",
        "comfy_startup_timeout_seconds": 0.5,
    }

    fake_manager = mock.Mock()
    monkeypatch.setattr(main, "ComfyProcessManager", mock.Mock(return_value=fake_manager))
    waited = mock.Mock()
    monkeypatch.setattr(main, "wait_for_comfy_ready", waited)

    main.bootstrap_comfy(config)

    fake_manager.start.assert_called_once()
    waited.assert_called_once_with("http://127.0.0.1:8188", timeout=0.5, poll_interval=0.5)


def test_bootstrap_comfy_checks_health_when_process_config_missing(monkeypatch) -> None:
    checker = mock.Mock()
    monkeypatch.setattr(main, "wait_for_comfy_ready", checker)

    result = main.bootstrap_comfy({"comfy_base_url": "http://127.0.0.1:8188"})

    assert result is None
    checker.assert_called_once_with("http://127.0.0.1:8188")


def test_async_bootstrap_comfy_uses_daemon_thread(monkeypatch) -> None:
    recorded = {}

    class _FakeRegistry:
        def spawn(self, **kwargs):
            recorded.update(kwargs)
            return mock.Mock()

    monkeypatch.setattr("src.utils.thread_registry.get_thread_registry", lambda: _FakeRegistry())

    main._async_bootstrap_comfy(mock.Mock(), mock.Mock(), mock.Mock())

    assert recorded["name"] == "ComfyUI-Bootstrap"
    assert recorded["daemon"] is True
    assert recorded["suppress_daemon_warning"] is True
