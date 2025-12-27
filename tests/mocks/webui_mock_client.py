"""Mock WebUIClient that uses MockWebUIServer."""

from typing import Any
from tests.mocks.webui_mock_server import get_mock_server


class MockWebUIClient:
    """
    Drop-in replacement for WebUIClient that uses MockWebUIServer.
    
    Compatible with journey tests. Provides same interface as real client,
    but routes requests to mock server instead of HTTP.
    """
    
    def __init__(self, base_url: str = "http://mock"):
        self.base_url = base_url
        self.server = get_mock_server()
    
    def txt2img(self, **kwargs) -> dict:
        """Call mock txt2img."""
        return self.server.txt2img(kwargs)
    
    def img2img(self, **kwargs) -> dict:
        """Call mock img2img."""
        return self.server.img2img(kwargs)
    
    def upscale(self, **kwargs) -> dict:
        """Call mock upscale."""
        return self.server.upscale(kwargs)
    
    def controlnet(self, **kwargs) -> dict:
        """Call mock controlnet."""
        return self.server.controlnet(kwargs)
    
    def get_progress(self) -> dict:
        """Mock progress (always complete)."""
        return {
            "progress": 1.0,
            "eta_relative": 0.0,
            "state": {"job_count": 0},
            "current_image": None,
        }
    
    def interrupt(self) -> dict:
        """Mock interrupt (no-op)."""
        return {"success": True}
    
    def get_config(self) -> dict:
        """Mock config."""
        return {
            "sd_model_checkpoint": "mock_model_v1.safetensors",
            "sd_vae": "auto",
        }
