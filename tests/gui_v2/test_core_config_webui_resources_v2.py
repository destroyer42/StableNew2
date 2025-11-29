from __future__ import annotations

import tkinter as tk
from types import SimpleNamespace

import pytest

from src.controller.webui_connection_controller import WebUIConnectionState
from src.gui.core_config_panel_v2 import CoreConfigPanelV2


class DummyAdapter:
    def __init__(self, models=None, vaes=None, samplers=None):
        self._models = models or []
        self._vaes = vaes or []
        self._samplers = samplers or []

    def get_model_names(self):
        return list(self._models)

    def get_vae_names(self):
        return list(self._vaes)

    def get_sampler_names(self):
        return list(self._samplers)


@pytest.fixture
def tk_root():
    try:
        root = tk.Tk()
    except tk.TclError as exc:
        pytest.skip(f"Tkinter not available: {exc}")
    root.withdraw()
    yield root
    try:
        root.destroy()
    except Exception:
        pass


def test_core_config_refresh_updates_dropdowns(tk_root):
    adapter = DummyAdapter(models=["m1", "m2"], vaes=["v1"], samplers=["s1"])
    panel = CoreConfigPanelV2(
        tk_root,
        include_vae=True,
        include_refresh=True,
        model_adapter=adapter,
        vae_adapter=adapter,
        sampler_adapter=adapter,
    )

    panel.refresh_from_adapters()

    assert tuple(panel._model_combo["values"]) == ("m1", "m2")
    assert tuple(panel._vae_combo["values"]) == ("v1",)
    assert tuple(panel._sampler_combo["values"]) == ("s1",)


def test_core_config_refresh_preserves_selection(tk_root):
    adapter = DummyAdapter(models=["keep", "other"], vaes=["v1"], samplers=["s1"])
    panel = CoreConfigPanelV2(
        tk_root,
        include_vae=True,
        include_refresh=True,
        model_adapter=adapter,
        vae_adapter=adapter,
        sampler_adapter=adapter,
    )
    panel.model_var.set("keep")
    panel.refresh_from_adapters()
    assert panel.model_var.get() == "keep"


def test_core_config_refresh_triggered_on_ready(monkeypatch):
    from src.main import _update_window_webui_manager

    class FakePanel:
        def __init__(self):
            self.state_history = []

        def set_webui_state(self, state):
            self.state_history.append(state)

        def set_launch_callback(self, callback):
            self.launch_callback = callback

        def set_retry_callback(self, callback):
            self.retry_callback = callback

    class FakeSidebar:
        def __init__(self):
            self.refresh_calls = 0

        def refresh_core_config_from_webui(self):
            self.refresh_calls += 1

    class FakeWindow:
        def __init__(self):
            self.status_bar_v2 = SimpleNamespace(webui_panel=FakePanel())
            self.sidebar_panel_v2 = FakeSidebar()
            self.webui_process_manager = SimpleNamespace()
            self.left_zone = None

    class FakeConnectionController:
        def __init__(self, *args, **kwargs):
            self._state = WebUIConnectionState.READY

        def get_state(self):
            return self._state

        def ensure_connected(self, autostart=True):
            self._state = WebUIConnectionState.READY
            return self._state

        def reconnect(self):
            self._state = WebUIConnectionState.READY
            return self._state

        def get_base_url(self):
            return "http://127.0.0.1:7860"

    monkeypatch.setattr(
        "src.controller.webui_connection_controller.WebUIConnectionController",
        FakeConnectionController,
    )

    window = FakeWindow()
    _update_window_webui_manager(window, window.webui_process_manager)
    assert window.sidebar_panel_v2.refresh_calls == 1
