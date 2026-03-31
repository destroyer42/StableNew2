from __future__ import annotations

from types import SimpleNamespace
from unittest import mock

from src.controller.webui_connection_controller import WebUIConnectionState
from src.gui.api_status_panel import resolve_webui_state_display


class FakeWebUIPanel:
    def __init__(self) -> None:
        self.launch_callback = None
        self.retry_callback = None
        self.state_history: list[WebUIConnectionState] = []

    def set_launch_callback(self, callback) -> None:
        self.launch_callback = callback

    def set_retry_callback(self, callback) -> None:
        self.retry_callback = callback

    def set_webui_state(self, state: WebUIConnectionState) -> None:
        self.state_history.append(state)


class FakeStatusBar:
    def __init__(self) -> None:
        self.webui_panel = FakeWebUIPanel()
        self.state_history: list[WebUIConnectionState] = []
        self.state_text_history: list[str] = []

    def update_webui_state(self, state: WebUIConnectionState | str | None) -> None:
        self.webui_panel.set_webui_state(state)
        normalized, text, _ = resolve_webui_state_display(state)
        if normalized is not None:
            self.state_history.append(normalized)
        elif isinstance(state, WebUIConnectionState):
            self.state_history.append(state)
        self.state_text_history.append(text)


class FakeWindow:
    def __init__(self) -> None:
        self.status_bar_v2 = FakeStatusBar()
        self.webui_process_manager = None
        self.left_zone = None

    def after(self, _delay, callback):
        callback()


class ControlledWindow(FakeWindow):
    def __init__(self) -> None:
        super().__init__()
        self.app_controller = SimpleNamespace(on_webui_ready=mock.Mock())
        self._scheduled: list[tuple[int, object]] = []

    def after(self, delay, callback):
        self._scheduled.append((delay, callback))


class FakeConnectionController:
    def __init__(self, *args, **kwargs):
        self._state = WebUIConnectionState.DISCONNECTED

    def ensure_connected(self, autostart: bool = True) -> WebUIConnectionState:
        self._state = WebUIConnectionState.READY
        return self._state

    def reconnect(self) -> WebUIConnectionState:
        self._state = WebUIConnectionState.READY
        return self._state

    def get_state(self) -> WebUIConnectionState:
        return self._state

    def get_base_url(self) -> str:
        return "http://127.0.0.1:7860"


def test_webui_launch_opens_browser(monkeypatch):
    import webbrowser

    from src.main import _update_window_webui_manager

    window = FakeWindow()
    fake_manager = SimpleNamespace()

    monkeypatch.setattr(
        "src.controller.webui_connection_controller.WebUIConnectionController",
        FakeConnectionController,
    )
    open_mock = mock.Mock()
    monkeypatch.setattr(webbrowser, "open_new_tab", open_mock)

    _update_window_webui_manager(window, fake_manager)

    panel = window.status_bar_v2.webui_panel
    assert panel.launch_callback is not None

    panel.launch_callback()

    open_mock.assert_called_once_with("http://127.0.0.1:7860")
    assert panel.state_history[-1] == WebUIConnectionState.READY
    assert window.status_bar_v2.state_text_history[-1] == "WebUI: Ready"


def test_webui_reconnect_retriggers_ready_callback(monkeypatch) -> None:
    from src.main import _update_window_webui_manager

    class SequenceConnectionController:
        def __init__(self, *args, **kwargs):
            self._states = [
                WebUIConnectionState.READY,
                WebUIConnectionState.DISCONNECTED,
                WebUIConnectionState.READY,
            ]
            self._state = WebUIConnectionState.DISCONNECTED

        def ensure_connected(self, autostart: bool = True) -> WebUIConnectionState:
            self._state = WebUIConnectionState.READY
            return self._state

        def reconnect(self) -> WebUIConnectionState:
            self._state = WebUIConnectionState.READY
            return self._state

        def get_state(self) -> WebUIConnectionState:
            if self._states:
                self._state = self._states.pop(0)
            return self._state

        def get_base_url(self) -> str:
            return "http://127.0.0.1:7860"

    window = ControlledWindow()
    monkeypatch.setattr(
        "src.controller.webui_connection_controller.WebUIConnectionController",
        SequenceConnectionController,
    )

    _update_window_webui_manager(window, SimpleNamespace())

    initial_callback = window._scheduled.pop(0)[1]
    initial_callback()
    reconnect_callback = window._scheduled.pop(0)[1]
    reconnect_callback()

    assert window.app_controller.on_webui_ready.call_count == 2
