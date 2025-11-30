from __future__ import annotations

from src.api.webui_resource_service import WebUIResourceService


class FakeClient:
    def get_models(self):
        return [{"model_name": "model-a", "title": "Model A"}]

    def get_vae_models(self):
        return [{"model_name": "vae-1", "title": "VAE 1"}]

    def get_samplers(self):
        return [{"name": "Euler a"}]

    def get_schedulers(self):
        return ["Normal"]

    def get_adetailer_models(self):
        return ["face_yolov8n.pt", "face_yolov8m.pt"]

    def get_adetailer_detectors(self):
        return ["face", "hand"]


def test_refresh_all_includes_adetailer_lists():
    client = FakeClient()
    service = WebUIResourceService(client=client)
    resources = service.refresh_all()

    assert resources.get("adetailer_models") == ["face_yolov8n.pt", "face_yolov8m.pt"]
    assert resources.get("adetailer_detectors") == ["face", "hand"]
