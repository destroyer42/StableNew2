"""PR-RUNTIME-WEBUI-LIFECYCLE-130: one authoritative managed WebUI lifecycle (manager level).

Covers the process-manager half of the convergence contract: global ownership cannot be stolen, a proven
TRUE-READY restart publishes exactly one readiness epoch and clears only stale readiness backoff, a real
post-recovery failure is still recorded, and a process that exits before readiness reports truthful
diagnostics. No process is spawned, no network is used, no wall-clock waits.
"""

from __future__ import annotations

from unittest import mock

import pytest

from src.api import healthcheck
from src.api import webui_process_manager as wpm
from src.api.webui_process_manager import WebUIProcessConfig, WebUIProcessManager, WebUIStartupError
from tests.helpers.webui_mocks import DummyProcess

URL = "http://127.0.0.1:7871"


@pytest.fixture(autouse=True)
def _clean_lifecycle_state(monkeypatch):
    wpm.clear_global_webui_process_manager()
    healthcheck.clear_readiness_failure_state()
    monkeypatch.setattr(
        "src.utils.single_instance.SingleInstanceLock.is_gui_running", staticmethod(lambda *a, **k: True)
    )
    monkeypatch.setattr(wpm, "build_process_container", mock.Mock(return_value=mock.Mock()))
    monkeypatch.setattr(WebUIProcessManager, "_start_orphan_monitor", mock.Mock())
    monkeypatch.setattr(WebUIProcessManager, "_configured_endpoint_is_occupied", lambda self: False)
    yield
    wpm.clear_global_webui_process_manager()
    healthcheck.clear_readiness_failure_state()


def _config(**extra) -> WebUIProcessConfig:
    return WebUIProcessConfig(
        command=["python", "webui.py"], base_url=URL, runtime_identity="forge_webui", **extra
    )


def _started_manager(monkeypatch, *, pid: int = 4242) -> tuple[WebUIProcessManager, DummyProcess]:
    process = DummyProcess(pid=pid)
    monkeypatch.setattr("subprocess.Popen", mock.Mock(return_value=process))
    manager = WebUIProcessManager(_config())
    manager.start()
    assert manager.owns_process
    return manager, process


# --- B: global ownership -------------------------------------------------------------------------


def test_constructing_an_unowned_manager_never_steals_the_global_from_an_owned_live_manager(monkeypatch):
    owner, _process = _started_manager(monkeypatch)
    assert wpm.get_global_webui_process_manager() is owner

    unrelated = WebUIProcessManager(_config())

    assert not unrelated.owns_process
    assert wpm.get_global_webui_process_manager() is owner


def test_stopping_an_unregistered_manager_does_not_clear_the_owned_global(monkeypatch):
    owner, _process = _started_manager(monkeypatch)
    unrelated = WebUIProcessManager(_config())

    unrelated.stop()

    assert wpm.get_global_webui_process_manager() is owner
    assert owner.owns_process


def test_a_second_manager_cannot_launch_a_duplicate_while_another_owns_a_live_process(monkeypatch):
    _owner, _process = _started_manager(monkeypatch)
    popen = mock.Mock(return_value=DummyProcess(pid=9999))
    monkeypatch.setattr("subprocess.Popen", popen)
    second = WebUIProcessManager(_config())

    with pytest.raises(WebUIStartupError, match="already owns"):
        second.start()

    popen.assert_not_called()
    assert not second.owns_process


def test_a_manager_without_a_live_owner_in_the_global_still_registers_normally():
    first = WebUIProcessManager(_config())
    assert wpm.get_global_webui_process_manager() is first

    second = WebUIProcessManager(_config())

    assert wpm.get_global_webui_process_manager() is second


# --- C/E: recovery establishes one readiness epoch ------------------------------------------------


def _restart_with_true_ready(manager: WebUIProcessManager, *, during_wait=None) -> bool:
    """Run ``restart_webui`` with start/stop faked and TRUE-READY proven by the (patched) helper."""

    api = mock.Mock()
    api.wait_until_true_ready = mock.Mock(side_effect=during_wait)
    with (
        mock.patch.object(manager, "stop_webui"),
        mock.patch.object(manager, "start"),
        mock.patch.object(WebUIProcessManager, "owns_process", mock.PropertyMock(return_value=True)),
        mock.patch("src.api.webui_api.WebUIAPI", return_value=api),
        mock.patch("src.api.webui_process_manager.time.sleep"),
    ):
        return manager.restart_webui(wait_ready=True, max_attempts=1)


def _record_hard_failures(count: int = 2) -> None:
    from requests.exceptions import ConnectionError as RequestsConnectionError

    for _ in range(count):
        healthcheck._record_readiness_failure(URL, RequestsConnectionError("actively refused"))


def test_successful_restart_clears_readiness_backoff_recorded_while_the_runtime_was_restarting():
    manager = WebUIProcessManager(_config())

    # Probes made by other threads while the owned runtime is legitimately down record hard failures AFTER
    # the pre-restart clear. They are stale once TRUE-READY is proven.
    assert _restart_with_true_ready(manager, during_wait=lambda **_kw: _record_hard_failures(2))

    state = healthcheck.get_readiness_failure_state(URL)
    assert state["cooldown_remaining_s"] == 0.0
    assert state["hard_failures"] == 0.0


def test_a_real_failure_after_recovery_is_still_recorded():
    manager = WebUIProcessManager(_config())
    assert _restart_with_true_ready(manager, during_wait=lambda **_kw: _record_hard_failures(2))

    _record_hard_failures(2)  # the runtime fails again after being proven ready

    state = healthcheck.get_readiness_failure_state(URL)
    assert state["hard_failures"] >= 2.0
    assert state["cooldown_remaining_s"] > 0.0


