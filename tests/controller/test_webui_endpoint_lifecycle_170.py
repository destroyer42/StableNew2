"""PR-RUNTIME-WEBUI-170: managed WebUI endpoint authority, single-flight lifecycle and READY projection.

Real ``WebUIProcessManager`` / ``WebUIConnectionController`` with fake processes and scripted readiness probes. Nothing
is spawned or contacted and nothing waits on a real clock.
"""

from __future__ import annotations

import threading
import time
from types import SimpleNamespace
from unittest import mock

import pytest

from src.api import healthcheck
from src.api import webui_process_manager as wpm
from src.api.healthcheck import WebUIHealthCheckTimeout
from src.api.webui_process_manager import WebUIProcessConfig, WebUIProcessManager
from src.controller.webui_connection_controller import (
    WebUIConnectionController,
    WebUIConnectionState,
)
from tests.helpers.webui_mocks import DummyProcess

FORGE_URL = "http://127.0.0.1:7871"
EXTERNAL_URL = "http://127.0.0.1:7860"


@pytest.fixture(autouse=True)
def _isolated_runtime(monkeypatch):
    wpm.clear_global_webui_process_manager()
    healthcheck.clear_readiness_failure_state()
    monkeypatch.setattr(
        "src.utils.single_instance.SingleInstanceLock.is_gui_running", staticmethod(lambda *a, **k: True)
    )
    monkeypatch.setattr(wpm, "build_process_container", mock.Mock(return_value=mock.Mock()))
    monkeypatch.setattr(WebUIProcessManager, "_start_orphan_monitor", mock.Mock())
    monkeypatch.setattr(WebUIProcessManager, "_configured_endpoint_is_occupied", lambda self: False)
    monkeypatch.setattr(
        "src.controller.webui_connection_controller.time.sleep", lambda *a, **k: None
    )
    for name, value in (
        ("get_webui_autostart_enabled", True),
        ("get_webui_health_initial_timeout_seconds", 0.01),
        ("get_webui_health_retry_interval_seconds", 0.01),
        ("get_webui_health_total_timeout_seconds", 0.05),
    ):
        monkeypatch.setattr(
            f"src.controller.webui_connection_controller.app_config.{name}", lambda value=value: value
        )
    yield
    wpm.clear_global_webui_process_manager()
    healthcheck.clear_readiness_failure_state()


def forge_config(**extra) -> WebUIProcessConfig:
    return WebUIProcessConfig(
        command=["launch-forge"],
        working_dir=None,
        startup_timeout_seconds=extra.pop("startup_timeout_seconds", 60.0),
        autostart_enabled=True,
        base_url=FORGE_URL,
        runtime_identity="forge_webui",
        **extra,
    )


def fake_probe(monkeypatch, behavior):
    """Replace the connection controller's readiness probe; ``behavior(url)`` returns True or raises."""
    seen: list[str] = []

    def probe(url, timeout=0, poll_interval=0):
        seen.append(url)
        return behavior(url)

    monkeypatch.setattr("src.controller.webui_connection_controller.wait_for_webui_ready", probe)
    # Any alternate-port discovery would also reach the healthcheck module's own probe: route it here too so a
    # runtime that answers elsewhere (7860) is genuinely reachable by the code under test.
    monkeypatch.setattr(healthcheck, "wait_for_webui_ready", probe)
    return seen


def not_ready(_url):
    raise WebUIHealthCheckTimeout("not ready")


# -- endpoint authority -------------------------------------------------------------------------------------------------


def test_managed_forge_uses_its_configured_endpoint_even_when_another_webui_answers_7860(monkeypatch):
    monkeypatch.setattr("subprocess.Popen", mock.Mock(return_value=DummyProcess(pid=701)))
    manager = WebUIProcessManager(forge_config(startup_timeout_seconds=0.2))
    controller = WebUIConnectionController(base_url_provider=lambda: FORGE_URL)
    controller.attach_process_manager(manager)
    seen = fake_probe(monkeypatch, lambda url: True if url == EXTERNAL_URL else not_ready(url))

    state = controller.ensure_connected(autostart=True)

    assert state is WebUIConnectionState.ERROR  # the configured runtime never became ready
    assert set(seen) == {FORGE_URL}  # 7860 was never probed, so it could not be adopted
    assert controller.get_base_url() == FORGE_URL
    assert manager.endpoint == FORGE_URL


