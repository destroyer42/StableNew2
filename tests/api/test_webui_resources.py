import pytest
from src.api.webui_resources import WebUIResourceService

class DummyClient:
    def get_models(self):
        return [
            {"model_name": "test-model", "title": "Test Model"},
            {"model_name": "other-model", "title": "Other Model"},
        ]
    def get_vae_models(self):
        return [
            {"model_name": "test-vae", "title": "Test VAE"},
        ]
    def get_hypernetworks(self):
        return [
            {"name": "hyper1"},
        ]
    def get_upscalers(self):
        return [
            {"name": "upscaler1"},
        ]

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
    service = WebUIResourceService(client=DummyClient(), webui_root="/does/not/matter")
    models = service.list_models()
    assert any(r.name == "test-model" for r in models)
    vaes = service.list_vaes()
    assert any(r.name == "test-vae" for r in vaes)
    hypers = service.list_hypernetworks()
    assert any(r.name == "hyper1" for r in hypers)
    upscalers = service.list_upscalers()
    assert any(r.name == "upscaler1" for r in upscalers)

def test_filesystem_fallback(temp_webui_root):
    service = WebUIResourceService(client=None, webui_root=str(temp_webui_root))
    models = service.list_models()
    assert any(r.name == "fallback-model" for r in models)
    vaes = service.list_vaes()
    assert any(r.name == "fallback-vae" for r in vaes)
    hypers = service.list_hypernetworks()
    assert any(r.name == "hypernet1" for r in hypers)
    embeddings = service.list_embeddings()
    assert any(r.name == "embed1" for r in embeddings)
    upscalers = service.list_upscalers()
    assert any(r.name == "upscaler1" for r in upscalers)
