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
            "adetailer_models": ["face_yolov8n.pt"],
            "adetailer_detectors": ["face", "hand"],
        }


def test_controller_refreshes_adetailer_resources(monkeypatch) -> None:
    controller = AppController(None, threaded=False, pipeline_runner=DummyPipelineRunner())
    controller.app_state = AppStateV2()
    controller.resource_service = FakeResourceService()
    fake_panel = FakeStageCardsPanel()
    controller.main_window = SimpleNamespace(pipeline_tab=SimpleNamespace(stage_cards_panel=fake_panel))

    controller.refresh_resources_from_webui()

    assert controller.app_state.adetailer_models == ["face_yolov8n.pt"]
    assert controller.app_state.adetailer_detectors == ["face", "hand"]
    assert fake_panel.last_resources is not None
    assert fake_panel.last_resources.get("adetailer_models") == ["face_yolov8n.pt"]
    assert fake_panel.last_resources.get("adetailer_detectors") == ["face", "hand"]
