from unittest import mock

from src.controller.webui_connection_controller import (
    WebUIConnectionController,
    WebUIConnectionState,
)


def make_controller(monkeypatch, results):
    calls = []

    def fake_wait(url, timeout=0, poll_interval=0):
        calls.append((url, timeout))
        outcome = results.pop(0)
        if isinstance(outcome, Exception):
            raise outcome
        return outcome

    monkeypatch.setattr(
        "src.controller.webui_connection_controller.wait_for_webui_ready", fake_wait
    )
    fake_pm = mock.Mock()
    fake_pm.return_value.start.return_value = True
    monkeypatch.setattr("src.controller.webui_connection_controller.WebUIProcessManager", fake_pm)
    monkeypatch.setattr(
        "src.controller.webui_connection_controller.build_default_webui_process_config",
        lambda: mock.Mock(),
    )
    monkeypatch.setattr(
        "src.controller.webui_connection_controller.app_config.get_webui_autostart_enabled",
        lambda: True,
    )
    monkeypatch.setattr(
        "src.controller.webui_connection_controller.time.sleep", lambda *args, **kwargs: None
    )
    ctrl = WebUIConnectionController(base_url_provider=lambda: "http://x")
    return ctrl, calls, fake_pm


def test_ensure_connected_already_running(monkeypatch):
    ctrl, calls, pm = make_controller(monkeypatch, [True])
    state = ctrl.ensure_connected(autostart=False)
    assert state == WebUIConnectionState.READY
    pm.assert_not_called()
    assert calls


def test_ensure_connected_autostart_and_retry(monkeypatch):
    ctrl, calls, pm = make_controller(monkeypatch, [False, False, True])
    state = ctrl.ensure_connected(autostart=True)
    assert state == WebUIConnectionState.READY
    pm.assert_called()
    assert len(calls) >= 2


def test_ensure_connected_timeout_sets_error(monkeypatch):
    ctrl, calls, pm = make_controller(monkeypatch, [False, False, False])
    state = ctrl.ensure_connected(autostart=True)
    assert state == WebUIConnectionState.ERROR
