from unittest import mock

from src.api.healthcheck import WebUIHealthCheckTimeout
from src.controller.webui_connection_controller import (
    WebUIConnectionController,
    WebUIConnectionState,
)


def _build_controller(monkeypatch, results, *, retry_count=1):
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
        lambda: object(),
    )
    monkeypatch.setattr(
        "src.controller.webui_connection_controller.app_config.get_webui_autostart_enabled",
        lambda: True,
    )
    monkeypatch.setattr(
        "src.controller.webui_connection_controller.app_config.get_webui_health_initial_timeout_seconds",
        lambda: 0.01,
    )
    monkeypatch.setattr(
        "src.controller.webui_connection_controller.app_config.get_webui_health_retry_count",
        lambda: retry_count,
    )
    monkeypatch.setattr(
        "src.controller.webui_connection_controller.app_config.get_webui_health_retry_interval_seconds",
        lambda: 0.01,
    )
    monkeypatch.setattr(
        "src.controller.webui_connection_controller.app_config.get_webui_health_total_timeout_seconds",
        lambda: 0.01,
    )
    monkeypatch.setattr(
        "src.controller.webui_connection_controller.time.sleep", lambda *args, **kwargs: None
    )
    ctrl = WebUIConnectionController(base_url_provider=lambda: "http://test")
    return ctrl, calls, fake_pm


def test_ensure_connected_uses_strict_healthcheck(monkeypatch):
    ctrl, calls, fake_pm = _build_controller(
        monkeypatch,
        [WebUIHealthCheckTimeout("timeout"), True],
        retry_count=1,
    )

    state = ctrl.ensure_connected(autostart=True)

    assert state == WebUIConnectionState.READY
    assert fake_pm.return_value.start.called
    assert len(calls) >= 2


def test_ensure_connected_does_not_mark_ready_when_healthcheck_times_out(monkeypatch):
    ctrl, calls, fake_pm = _build_controller(
        monkeypatch, [WebUIHealthCheckTimeout("timeout")], retry_count=0
    )

    state = ctrl.ensure_connected(autostart=False)

    assert state == WebUIConnectionState.ERROR
    assert not fake_pm.return_value.start.called
    assert len(calls) == 1