def test_successful_restart_publishes_exactly_one_readiness_epoch_to_listeners():
    manager = WebUIProcessManager(_config())
    events = []
    manager.add_ready_listener(events.append)

    assert _restart_with_true_ready(manager)

    assert len(events) == 1
    assert events[0].epoch == 1 == manager.ready_epoch
    assert events[0].source == "restart"
    assert events[0].runtime_identity == "forge_webui"
    assert events[0].endpoint == URL


def test_failed_restart_publishes_no_readiness_epoch_and_keeps_failure_state():
    from src.api.webui_api import WebUIReadinessTimeout

    manager = WebUIProcessManager(_config())
    events = []
    manager.add_ready_listener(events.append)
    _record_hard_failures(2)

    timeout = WebUIReadinessTimeout(
        message="not ready", total_waited=60.0, checks_status={}, stdout_tail=""
    )
    assert _restart_with_true_ready(manager, during_wait=timeout) is False

    assert events == []
    assert manager.ready_epoch == 0


def test_restart_without_a_readiness_proof_does_not_claim_ready():
    manager = WebUIProcessManager(_config())
    events = []
    manager.add_ready_listener(events.append)

    with (
        mock.patch.object(manager, "stop_webui"),
        mock.patch.object(manager, "start"),
        mock.patch.object(WebUIProcessManager, "owns_process", mock.PropertyMock(return_value=True)),
    ):
        assert manager.restart_webui(wait_ready=False)

    assert events == []


def test_a_listener_added_after_readiness_receives_the_current_epoch_once():
    manager = WebUIProcessManager(_config())
    manager.mark_ready(source="startup")
    late = []

    manager.add_ready_listener(late.append)

    assert [event.epoch for event in late] == [1]


def test_a_failing_listener_never_breaks_readiness_or_other_listeners():
    manager = WebUIProcessManager(_config())
    seen = []
    manager.add_ready_listener(mock.Mock(side_effect=RuntimeError("boom")))
    manager.add_ready_listener(seen.append)

    manager.mark_ready(source="startup")

    assert [event.epoch for event in seen] == [1]


# --- A: startup truth ------------------------------------------------------------------------------


def test_exit_diagnostics_are_none_while_the_process_is_alive(monkeypatch):
    manager, _process = _started_manager(monkeypatch)

    assert manager.exit_diagnostics() is None


def test_exit_diagnostics_report_pid_identity_profile_exit_code_and_a_bounded_output_tail(monkeypatch):
    manager, process = _started_manager(monkeypatch, pid=777)
    for index in range(500):
        manager._stdout_tail.append(f"stdout line {index}")
        manager._stderr_tail.append(f"stderr line {index}")
    process._returncode = 3  # natural exit before readiness

    diagnostics = manager.exit_diagnostics()

    assert diagnostics is not None
    assert diagnostics["pid"] == 777
    assert diagnostics["exit_code"] == 3
    assert diagnostics["runtime_identity"] == "forge_webui"
    assert diagnostics["launch_profile"] == "standard"
    assert diagnostics["endpoint"] == URL
    assert diagnostics["stdout_tail"].splitlines()[-1] == "stdout line 499"
    assert diagnostics["stderr_tail"].splitlines()[-1] == "stderr line 499"
    assert len(diagnostics["stdout_tail"].splitlines()) <= 40
    assert len(diagnostics["stdout_tail"]) <= 4000


def test_startup_wait_reports_an_early_exit_without_waiting_for_the_timeout(monkeypatch):
    manager, process = _started_manager(monkeypatch, pid=31337)
    process._returncode = 1
    probe = mock.Mock(side_effect=healthcheck.WebUIHealthCheckTimeout("not ready"))

    with pytest.raises(WebUIStartupError) as raised:
        wpm.wait_for_managed_startup(manager, URL, timeout_s=60.0, probe=probe)

    message = str(raised.value)
    assert "31337" in message and "exit code 1" in message and "forge_webui" in message
    assert probe.call_count == 1  # one bounded slice, then the exit was reported, not 60 s of polling


def test_startup_timeout_with_a_live_process_keeps_truthful_ownership(monkeypatch):
    manager, _process = _started_manager(monkeypatch)
    clock = {"now": 0.0}

    def probe(url, *, timeout, poll_interval):
        clock["now"] += timeout
        raise healthcheck.WebUIHealthCheckTimeout("not ready")

    monkeypatch.setattr(wpm.time, "monotonic", lambda: clock["now"])

    with pytest.raises(healthcheck.WebUIHealthCheckTimeout):
        wpm.wait_for_managed_startup(manager, URL, timeout_s=12.0, probe=probe)

    assert manager.owns_process  # slow startup is not an ownership loss and nothing was killed
    assert wpm.get_global_webui_process_manager() is manager
    assert manager.ready_epoch == 0


def test_startup_wait_does_not_accumulate_readiness_backoff_while_an_owned_process_boots(monkeypatch):
    manager, _process = _started_manager(monkeypatch)
    clock = {"now": 0.0}
    calls = {"count": 0}

    def probe(url, *, timeout, poll_interval):
        calls["count"] += 1
        clock["now"] += timeout
        if calls["count"] < 4:
            _record_hard_failures(1)  # refused while booting is expected, not a failure
            raise healthcheck.WebUIHealthCheckTimeout("not ready")
        return True

    monkeypatch.setattr(wpm.time, "monotonic", lambda: clock["now"])

    wpm.wait_for_managed_startup(manager, URL, timeout_s=60.0, probe=probe)

    assert healthcheck.get_readiness_failure_state(URL)["cooldown_remaining_s"] == 0.0
    assert manager.ready_epoch == 1
