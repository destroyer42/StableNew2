"""PR-RUNTIME-WEBUI-WATCHDOG-120: first-trigger semantics are independent of host uptime.

``time.monotonic()`` is host uptime, so "never triggered" must not be represented by a number near
zero. All timing here comes from an injected clock; no test waits in real time.
"""

from __future__ import annotations

import time
from types import SimpleNamespace

import pytest

from src.services.watchdog_system_v2 import SystemWatchdogV2
from src.utils import diagnostics_bundle_v2 as bundle_module

UI_COOLDOWN_S = SystemWatchdogV2.COOLDOWN_S["ui_heartbeat_stall"]


class _Diagnostics:
    def __init__(self) -> None:
        self.calls: list[dict[str, object]] = []

    def build_async(self, **kwargs) -> None:
        self.calls.append(kwargs)
        callback = kwargs.get("on_done")
        if callable(callback):
            callback()

    def ui_stall_calls(self) -> list[dict[str, object]]:
        return [call for call in self.calls if call["reason"] == "ui_heartbeat_stall"]


class _ClockedTime:
    """Stands in for the ``time`` module inside one module: real time, controllable monotonic."""

    def __init__(self, clock: SimpleNamespace) -> None:
        self._clock = clock

    def monotonic(self) -> float:
        return self._clock.now

    def __getattr__(self, name: str):
        return getattr(time, name)


@pytest.fixture
def clock(monkeypatch: pytest.MonkeyPatch) -> SimpleNamespace:
    """A small host-uptime origin (a freshly booted host, a few seconds into the session)."""

    state = SimpleNamespace(now=50.0)
    stub = _ClockedTime(state)
    monkeypatch.setattr("src.services.watchdog_system_v2.time", stub)
    monkeypatch.setattr(bundle_module, "time", stub)
    return state


def _idle_app(clock: SimpleNamespace, *, heartbeat_age_s: float) -> SimpleNamespace:
    return SimpleNamespace(
        last_ui_heartbeat_ts=clock.now - heartbeat_age_s,
        last_queue_activity_ts=clock.now,
        last_runner_activity_ts=clock.now,
        has_running_jobs=lambda: False,
        get_queue_state=lambda: {"status": "idle"},
        _is_shutting_down=False,
    )


def test_true_ui_stall_triggers_even_with_a_tiny_monotonic_origin(clock) -> None:
    app = _idle_app(clock, heartbeat_age_s=SystemWatchdogV2.UI_STALL_S + 5.0)
    diagnostics = _Diagnostics()
    watchdog = SystemWatchdogV2(app, diagnostics)

    assert clock.now < UI_COOLDOWN_S  # the condition that used to suppress the first trigger
    watchdog._check()

    assert len(diagnostics.ui_stall_calls()) == 1


def test_a_healthy_heartbeat_never_triggers_at_a_tiny_monotonic_origin(clock) -> None:
    app = _idle_app(clock, heartbeat_age_s=0.5)
    diagnostics = _Diagnostics()
    watchdog = SystemWatchdogV2(app, diagnostics)

    for _ in range(40):
        clock.now += 0.25
        app.last_ui_heartbeat_ts = clock.now
        watchdog._check()

    assert diagnostics.ui_stall_calls() == []


def test_continuing_stall_is_damped_and_re_triggers_only_after_the_cooldown(clock) -> None:
    app = _idle_app(clock, heartbeat_age_s=SystemWatchdogV2.UI_STALL_S + 5.0)
    diagnostics = _Diagnostics()
    watchdog = SystemWatchdogV2(app, diagnostics)

    watchdog._check()
    assert len(diagnostics.ui_stall_calls()) == 1

    # The stall continues: every check inside the repeat cooldown is suppressed.
    for _ in range(int(UI_COOLDOWN_S) - 1):
        clock.now += 1.0
        watchdog._check()
    assert len(diagnostics.ui_stall_calls()) == 1

    # An eligible later stall after the cooldown triggers again.
    clock.now += 2.0
    watchdog._check()
    assert len(diagnostics.ui_stall_calls()) == 2


def test_runner_stall_never_triggered_default_does_not_depend_on_uptime(clock) -> None:
    app = _idle_app(clock, heartbeat_age_s=0.0)
    app.has_running_jobs = lambda: True
    app.last_runner_activity_ts = clock.now - SystemWatchdogV2.RUNNER_STALL_S - 5.0
    diagnostics = _Diagnostics()
    watchdog = SystemWatchdogV2(app, diagnostics)

    watchdog._check()

    assert [c for c in diagnostics.calls if c["reason"] == "queue_runner_stall"]


def test_first_diagnostics_bundle_is_not_suppressed_by_a_tiny_monotonic_origin(
    clock, tmp_path, monkeypatch
) -> None:
    reason = "ui_heartbeat_stall_first_trigger_120"
    built: list[str] = []
    monkeypatch.setattr(
        bundle_module, "build_crash_bundle", lambda **kwargs: built.append(kwargs["reason"])
    )
    bundle_module._LAST_BUNDLE_TS.pop(reason, None)
    bundle_module._IN_FLIGHT.discard(reason)
    try:
        clock.now = 10.0  # below the 30 s bundle cooldown
        first = bundle_module.build_async(reason=reason, output_dir=tmp_path, cooldown_s=30.0)
        assert first is not None, "the first bundle must not be gated by host uptime"
        first.join(timeout=10.0)
        assert built == [reason]

        # The existing repeat cooldown still applies after the first bundle.
        clock.now += 5.0
        assert bundle_module.build_async(reason=reason, output_dir=tmp_path, cooldown_s=30.0) is None
        assert built == [reason]
    finally:
        bundle_module._LAST_BUNDLE_TS.pop(reason, None)
        bundle_module._IN_FLIGHT.discard(reason)
