"""PR-RUNTIME-WEBUI-WATCHDOG-120: WebUI connection work never blocks the Tk thread.

The test thread plays the Tk thread. ``FakeWindow.run_in_main_thread`` queues callbacks the way the
real Tk dispatcher does, and the test "pumps" them explicitly. A fake connection controller blocks
on an ``Event`` to stand in for a startup that takes longer than the 10 s UI-stall threshold, so no
test waits in real time and the Tk side never blocks.
"""

from __future__ import annotations

import queue
import threading
import time
from types import SimpleNamespace
from unittest import mock

import pytest

from src.controller.webui_connection_controller import WebUIConnectionState
from src.main import _update_window_webui_manager
from src.services.watchdog_system_v2 import SystemWatchdogV2

WAIT_S = 10.0  # generous upper bound for thread hand-offs; never a sleep


class FakePanel:
    def __init__(self) -> None:
        self.launch_callback = None
        self.retry_callback = None
        self.states: list[WebUIConnectionState] = []

    def set_launch_callback(self, callback) -> None:
        self.launch_callback = callback

    def set_retry_callback(self, callback) -> None:
        self.retry_callback = callback

    def set_webui_state(self, state) -> None:
        self.states.append(state)


class FakeWindow:
    """Queues Tk-thread callbacks; the test pumps them (``pump``) like the Tk event loop."""

    def __init__(self, connection_controller) -> None:
        self.webui_panel = FakePanel()
        self.status_bar_v2 = SimpleNamespace(webui_panel=self.webui_panel)
        self.webui_process_manager = None
        self.left_zone = None
        self.app_controller = SimpleNamespace(webui_connection_controller=connection_controller)
        self.tk_queue: queue.Queue = queue.Queue()
        self.scheduled_after: list = []

    def run_in_main_thread(self, fn) -> None:
        self.tk_queue.put(fn)

    def after(self, _delay, callback) -> None:
        # Periodic checks are driven explicitly by the tests.
        self.scheduled_after.append(callback)

    def pump(self, *, expect: int = 1) -> None:
        for _ in range(expect):
            self.tk_queue.get(timeout=WAIT_S)()


class BlockingConnectionController:
    """``ensure_connected``/``reconnect`` block until released; they record their thread."""

    def __init__(self, *, result=WebUIConnectionState.READY, error: Exception | None = None):
        self._state = WebUIConnectionState.DISCONNECTED
        self.release = threading.Event()
        self.started = threading.Event()
        self.calls: list[tuple[str, int]] = []
        self.result = result
        self.error = error

    def _blocking(self, name: str) -> WebUIConnectionState:
        self.calls.append((name, threading.get_ident()))
        self._state = WebUIConnectionState.CONNECTING
        self.started.set()
        assert self.release.wait(WAIT_S), "test never released the simulated startup"
        if self.error is not None:
            raise self.error
        self._state = self.result
        return self._state

    def ensure_connected(self, autostart: bool = True) -> WebUIConnectionState:
        return self._blocking("ensure_connected")

    def reconnect(self) -> WebUIConnectionState:
        return self._blocking("reconnect")

    def get_state(self) -> WebUIConnectionState:
        return self._state

    def get_base_url(self) -> str:
        return "http://127.0.0.1:7860"


@pytest.fixture
def open_tab(monkeypatch) -> mock.Mock:
    import webbrowser

    opened = mock.Mock()
    monkeypatch.setattr(webbrowser, "open_new_tab", opened)
    return opened


def _wire(controller: BlockingConnectionController) -> FakeWindow:
    window = FakeWindow(controller)
    _update_window_webui_manager(window, SimpleNamespace())
    assert window.webui_panel.launch_callback is not None
    assert window.webui_panel.retry_callback is not None
    return window


def test_launch_returns_immediately_and_work_runs_off_the_tk_thread(open_tab) -> None:
    controller = BlockingConnectionController()
    window = _wire(controller)
    tk_thread = threading.get_ident()

    window.webui_panel.launch_callback()  # would hang the test if it ran the work inline

    assert controller.started.wait(WAIT_S)
    assert window.webui_panel.states[-1] is WebUIConnectionState.CONNECTING
    assert controller.calls and controller.calls[0][1] != tk_thread
    open_tab.assert_not_called()

    controller.release.set()
    window.pump()

    assert window.webui_panel.states[-1] is WebUIConnectionState.READY
    open_tab.assert_called_once_with("http://127.0.0.1:7860")


def test_retry_runs_reconnect_off_the_tk_thread(open_tab) -> None:
    controller = BlockingConnectionController()
    window = _wire(controller)

    window.webui_panel.retry_callback()

    assert controller.started.wait(WAIT_S)
    assert controller.calls[0][0] == "reconnect"
    assert controller.calls[0][1] != threading.get_ident()
    assert window.webui_panel.states[-1] is WebUIConnectionState.CONNECTING
    controller.release.set()
    window.pump()
    assert window.webui_panel.states[-1] is WebUIConnectionState.READY
    open_tab.assert_not_called()  # Retry never opens a browser tab


