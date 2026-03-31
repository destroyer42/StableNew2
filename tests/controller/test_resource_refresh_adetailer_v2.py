from __future__ import annotations

from types import SimpleNamespace

from src.controller.app_controller import AppController
from src.gui.app_state_v2 import AppStateV2


class DummyPipelineRunner:
    def run(self, *args, **kwargs):
        return None


class FakeStageCardsPanel:
    def __init__(self) -> None:
        self.last_resources = None

    def apply_resource_update(self, resources: dict[str, list[str]] | None) -> None:
        self.last_resources = dict(resources or {})


class FakeResourceService:
    def refresh_all(self) -> dict[str, list[str]]:
        return {
            "models": [],
            "vaes": [],
            "samplers": [],
            "schedulers": [],
            "upscalers": [],
            "hypernetworks": ["hyper-a"],
            "embeddings": ["embed-a"],
            "adetailer_models": ["face_yolov8n.pt"],
            "adetailer_detectors": ["face", "hand"],
        }


def test_controller_refreshes_adetailer_resources(monkeypatch) -> None:
    controller = AppController(None, threaded=False, pipeline_runner=DummyPipelineRunner())
    controller.app_state = AppStateV2()
    controller.resource_service = FakeResourceService()
    fake_panel = FakeStageCardsPanel()
    controller.main_window = SimpleNamespace(
        pipeline_tab=SimpleNamespace(stage_cards_panel=fake_panel)
    )

    controller.refresh_resources_from_webui()

    assert controller.app_state.adetailer_models == ["face_yolov8n.pt"]
    assert controller.app_state.adetailer_detectors == ["face", "hand"]
    assert controller.app_state.resources["hypernetworks"] == ["hyper-a"]
    assert controller.app_state.resources["embeddings"] == ["embed-a"]
    assert fake_panel.last_resources is not None
    assert fake_panel.last_resources.get("hypernetworks") == ["hyper-a"]
    assert fake_panel.last_resources.get("embeddings") == ["embed-a"]
    assert fake_panel.last_resources.get("adetailer_models") == ["face_yolov8n.pt"]
    assert fake_panel.last_resources.get("adetailer_detectors") == ["face", "hand"]


def test_controller_preserves_existing_critical_resources_when_refresh_is_empty() -> None:
    controller = AppController(None, threaded=False, pipeline_runner=DummyPipelineRunner())
    controller.app_state = AppStateV2()
    controller.resource_service = FakeResourceService()
    fake_panel = FakeStageCardsPanel()
    controller.main_window = SimpleNamespace(
        pipeline_tab=SimpleNamespace(stage_cards_panel=fake_panel)
    )

    existing = {
        "models": ["model-a"],
        "vaes": ["vae-a"],
        "samplers": ["Euler a"],
        "schedulers": ["Karras"],
        "upscalers": ["Latent"],
        "hypernetworks": [],
        "embeddings": [],
        "adetailer_models": [],
        "adetailer_detectors": [],
    }
    controller.state.resources = dict(existing)
    controller.app_state.set_resources(existing)

    controller.refresh_resources_from_webui()

    assert controller.app_state.resources["models"] == ["model-a"]
    assert controller.app_state.resources["vaes"] == ["vae-a"]
    assert controller.app_state.resources["samplers"] == ["Euler a"]
    assert controller.app_state.resources["schedulers"] == ["Karras"]
    assert controller.app_state.resources["hypernetworks"] == ["hyper-a"]
    assert controller.app_state.resources["adetailer_models"] == ["face_yolov8n.pt"]
    assert fake_panel.last_resources is not None
    assert fake_panel.last_resources.get("models") == ["model-a"]
    assert fake_panel.last_resources.get("hypernetworks") == ["hyper-a"]
