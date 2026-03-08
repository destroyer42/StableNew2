import types
from unittest import mock

import pytest

from src.api.webui_process_manager import WebUIProcessConfig, WebUIProcessManager, WebUIStartupError
from tests.helpers.webui_mocks import DummyProcess


def test_start_invokes_subprocess_with_config(monkeypatch):
    dummy = DummyProcess()
    popen_mock = mock.Mock(return_value=dummy)
    monkeypatch.setattr("subprocess.Popen", popen_mock)
    monkeypatch.setattr(
        "src.api.webui_process_manager.build_process_container",
        mock.Mock(return_value=mock.Mock()),
    )

    cfg = WebUIProcessConfig(
        command=["python", "webui.py"], working_dir="/tmp/webui", env_overrides={"A": "1"}
    )
    manager = WebUIProcessManager(cfg)
    manager._start_orphan_monitor = mock.Mock()

    process = manager.start()

    assert process is dummy
    kwargs = popen_mock.call_args.kwargs
    assert kwargs["cwd"] == "/tmp/webui"
    assert kwargs["env"].get("A") == "1"


def test_start_windows_bat_uses_cmd_wrapper_without_shell(monkeypatch):
    dummy = DummyProcess()
    popen_mock = mock.Mock(return_value=dummy)
    monkeypatch.setattr("subprocess.Popen", popen_mock)
    monkeypatch.setattr("src.api.webui_process_manager.os.name", "nt", raising=False)
    monkeypatch.setattr(
        "src.api.webui_process_manager.build_process_container",
        mock.Mock(return_value=mock.Mock()),
    )

    cfg = WebUIProcessConfig(command=["webui-user.bat", "--api"], working_dir="C:/webui")
    manager = WebUIProcessManager(cfg)
    manager._start_orphan_monitor = mock.Mock()
    manager.start()

    args = popen_mock.call_args.args
    kwargs = popen_mock.call_args.kwargs
    assert args[0][:4] == ["cmd.exe", "/d", "/s", "/c"]
    assert kwargs["shell"] is False
    # Ensure breakaway flag is NOT present (0x01000000)
    assert (kwargs["creationflags"] & 0x01000000) == 0


def test_start_attaches_pid_to_process_container(monkeypatch):
    dummy = DummyProcess()
    popen_mock = mock.Mock(return_value=dummy)
    monkeypatch.setattr("subprocess.Popen", popen_mock)
    container = mock.Mock()
    monkeypatch.setattr(
        "src.api.webui_process_manager.build_process_container",
        mock.Mock(return_value=container),
    )

    manager = WebUIProcessManager(WebUIProcessConfig(command=["python", "webui.py"]))
    manager._start_orphan_monitor = mock.Mock()
    manager.start()

    container.add_pid.assert_called_once_with(dummy.pid)


def test_start_raises_structured_error(monkeypatch):
    popen_mock = mock.Mock(side_effect=RuntimeError("boom"))
    monkeypatch.setattr("subprocess.Popen", popen_mock)

    manager = WebUIProcessManager(WebUIProcessConfig(command=["bad"]))

    with pytest.raises(WebUIStartupError):
        manager.start()


def test_stop_handles_already_exited_process(monkeypatch):
    dummy = DummyProcess()
    dummy.poll = types.MethodType(lambda self: 1, dummy)
    popen_mock = mock.Mock(return_value=dummy)
    monkeypatch.setattr("subprocess.Popen", popen_mock)

    manager = WebUIProcessManager(WebUIProcessConfig(command=["python", "webui.py"]))
    manager.start()

    # Process reports exit code; stop should not raise
    manager.stop()
    assert dummy.terminated is False


def test_ensure_running_reuses_running_process(monkeypatch):
    cfg = WebUIProcessConfig(command=["python", "webui.py"])
    manager = WebUIProcessManager(cfg)
    manager._process = DummyProcess()
    check_calls = []
    manager.check_health = lambda: check_calls.append(True) or True
    start_mock = mock.Mock()
    manager.start = start_mock

    assert manager.ensure_running()
    start_mock.assert_not_called()
    assert len(check_calls) == 1


def test_ensure_running_restarts_when_unhealthy(monkeypatch):
    cfg = WebUIProcessConfig(command=["python", "webui.py"])
    manager = WebUIProcessManager(cfg)
    manager._process = DummyProcess()

    call_count = {"n": 0}

    def check_health():
        call_count["n"] += 1
        return call_count["n"] > 1

    manager.check_health = check_health
    stop_mock = mock.Mock()
    start_mock = mock.Mock()
    manager.stop = stop_mock
    manager.start = start_mock

    assert manager.ensure_running()
    stop_mock.assert_called_once()
    start_mock.assert_called_once()
    assert call_count["n"] == 2


def test_ensure_running_checks_health_after_start(monkeypatch):
    cfg = WebUIProcessConfig(command=["python", "webui.py"])
    manager = WebUIProcessManager(cfg)
    manager._process = None

    dummy = DummyProcess()

    def fake_start():
        manager._process = dummy
        return dummy

    manager.start = fake_start
    check_calls = []

    def fake_check():
        check_calls.append(True)
        return True

    manager.check_health = fake_check

    assert manager.ensure_running()
    assert len(check_calls) == 1


def test_check_health_uses_retries(monkeypatch):
    cfg = WebUIProcessConfig(command=["python", "webui.py"])
    manager = WebUIProcessManager(cfg)
    called = []

    def fake_wait(url, timeout, poll_interval):
        called.append((url, timeout, poll_interval))
        return True

    monkeypatch.setattr("src.api.healthcheck.wait_for_webui_ready", fake_wait)
    monkeypatch.setenv("STABLENEW_WEBUI_BASE_URL", "http://custom:8000")

    assert manager.check_health()
    assert called and called[0][1] == 15.0 and called[0][2] == 3.0
