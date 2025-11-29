from types import SimpleNamespace
from unittest import mock

import pytest

from src.controller.app_controller import AppController
from src.controller.webui_connection_controller import WebUIConnectionController, WebUIConnectionState
from src.gui.app_state_v2 import AppStateV2


class DummyLabel:
    def configure(self, *args, **kwargs):
        pass


class DummyText:
    def insert(self, *args, **kwargs):
        pass

    def see(self, *args, **kwargs):
        pass


class DummyBottomZone:
    def __init__(self):
        self.api_status_label = DummyLabel()
        self.status_label = DummyLabel()
        self.log_text = DummyText()


class DummyButton:
    def configure(self, *args, **kwargs):
        pass


class DummyCombo:
    def bind(self, *args, **kwargs):
        pass


class ResourcePanelSpy:
    def __init__(self):
        self.calls: list[dict[str, list[str]]] = []

    def apply_resource_update(self, resources: dict[str, list[str]] | None) -> None:
        if resources is not None:
            self.calls.append(resources)


class DummyResourceService:
    def __init__(self):
        self.refresh_calls = 0

    def refresh_all(self) -> dict[str, list]:
        self.refresh_calls += 1
        return {
            "models": [
                SimpleNamespace(name="model-a", display_name="Model A"),
            ],
            "vaes": [
                SimpleNamespace(name="vae-z", display_name="VAE Z"),
            ],
            "samplers": ["Euler a", "DPM++ 2M"],
            "schedulers": ["Normal", "Karras"],
        }

    def list_models(self):
        return []

    def list_vaes(self):
        return []

    def list_upscalers(self):
        return []

    def list_hypernetworks(self):
        return []

    def list_embeddings(self):
        return []


class DummyMainWindow:
    def __init__(self, stage_panel: ResourcePanelSpy):
        self.app_state = AppStateV2()
        self.pipeline_tab = SimpleNamespace(stage_cards_panel=stage_panel)
        self.bottom_zone = DummyBottomZone()
        self.after = lambda *args, **kwargs: None
        self.open_engine_settings_dialog = lambda **kwargs: None
        self.header_zone = None
        self.left_zone = None
        self.status_bar_v2 = None

        self.header_zone = SimpleNamespace(
            run_button=DummyButton(),
            stop_button=DummyButton(),
            preview_button=DummyButton(),
            settings_button=DummyButton(),
            help_button=DummyButton(),
        )
        self.left_zone = SimpleNamespace(
            load_pack_button=DummyButton(),
            edit_pack_button=DummyButton(),
            packs_list=SimpleNamespace(bind=lambda *args, **kwargs: None),
            preset_combo=DummyCombo(),
        )

    def update_pack_list(self, packs: list[str]) -> None:
        self._pack_names = list(packs)

    def connect_controller(self, controller) -> None:
        self.app_controller = controller


def test_refresh_resources_from_webui(monkeypatch):
    stage_panel = ResourcePanelSpy()
    window = DummyMainWindow(stage_panel)
    resource_service = DummyResourceService()
    app_controller = AppController(
        window,
        pipeline_runner=mock.Mock(),
        threaded=False,
        resource_service=resource_service,
    )

    monkeypatch.setattr(
        "src.controller.webui_connection_controller.wait_for_webui_ready",
        lambda *args, **kwargs: True,
    )

    connection_controller = WebUIConnectionController()
    connection_controller.register_on_ready(app_controller.refresh_resources_from_webui)
    state = connection_controller.ensure_connected(autostart=False)

    assert state == WebUIConnectionState.READY
    assert resource_service.refresh_calls == 1
    normalized = app_controller.state.resources
    assert normalized["models"][0].display_name == "Model A"
    assert app_controller.app_state.resources == normalized
    assert stage_panel.calls
    assert stage_panel.calls[-1] is normalized


def test_on_webui_ready_registered(monkeypatch):
    stage_panel = ResourcePanelSpy()
    window = DummyMainWindow(stage_panel)
    app_controller = AppController(
        window,
        pipeline_runner=mock.Mock(),
        threaded=False,
        resource_service=DummyResourceService(),
    )

    refresh_calls: list[str] = []
    monkeypatch.setattr(
        app_controller,
        "refresh_resources_from_webui",
        lambda: refresh_calls.append("called"),
    )
    connection_controller = WebUIConnectionController()
    connection_controller.register_on_ready(app_controller.on_webui_ready)

    monkeypatch.setattr(
        "src.controller.webui_connection_controller.wait_for_webui_ready",
        lambda *args, **kwargs: True,
    )

    state = connection_controller.ensure_connected(autostart=False)

    assert state == WebUIConnectionState.READY
    assert refresh_calls
