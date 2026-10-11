from unittest import mock

from src.api.healthcheck import WebUIHealthCheckTimeout
from src.controller.webui_connection_controller import (
    WebUIConnectionController,
    WebUIConnectionState,
)


def make_controller(monkeypatch, results):
    """Build a controller whose readiness, autostart and sleep are faked.

    ``wait_for_webui_ready`` returns True or raises (it never returns False), so a ``False`` outcome raises the
    timeout it would raise; an exhausted script keeps failing. ``calls`` records every probed URL.
    """
    calls = []

    def fake_wait(url, timeout=0, poll_interval=0):
        calls.append((url, timeout))
        outcome = results.pop(0) if results else False
        if outcome is False:
            raise WebUIHealthCheckTimeout("not ready")
        if isinstance(outcome, Exception):
            raise outcome
        return outcome

    monkeypatch.setattr(
        "src.controller.webui_connection_controller.wait_for_webui_ready", fake_wait
    )
    fake_pm = mock.Mock()
    fake_pm.return_value.start.return_value = True
    fake_pm.return_value.exit_diagnostics.return_value = None  # the owned process is still alive
    fake_pm.return_value.startup_timeout_seconds = 0.05
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
    pm.assert_called_once()  # managed start was attempted after the initial probe failed
    assert len(calls) >= 2  # initial probe plus the bounded owned-startup wait
    assert {url for url, _ in calls} == {"http://x"}  # only the configured endpoint was ever probed
    snapshot = ctrl.get_last_connection_timing_snapshot()
    assert snapshot is not None
    assert snapshot["state"] == WebUIConnectionState.ERROR.value
    assert snapshot["autostart_invoked"] is True
    assert "detected_url" not in snapshot
    assert ctrl.get_base_url() == "http://x"


def test_alternate_port_answering_is_never_probed_or_adopted(monkeypatch):
    """Another WebUI answering elsewhere (for example 7860) must not redirect the configured runtime."""
    from src.api import healthcheck

    probed = []
    real = healthcheck.wait_for_webui_ready
    assert callable(real)
    ctrl, calls, pm = make_controller(monkeypatch, [])
    state = ctrl.ensure_connected(autostart=True)
    probed.extend(url for url, _ in calls)
    assert state == WebUIConnectionState.ERROR
    assert set(probed) == {"http://x"}
    assert ctrl.get_base_url() == "http://x"
    assert not hasattr(healthcheck, "find_webui_port")
