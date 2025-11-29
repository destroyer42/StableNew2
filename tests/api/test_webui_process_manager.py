import types
from unittest import mock

import pytest

from src.api.webui_process_manager import WebUIProcessConfig, WebUIProcessManager, WebUIStartupError


class _DummyProcess:
    def __init__(self):
        self.terminated = False
        # Add dummy stdout/stderr streams to avoid AttributeError in manager.start()
        import io
        self.stdout = io.BytesIO(b'')
        self.stderr = io.BytesIO(b'')

    def poll(self):
        return None

    def terminate(self):
        self.terminated = True


def test_start_invokes_subprocess_with_config(monkeypatch):
    dummy = _DummyProcess()
    popen_mock = mock.Mock(return_value=dummy)
    monkeypatch.setattr("subprocess.Popen", popen_mock)

    cfg = WebUIProcessConfig(command=["python", "webui.py"], working_dir="/tmp/webui", env_overrides={"A": "1"})
    manager = WebUIProcessManager(cfg)

    process = manager.start()

    assert process is dummy
    popen_mock.assert_called_once()
    kwargs = popen_mock.call_args.kwargs
    assert kwargs["cwd"] == "/tmp/webui"
    assert kwargs["env"].get("A") == "1"


def test_start_raises_structured_error(monkeypatch):
    popen_mock = mock.Mock(side_effect=RuntimeError("boom"))
    monkeypatch.setattr("subprocess.Popen", popen_mock)

    manager = WebUIProcessManager(WebUIProcessConfig(command=["bad"]))

    with pytest.raises(WebUIStartupError):
        manager.start()


def test_stop_handles_already_exited_process(monkeypatch):
    dummy = _DummyProcess()
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
    manager._process = _DummyProcess()
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
    manager._process = _DummyProcess()

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

    dummy = _DummyProcess()

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
