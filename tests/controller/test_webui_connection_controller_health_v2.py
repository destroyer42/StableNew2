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


def test_ensure_connected_records_timing_snapshot(monkeypatch):
    ctrl, calls, fake_pm = _build_controller(
        monkeypatch,
        [WebUIHealthCheckTimeout("timeout"), True],
        retry_count=1,
    )

    state = ctrl.ensure_connected(autostart=True)
    timing = ctrl.get_last_connection_timing_snapshot()

    assert state == WebUIConnectionState.READY
    assert timing is not None
    assert timing["state"] == "ready"
    assert timing["autostart_invoked"] is True
    assert timing["retry_attempts_used"] == 1
    assert timing["fast_probe_elapsed_ms"] >= 0.0
    assert timing["total_elapsed_ms"] >= 0.0


def test_strict_readiness_accepts_healthy_external_webui(monkeypatch):
    ctrl = WebUIConnectionController(base_url_provider=lambda: "http://test")
    monkeypatch.setattr(ctrl, "is_port_listening", lambda _host, _port: True)
    monkeypatch.setattr(ctrl, "_probe_endpoint", lambda _path: (True, None))

    assert ctrl._process_pid is None
    assert ctrl._evaluate_strict_readiness() == (True, None)


def test_strict_readiness_rejects_dead_owned_webui(monkeypatch):
    ctrl = WebUIConnectionController(base_url_provider=lambda: "http://test")
    ctrl._process_pid = 12345
    monkeypatch.setattr(
        "src.controller.webui_connection_controller.psutil.pid_exists",
        lambda _pid: False,
    )
    monkeypatch.setattr(ctrl, "is_port_listening", lambda _host, _port: True)

    ready, reason = ctrl._evaluate_strict_readiness()

    assert ready is False
    assert reason == "owned process not alive"
    assert ctrl._process_pid == 12345
