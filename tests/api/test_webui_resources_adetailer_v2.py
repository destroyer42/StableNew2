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

    def get_hypernetworks(self):
        return [{"name": "hyper-1"}]

    def get_adetailer_models(self):
        return ["face_yolov8n.pt", "face_yolov8m.pt"]

    def get_adetailer_detectors(self):
        return ["face", "hand"]


def test_refresh_all_includes_canonical_resource_lists(tmp_path):
    emb_dir = tmp_path / "embeddings"
    emb_dir.mkdir(parents=True)
    (emb_dir / "embedding-a.pt").write_text("")

    client = FakeClient()
    service = WebUIResourceService(client=client, webui_root=str(tmp_path))
    resources = service.refresh_all()

    assert resources.get("hypernetworks")
    assert resources.get("embeddings")
    assert resources.get("adetailer_models") == ["face_yolov8n.pt", "face_yolov8m.pt"]
    assert resources.get("adetailer_detectors") == ["face", "hand"]


# --- PR-IMG-FORGE-120: an unavailable refresh must not advertise detectors the managed Forge runtime lacks -------------


def test_forge_detector_fallback_is_only_the_managed_runtimes_accepted_set(monkeypatch) -> None:
    from src.api.client import SDWebUIClient
    from src.api.forge_client import ForgeWebUIClient
    from src.utils.managed_forge_runtime import accepted_detector_names

    accepted = list(accepted_detector_names())
    assert accepted == ["face_yolov8n.pt", "hand_yolov8n.pt"]  # exactly the manifest's two YOLO files, never MediaPipe
    monkeypatch.setattr(SDWebUIClient, "get_scripts", lambda self: None)  # the refresh is unavailable

    forge = ForgeWebUIClient(base_url="http://127.0.0.1:7871")
    assert forge.get_adetailer_models() == accepted
    assert forge.get_adetailer_detectors() == accepted
    assert WebUIResourceService(client=forge).refresh_all()["adetailer_models"] == accepted
    # a scripts payload with no ADetailer entry falls back the same way
    monkeypatch.setattr(SDWebUIClient, "get_scripts", lambda self: {"txt2img": []})
    assert forge.get_adetailer_models() == accepted

    generic = SDWebUIClient(base_url="http://127.0.0.1:7860").get_adetailer_models()  # explicit A1111 keeps its list
    assert "mediapipe_face_full" in generic and "face_yolov8s.pt" in generic


def test_forge_reports_what_the_endpoint_lists_when_it_answers(monkeypatch) -> None:
    from src.api.client import SDWebUIClient
    from src.api.forge_client import ForgeWebUIClient

    scripts = {"txt2img": [{"name": "ADetailer", "args": [{"choices": ["face_yolov8n.pt", "hand_yolov8n.pt", "extra.pt", "more.pt"]}]}]}
    monkeypatch.setattr(SDWebUIClient, "get_scripts", lambda self: scripts)
    assert ForgeWebUIClient(base_url="http://127.0.0.1:7871").get_adetailer_models()[2] == "extra.pt"  # the endpoint is truth