def test_managed_forge_startup_uses_7871_throughout_and_publishes_one_epoch(monkeypatch):
    monkeypatch.setattr("subprocess.Popen", mock.Mock(return_value=DummyProcess(pid=702)))
    manager = WebUIProcessManager(forge_config())
    controller = WebUIConnectionController(base_url_provider=lambda: FORGE_URL)
    controller.attach_process_manager(manager)
    attempts = {"n": 0}

    def booting_then_ready(url):
        attempts["n"] += 1
        if attempts["n"] <= 2:  # fast probe and the first startup slice: Forge still loading
            raise WebUIHealthCheckTimeout("loading")
        return True

    seen = fake_probe(monkeypatch, booting_then_ready)

    state = controller.ensure_connected(autostart=True)

    assert state is WebUIConnectionState.READY
    assert set(seen) == {FORGE_URL}
    assert manager.ready_epoch == 1 and controller.ready_epoch == 1  # one proof, announced once
    assert controller.get_base_url() == FORGE_URL == manager.endpoint


def test_a_failed_health_check_never_rebinds_any_runtime(monkeypatch):
    monkeypatch.setattr(healthcheck, "wait_for_webui_ready", lambda *a, **k: (_ for _ in ()).throw(RuntimeError("down")))
    for identity, url in (("forge_webui", FORGE_URL), ("a1111_webui", EXTERNAL_URL)):
        config = WebUIProcessConfig(command=["x"], runtime_identity=identity, base_url=url)
        assert WebUIProcessManager(config).check_health() is False
        assert config.base_url == url


# -- single flight ------------------------------------------------------------------------------------------------------


def test_concurrent_launch_requests_start_exactly_one_process(monkeypatch):
    launches = []
    first_inside = threading.Event()
    release = threading.Event()

    def blocking_popen(*args, **kwargs):
        launches.append(1)
        first_inside.set()
        release.wait(5)  # hold the first launcher inside the spawn while the others arrive
        return DummyProcess(pid=703)

    monkeypatch.setattr("subprocess.Popen", mock.Mock(side_effect=blocking_popen))
    manager = WebUIProcessManager(forge_config())
    errors: list[BaseException] = []

    def launch():
        try:
            manager.start()
        except BaseException as exc:  # noqa: BLE001
            errors.append(exc)

    threads = [threading.Thread(target=launch) for _ in range(4)]
    threads[0].start()
    assert first_inside.wait(5)
    for thread in threads[1:]:
        thread.start()
    # Real-clock wait (independent of any patched time.sleep): an unserialized second launcher would spawn here.
    threading.Event().wait(0.3)
    observed_while_held = len(launches)
    release.set()
    for thread in threads:
        thread.join(5)

    assert not errors
    assert observed_while_held == 1
    assert len(launches) == 1


def test_overlapping_connection_attempts_share_one_flight(monkeypatch):
    release = threading.Event()
    entered = threading.Event()
    calls = []

    def probe(url, timeout=0, poll_interval=0):
        calls.append(url)
        entered.set()
        assert release.wait(5)
        return True

    monkeypatch.setattr("src.controller.webui_connection_controller.wait_for_webui_ready", probe)
    controller = WebUIConnectionController(base_url_provider=lambda: FORGE_URL)
    results: list[WebUIConnectionState] = []
    first = threading.Thread(target=lambda: results.append(controller.ensure_connected(autostart=True)))
    first.start()
    assert entered.wait(5)
    second = threading.Thread(target=lambda: results.append(controller.ensure_connected(autostart=True)))
    second.start()
    time.sleep(0.05)
    release.set()
    first.join(5)
    second.join(5)

    assert results == [WebUIConnectionState.READY, WebUIConnectionState.READY]
    assert len(calls) == 1  # the second caller joined the in-flight attempt instead of probing again
    assert controller.ready_epoch == 1


def test_a_ready_callback_reentering_connection_does_not_deadlock(monkeypatch):
    controller = WebUIConnectionController(base_url_provider=lambda: FORGE_URL)
    fake_probe(monkeypatch, lambda url: True)
    seen: list[WebUIConnectionState] = []
    controller.register_on_ready(lambda: seen.append(controller.ensure_connected(autostart=True)))
    outcome: list[WebUIConnectionState] = []
    worker = threading.Thread(target=lambda: outcome.append(controller.ensure_connected(autostart=True)))
    worker.start()
    worker.join(5)

    assert not worker.is_alive()  # no self-deadlock on the attempt's own lock
    assert outcome == [WebUIConnectionState.READY]
    assert seen == [WebUIConnectionState.READY]


# -- stale results ------------------------------------------------------------------------------------------------------


