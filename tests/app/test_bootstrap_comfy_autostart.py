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


def test_bootstrap_comfy_unmanaged_probe_is_soft_when_unavailable(monkeypatch) -> None:
    checker = mock.Mock(side_effect=RuntimeError("connection refused"))
    logger = mock.Mock()
    monkeypatch.setattr(main, "wait_for_comfy_ready", checker)
    monkeypatch.setattr(main, "logging", logger)

    result = main.bootstrap_comfy({"comfy_base_url": "http://127.0.0.1:8188"})

    assert result is None
    logger.info.assert_any_call("No ComfyUI configuration available")
    assert any("ComfyUI not available for unmanaged bootstrap probe" in str(call.args[0]) for call in logger.info.call_args_list)


def test_bootstrap_comfy_unmanaged_manager_does_not_raise_when_server_absent(monkeypatch) -> None:
    config = {
        "comfy_base_url": "http://127.0.0.1:8188",
        "process_config": mock.Mock(autostart_enabled=False, startup_timeout_seconds=5.0),
    }
    fake_manager = mock.Mock()
    checker = mock.Mock(side_effect=RuntimeError("connection refused"))
    logger = mock.Mock()
    monkeypatch.setattr(main, "ComfyProcessManager", mock.Mock(return_value=fake_manager))
    monkeypatch.setattr(main, "wait_for_comfy_ready", checker)
    monkeypatch.setattr(main, "logging", logger)

    result = main.bootstrap_comfy(config)

    assert result is fake_manager
    fake_manager.start.assert_not_called()
    assert checker.called
    assert any("ComfyUI not ready at startup; continuing unmanaged" in str(call.args[0]) for call in logger.info.call_args_list)


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


def test_load_comfy_config_uses_process_config_base_url(monkeypatch) -> None:
    proc_config = mock.Mock(
        base_url="http://127.0.0.1:8000",
        command=["python", "main.py"],
        working_dir="C:/ComfyUI",
        autostart_enabled=True,
        startup_timeout_seconds=30.0,
    )
    monkeypatch.setattr(main, "build_default_comfy_process_config", lambda: proc_config)
    monkeypatch.delenv("STABLENEW_COMFY_BASE_URL", raising=False)
    monkeypatch.delenv("STABLENEW_COMFY_COMMAND", raising=False)
    monkeypatch.delenv("STABLENEW_COMFY_WORKDIR", raising=False)
    monkeypatch.delenv("STABLENEW_COMFY_AUTOSTART", raising=False)
    monkeypatch.delenv("STABLENEW_COMFY_TIMEOUT", raising=False)

    config = main._load_comfy_config()

    assert config["comfy_base_url"] == "http://127.0.0.1:8000"
    assert config["process_config"] is proc_config
