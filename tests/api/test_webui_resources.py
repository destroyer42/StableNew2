import pytest

from src.api.client import DEFAULT_SCHEDULERS
from src.api.webui_resource_service import WebUIResourceService as ExtendedWebUIResourceService
from src.api.webui_resources import WebUIResourceService
from tests.helpers.webui_mocks import DummyWebUIClient


@pytest.fixture
def forbid_webui_client(monkeypatch):
    """Fail loudly if a filesystem-only service ever constructs a WebUI client."""

    def _boom(*args, **kwargs):
        raise AssertionError("filesystem-only resource discovery must not create a WebUI client")

    monkeypatch.setattr("src.api.webui_resources.SDWebUIClient", _boom)


@pytest.fixture
def temp_webui_root(tmp_path):
    # Create dummy model files
    model_dir = tmp_path / "models" / "Stable-diffusion"
    model_dir.mkdir(parents=True)
    (model_dir / "fallback-model.ckpt").write_text("")
    (model_dir / "fallback-model.safetensors").write_text("")
    vae_dir = tmp_path / "models" / "VAE"
    vae_dir.mkdir(parents=True)
    (vae_dir / "fallback-vae.pt").write_text("")
    hyper_dir = tmp_path / "models" / "hypernetworks"
    hyper_dir.mkdir(parents=True)
    (hyper_dir / "hypernet1.pt").write_text("")
    emb_dir = tmp_path / "embeddings"
    emb_dir.mkdir(parents=True)
    (emb_dir / "embed1.pt").write_text("")
    up_dir = tmp_path / "models" / "ESRGAN"
    up_dir.mkdir(parents=True)
    (up_dir / "upscaler1.pt").write_text("")
    return tmp_path


def test_api_backed_discovery():
    client = DummyWebUIClient(
        models=[
            {"model_name": "test-model", "title": "Test Model"},
            {"model_name": "other-model", "title": "Other Model"},
        ],
        vaes=[
            {"model_name": "test-vae", "title": "Test VAE"},
        ],
        hypernetworks=[
            {"name": "hyper1"},
        ],
        upscalers=[
            {"name": "upscaler1"},
        ],
    )
    service = WebUIResourceService(client=client, webui_root="/does/not/matter")
    models = service.list_models()
    assert any(r.name == "test-model" for r in models)
    vaes = service.list_vaes()
    assert any(r.name == "test-vae" for r in vaes)
    hypers = service.list_hypernetworks()
    assert any(r.name == "hyper1" for r in hypers)
    upscalers = service.list_upscalers()
    assert any(r.name == "upscaler1" for r in upscalers)


def _build_resource_map(service: WebUIResourceService) -> dict[str, list]:
    return {
        "models": service.list_models(),
        "vaes": service.list_vaes(),
        "hypernetworks": service.list_hypernetworks(),
        "embeddings": service.list_embeddings(),
        "upscalers": service.list_upscalers(),
        "refiner_models": [],  # legacy placeholder
        "adetailer_models": [],  # added for future compatibility
        "adetailer_detectors": [],
    }


def test_filesystem_fallback(temp_webui_root, forbid_webui_client):
    service = WebUIResourceService(client=None, webui_root=str(temp_webui_root))
    assert service.client is None
    resources = _build_resource_map(service)
    assert {r.name for r in resources["models"]} == {"fallback-model"}
    assert [r.name for r in resources["vaes"]] == ["fallback-vae.pt"]
    assert [r.name for r in resources["hypernetworks"]] == ["hypernet1"]
    assert [r.name for r in resources["embeddings"]] == ["embed1"]
    assert [r.name for r in resources["upscalers"]] == ["upscaler1"]
    assert set(resources.keys()) >= {"models", "vaes", "hypernetworks", "embeddings", "upscalers"}
    assert "refiner_models" in resources
    assert "adetailer_models" in resources
    assert "adetailer_detectors" in resources


def test_omitted_client_builds_default_api_first_client(monkeypatch, temp_webui_root):
    class _RecordingClient:
        instances: list = []

        def __init__(self) -> None:
            self.calls: list[str] = []
            _RecordingClient.instances.append(self)

        def get_models(self):
            self.calls.append("get_models")
            return [{"model_name": "api-model", "title": "API Model"}]

    monkeypatch.setattr("src.api.webui_resources.SDWebUIClient", _RecordingClient)

    service = WebUIResourceService(webui_root=str(temp_webui_root))

    assert len(_RecordingClient.instances) == 1
    assert service.client is _RecordingClient.instances[0]
    # API-first: the API answer wins over the filesystem model present under the root
    assert [r.name for r in service.list_models()] == ["api-model"]
    assert service.client.calls == ["get_models"]


def test_explicit_client_is_used_as_given(temp_webui_root, forbid_webui_client):
    client = DummyWebUIClient(models=[{"model_name": "m", "title": "M"}])
    service = WebUIResourceService(client=client, webui_root=str(temp_webui_root))
    assert service.client is client


def test_extended_service_omitted_and_explicit_none_follow_the_same_contract(
    monkeypatch, temp_webui_root
):
    created: list[object] = []

    def _factory():
        created.append(object())
        return created[-1]

    monkeypatch.setattr("src.api.webui_resources.SDWebUIClient", _factory)

    default_service = ExtendedWebUIResourceService(webui_root=str(temp_webui_root))
    assert created and default_service.client is created[0]

    created.clear()
    fs_only = ExtendedWebUIResourceService(client=None, webui_root=str(temp_webui_root))
    assert created == []
    assert fs_only.client is None


def test_extended_filesystem_only_refresh_all_touches_no_client(
    temp_webui_root, forbid_webui_client
):
    service = ExtendedWebUIResourceService(client=None, webui_root=str(temp_webui_root))

    resources = service.refresh_all()

    assert {r.name for r in resources["models"]} == {"fallback-model"}
    assert [r.name for r in resources["vaes"]] == ["fallback-vae.pt"]
    assert [r.name for r in resources["hypernetworks"]] == ["hypernet1"]
    assert [r.name for r in resources["embeddings"]] == ["embed1"]
    assert [r.name for r in resources["upscalers"]] == ["upscaler1"]
    assert resources["samplers"] == []
    assert resources["schedulers"] == list(DEFAULT_SCHEDULERS)
    assert resources["adetailer_models"] == []
    assert resources["adetailer_detectors"] == []
