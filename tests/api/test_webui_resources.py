import pytest
from src.api.webui_resources import WebUIResourceService

from tests.helpers.webui_mocks import DummyWebUIClient

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


def test_filesystem_fallback(temp_webui_root):
    service = WebUIResourceService(client=None, webui_root=str(temp_webui_root))
    resources = _build_resource_map(service)
    assert resources["models"], "Expected fallback models for filesystem lookup"
    assert resources["vaes"], "Expected fallback VAEs for filesystem lookup"
    assert resources["hypernetworks"], "Expected fallback hypernetworks for filesystem lookup"
    assert resources["embeddings"], "Expected fallback embeddings for filesystem lookup"
    assert resources["upscalers"], "Expected fallback upscalers for filesystem lookup"
    assert set(resources.keys()) >= {"models", "vaes", "hypernetworks", "embeddings", "upscalers"}
    assert "refiner_models" in resources
    assert "adetailer_models" in resources
    assert "adetailer_detectors" in resources