def test_a_stale_failure_cannot_overwrite_a_newer_ready_proof(monkeypatch):
    monkeypatch.setattr("subprocess.Popen", mock.Mock(return_value=DummyProcess(pid=704)))
    manager = WebUIProcessManager(forge_config(startup_timeout_seconds=0.2))
    controller = WebUIConnectionController(base_url_provider=lambda: FORGE_URL)
    controller.attach_process_manager(manager)
    calls = {"n": 0}

    def probe(url, timeout=0, poll_interval=0):
        calls["n"] += 1
        if calls["n"] == 2:
            # Another path (the bootstrap waiter) proves the same owned runtime ready while this attempt is in flight.
            manager.mark_ready(source="startup")
        raise WebUIHealthCheckTimeout("old attempt timed out")

    monkeypatch.setattr("src.controller.webui_connection_controller.wait_for_webui_ready", probe)

    state = controller.ensure_connected(autostart=True)

    assert state is WebUIConnectionState.READY
    assert controller.get_state() is WebUIConnectionState.READY
    assert controller.ready_epoch == 1


def test_a_stale_failure_is_ignored_in_the_window_before_the_ready_epoch_is_announced(monkeypatch):
    controller = WebUIConnectionController(base_url_provider=lambda: FORGE_URL)

    def probe(url, timeout=0, poll_interval=0):
        # The manager thread has published READY but not yet bumped the epoch when this attempt's failure settles.
        controller._set_state(WebUIConnectionState.READY)
        raise WebUIHealthCheckTimeout("old attempt timed out")

    monkeypatch.setattr("src.controller.webui_connection_controller.wait_for_webui_ready", probe)

    assert controller.ensure_connected(autostart=False) is WebUIConnectionState.READY


def test_an_unrelated_failure_still_publishes_error(monkeypatch):
    monkeypatch.setattr("subprocess.Popen", mock.Mock(return_value=DummyProcess(pid=705)))
    manager = WebUIProcessManager(forge_config(startup_timeout_seconds=0.05))
    controller = WebUIConnectionController(base_url_provider=lambda: FORGE_URL)
    controller.attach_process_manager(manager)
    fake_probe(monkeypatch, not_ready)

    assert controller.ensure_connected(autostart=True) is WebUIConnectionState.ERROR


def test_an_explicit_connection_attempt_is_not_defeated_by_stale_probe_backoff(monkeypatch):
    # Two refused connections arm a cooldown that makes wait_for_webui_ready fail instantly for tens of seconds.
    refused = healthcheck.requests.exceptions.ConnectionError("actively refused")
    for _ in range(3):
        healthcheck._record_readiness_failure(FORGE_URL, refused)
    assert healthcheck.get_readiness_failure_state(FORGE_URL)["cooldown_remaining_s"] > 0
    monkeypatch.setattr(healthcheck, "_probe_json_endpoint", lambda url, endpoint, timeout: None)
    controller = WebUIConnectionController(base_url_provider=lambda: FORGE_URL)

    assert controller.ensure_connected(autostart=False) is WebUIConnectionState.READY


# -- owned startup window ------------------------------------------------------------------------------------------------


def _started(monkeypatch, pid):
    popen = mock.Mock(return_value=DummyProcess(pid=pid))
    monkeypatch.setattr("subprocess.Popen", popen)
    manager = WebUIProcessManager(forge_config(startup_timeout_seconds=120.0))
    manager.start()
    return manager, popen


def test_launch_during_a_slow_legitimate_startup_does_not_restart_the_process(monkeypatch):
    manager, popen = _started(monkeypatch, 706)
    stop = mock.Mock()
    monkeypatch.setattr(manager, "stop", stop)
    monkeypatch.setattr(manager, "check_health", lambda: False)  # model still loading: API not up yet
    waited = []
    monkeypatch.setattr(
        wpm, "wait_for_managed_startup", lambda mgr, url, **kw: waited.append((url, kw["timeout_s"]))
    )

    assert manager.ensure_running() is True

    stop.assert_not_called()
    assert popen.call_count == 1
    assert waited and waited[0][0] == FORGE_URL and 0 < waited[0][1] <= 120.0


def test_concurrent_ensure_running_recovers_an_unhealthy_process_once(monkeypatch):
    manager, popen = _started(monkeypatch, 710)
    manager._start_time = time.time() - 10_000
    monkeypatch.setattr(manager, "check_health", lambda: False)
    stops = []
    entered = threading.Event()
    release = threading.Event()

    def blocking_stop():
        stops.append(1)
        entered.set()
        release.wait(5)

    monkeypatch.setattr(manager, "stop", blocking_stop)
    monkeypatch.setattr(manager, "start", mock.Mock())
    results: list[bool] = []
    threads = [threading.Thread(target=lambda: results.append(manager.ensure_running())) for _ in range(3)]
    threads[0].start()
    assert entered.wait(5)
    for thread in threads[1:]:
        thread.start()
    threading.Event().wait(0.3)  # real-clock window in which an unserialized caller would also stop the process
    observed_while_held = len(stops)
    release.set()
    for thread in threads:
        thread.join(5)

    assert observed_while_held == 1
    assert len(results) == 3


