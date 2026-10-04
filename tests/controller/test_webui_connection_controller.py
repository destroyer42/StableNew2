from unittest import mock

from src.controller.webui_connection_controller import (
    WebUIConnectionController,
    WebUIConnectionState,
)


def make_controller(monkeypatch, results, *, detected_url=None):
    """Build a controller whose readiness, autostart, sleep and autodiscovery are all faked.

    ``find_webui_port`` scans real loopback ports, so it is replaced by a recording fake;
    ``controller.autodiscovery_calls`` shows whether the controller reached that stage.
    """
    calls = []
    autodiscovery_calls = []

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

    def fake_find_webui_port(*args, **kwargs):
        autodiscovery_calls.append((args, kwargs))
        return detected_url

    # ensure_connected imports find_webui_port from the healthcheck module at call time.
    monkeypatch.setattr("src.api.healthcheck.find_webui_port", fake_find_webui_port)
    ctrl = WebUIConnectionController(base_url_provider=lambda: "http://x")
    ctrl.autodiscovery_calls = autodiscovery_calls
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
    pm.assert_called_once()  # managed start was attempted after the initial probe failed
    assert len(calls) >= 2  # initial probe plus at least one configured retry
    assert len(ctrl.autodiscovery_calls) == 1  # discovery ran (faked) and found nothing
    snapshot = ctrl.get_last_connection_timing_snapshot()
    assert snapshot is not None
    assert snapshot["state"] == WebUIConnectionState.ERROR.value
    assert snapshot["autostart_invoked"] is True
    assert snapshot["retry_attempts_used"] >= 1
    assert "detected_url" not in snapshot
    assert ctrl.get_base_url() == "http://x"


def test_ensure_connected_uses_alternate_endpoint_found_by_autodiscovery(monkeypatch):
    # fast probe and every configured retry fail; the alternate endpoint is then ready
    retry_count = 2
    monkeypatch.setattr(
        "src.controller.webui_connection_controller.app_config.get_webui_health_retry_count",
        lambda: retry_count,
    )
    ctrl, calls, pm = make_controller(
        monkeypatch,
        [False] * (1 + retry_count) + [True],
        detected_url="http://x:7861",
    )
    state = ctrl.ensure_connected(autostart=True)
    assert state == WebUIConnectionState.READY
    assert len(ctrl.autodiscovery_calls) == 1
    assert calls[-1][0] == "http://x:7861"
    assert ctrl.get_base_url() == "http://x:7861"
    snapshot = ctrl.get_last_connection_timing_snapshot()
    assert snapshot is not None
    assert snapshot["state"] == WebUIConnectionState.READY.value
    assert snapshot["detected_url"] == "http://x:7861"