def test_overlapping_clicks_are_single_flight(open_tab) -> None:
    controller = BlockingConnectionController()
    window = _wire(controller)

    window.webui_panel.launch_callback()
    assert controller.started.wait(WAIT_S)
    window.webui_panel.launch_callback()  # double click
    window.webui_panel.retry_callback()  # retry while launching

    controller.release.set()
    window.pump()
    assert len(controller.calls) == 1
    assert window.tk_queue.empty()

    # Once finished, the next click is accepted again.
    controller.started.clear()
    controller.release.clear()
    window.webui_panel.retry_callback()
    assert controller.started.wait(WAIT_S)
    controller.release.set()
    window.pump()
    assert [name for name, _ in controller.calls] == ["ensure_connected", "reconnect"]


def test_never_ready_webui_ends_in_error_and_leaves_the_gui_usable(open_tab) -> None:
    # The controller's bounded readiness contract returns ERROR when WebUI never becomes ready.
    controller = BlockingConnectionController(result=WebUIConnectionState.ERROR)
    window = _wire(controller)

    window.webui_panel.launch_callback()
    assert controller.started.wait(WAIT_S)
    controller.release.set()
    window.pump()

    assert window.webui_panel.states[-1] is WebUIConnectionState.ERROR
    open_tab.assert_not_called()
    assert len(controller.calls) == 1  # one bounded attempt, no retry loop in the GUI layer

    # The GUI is not wedged: a later Retry is accepted.
    controller.started.clear()
    controller.release.clear()
    window.webui_panel.retry_callback()
    assert controller.started.wait(WAIT_S)
    controller.release.set()
    window.pump()
    assert len(controller.calls) == 2


def test_connection_exception_projects_error_and_clears_the_guard(open_tab) -> None:
    controller = BlockingConnectionController(error=RuntimeError("probe exploded"))
    window = _wire(controller)

    window.webui_panel.launch_callback()
    assert controller.started.wait(WAIT_S)
    controller.release.set()
    window.pump()

    assert window.webui_panel.states[-1] is WebUIConnectionState.ERROR
    open_tab.assert_not_called()
    controller.error = None
    controller.started.clear()
    controller.release.clear()
    window.webui_panel.retry_callback()
    assert controller.started.wait(WAIT_S)
    controller.release.set()
    window.pump()
    assert window.webui_panel.states[-1] is WebUIConnectionState.READY


def test_periodic_autoreconnect_runs_off_tk_and_is_single_flight(open_tab) -> None:
    controller = BlockingConnectionController()
    window = _wire(controller)
    tk_thread = threading.get_ident()

    # _wire already ran the initial status check (1 DISCONNECTED observation). Two more
    # periodic ticks reach the 3-disconnect autoreconnect threshold.
    periodic = window.scheduled_after[-1]
    periodic()
    periodic()

    assert controller.started.wait(WAIT_S)
    assert controller.calls[0][0] == "ensure_connected"
    assert controller.calls[0][1] != tk_thread

    # While the attempt is in flight the controller reports CONNECTING; ticks must not pile up.
    periodic()
    periodic()
    controller.release.set()
    window.pump()
    assert len(controller.calls) == 1
    assert window.webui_panel.states[-1] is WebUIConnectionState.READY


def test_long_webui_startup_is_not_a_ui_stall_but_a_frozen_heartbeat_is() -> None:
    """The Tk thread keeps beating while WebUI start takes >10 s; a frozen Tk loop still triggers.

    Time is simulated: the Tk thread advances a fake clock in 250 ms heartbeat ticks (the real
    ticker period) and runs the real watchdog check after each tick.
    """

    now = SimpleNamespace(value=50.0)  # tiny host-uptime origin on purpose
    diagnostics_calls: list[dict] = []

    class Diagnostics:
        def build_async(self, **kwargs) -> None:
            diagnostics_calls.append(kwargs)
            callback = kwargs.get("on_done")
            if callable(callback):
                callback()

    app = SimpleNamespace(
        last_ui_heartbeat_ts=now.value,
        last_queue_activity_ts=now.value,
        last_runner_activity_ts=now.value,
        has_running_jobs=lambda: False,
        get_queue_state=lambda: {"status": "idle"},
        _is_shutting_down=False,
    )

    class Clock:
        def monotonic(self) -> float:
            return now.value

        def __getattr__(self, name):
            return getattr(time, name)

    clock = Clock()
    with mock.patch("src.services.watchdog_system_v2.time", clock):
        watchdog = SystemWatchdogV2(app, Diagnostics())
        controller = BlockingConnectionController()
        window = _wire(controller)

        window.webui_panel.launch_callback()
        assert controller.started.wait(WAIT_S)  # WebUI "startup" is now in progress off Tk

        simulated_startup_s = SystemWatchdogV2.UI_STALL_S * 3  # 30 s, far above the threshold
        for _ in range(int(simulated_startup_s / 0.25)):
            now.value += 0.25
            app.last_ui_heartbeat_ts = now.value  # the Tk heartbeat ticker keeps running
            watchdog._check()

        assert diagnostics_calls == [], "slow WebUI startup must not look like a UI stall"
        assert controller.started.is_set() and not controller.release.is_set()

        controller.release.set()
        window.pump()
        assert window.webui_panel.states[-1] is WebUIConnectionState.READY

        # A genuinely frozen Tk loop (no heartbeat) is still caught.
        now.value += SystemWatchdogV2.UI_STALL_S + 1.0
        watchdog._check()
        assert [c["reason"] for c in diagnostics_calls] == ["ui_heartbeat_stall"]