def test_an_unhealthy_process_past_its_startup_window_is_still_recovered(monkeypatch):
    manager, popen = _started(monkeypatch, 707)
    manager._start_time = time.time() - 10_000  # far outside the window
    monkeypatch.setattr(manager, "check_health", lambda: False)
    stopped = []
    monkeypatch.setattr(manager, "stop", lambda: stopped.append(1))
    monkeypatch.setattr(manager, "start", mock.Mock())

    manager.ensure_running()

    assert stopped == [1]  # existing bounded recovery is unchanged once the window has elapsed


def test_a_proven_ready_process_is_not_given_startup_grace(monkeypatch):
    manager, _ = _started(monkeypatch, 708)
    manager.mark_ready(source="startup")

    assert manager._within_startup_window() is False


# -- agreement, failure evidence, external ownership ------------------------------------------------------------------


def test_manager_connection_browser_and_client_endpoints_agree_for_managed_forge(monkeypatch):
    from src.api.webui_runtime_identity import effective_webui_base_url
    from src.controller.ports.default_runtime_ports import DefaultImageRuntimePorts

    settings = {"webui_runtime_identity": "forge_webui"}
    monkeypatch.setattr("src.api.webui_runtime_identity.load_backend_settings", lambda *a, **k: settings)
    monkeypatch.delenv("STABLENEW_WEBUI_BASE_URL", raising=False)
    config = wpm.build_default_webui_process_config()
    assert config is not None
    controller = WebUIConnectionController()  # default provider: the same effective endpoint resolution

    # Process manager, connection/browser URL and API-client URL all resolve one configured endpoint.
    assert controller.get_base_url() == effective_webui_base_url() == DefaultImageRuntimePorts.base_url()
    assert config.base_url == controller.get_base_url()
    assert controller.get_base_url().rstrip("/").endswith(":7871")


def test_a_startup_failure_reports_the_actual_exit_and_leaves_evidence(monkeypatch):
    process = DummyProcess(pid=709)
    monkeypatch.setattr("subprocess.Popen", mock.Mock(return_value=process))
    manager = WebUIProcessManager(forge_config())
    controller = WebUIConnectionController(base_url_provider=lambda: FORGE_URL)
    controller.attach_process_manager(manager)

    def probe(url, timeout=0, poll_interval=0):
        manager._stderr_tail.append("RuntimeError: CUDA out of memory")
        process._returncode = 3  # the owned process dies while Forge boots
        raise WebUIHealthCheckTimeout("not ready")

    monkeypatch.setattr("src.controller.webui_connection_controller.wait_for_webui_ready", probe)

    assert controller.ensure_connected(autostart=True) is WebUIConnectionState.ERROR
    error = controller.get_last_connection_timing_snapshot()["error"]
    assert "709" in error and "exit code 3" in error and "forge_webui" in error
    assert "CUDA out of memory" in error


def test_an_occupied_external_endpoint_is_never_launched_over_adopted_or_stopped(monkeypatch):
    monkeypatch.setattr(WebUIProcessManager, "_configured_endpoint_is_occupied", lambda self: True)
    popen = mock.Mock()
    monkeypatch.setattr("subprocess.Popen", popen)
    manager = WebUIProcessManager(forge_config())
    stop = mock.Mock()
    monkeypatch.setattr(manager, "stop", stop)
    controller = WebUIConnectionController(base_url_provider=lambda: FORGE_URL)
    controller.attach_process_manager(manager)
    fake_probe(monkeypatch, not_ready)  # the occupant answers the port but is not a ready WebUI API

    assert controller.ensure_connected(autostart=True) is WebUIConnectionState.ERROR
    popen.assert_not_called()
    stop.assert_not_called()
    assert manager.owns_process is False


# -- READY projection ------------------------------------------------------------------------------------------------------


def test_ready_state_disables_launch_and_retry_controls():
    tk = pytest.importorskip("tkinter")
    from src.gui.status_bar_v2 import StatusBarV2

    try:
        root = tk.Tk()
    except tk.TclError as exc:
        pytest.skip(f"Tkinter not available: {exc}")
    root.withdraw()
    try:
        status = StatusBarV2(root, controller=SimpleNamespace())
        for ready in (WebUIConnectionState.READY, "ready", "connected"):
            status.update_webui_state(ready)
            assert "disabled" in status._launch_button.state()
            assert "disabled" in status._retry_button.state()
        status.update_webui_state(WebUIConnectionState.ERROR)
        assert "disabled" not in status._launch_button.state()
    finally:
        root.destroy()


def test_no_unreachable_alternate_port_discovery_remains():
    from src.controller import app_controller

    assert not hasattr(healthcheck, "find_webui_port")
    assert not hasattr(wpm, "discover_webui_port")
    assert not hasattr(app_controller.AppController, "_create_api_client_with_discovery")
