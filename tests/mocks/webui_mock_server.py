"""Mock WebUI HTTP server for CI testing."""

from tests.mocks.mock_responses import (
    controlnet_response,
    img2img_response,
    txt2img_response,
    upscale_response,
)


class MockWebUIServer:
    """
    Mock SD WebUI API server for CI testing.
    
    Provides realistic responses for:
    - /sdapi/v1/txt2img
    - /sdapi/v1/img2img
    - /sdapi/v1/extra-single-image (upscale)
    - /controlnet/* (adetailer)
    
    Tracks requests for verification in tests.
    """
    
    def __init__(self):
        self.requests_made = []
        self.call_count = {"txt2img": 0, "img2img": 0, "upscale": 0, "controlnet": 0}
    
    def txt2img(self, payload: dict) -> dict:
        """Handle /sdapi/v1/txt2img request."""
        self.requests_made.append(("txt2img", payload))
        self.call_count["txt2img"] += 1
        
        return txt2img_response(
            prompt=payload.get("prompt", ""),
            seed=payload.get("seed", 42),
            width=payload.get("width", 512),
            height=payload.get("height", 512),
        )
    
    def img2img(self, payload: dict) -> dict:
        """Handle /sdapi/v1/img2img request."""
        self.requests_made.append(("img2img", payload))
        self.call_count["img2img"] += 1
        
        init_images = payload.get("init_images", [])
        init_image = init_images[0] if init_images else ""
        
        return img2img_response(
            prompt=payload.get("prompt", ""),
            init_image=init_image,
            seed=payload.get("seed", 42),
            width=payload.get("width", 512),
            height=payload.get("height", 512),
            denoising_strength=payload.get("denoising_strength", 0.75),
        )
    
    def upscale(self, payload: dict) -> dict:
        """Handle /sdapi/v1/extra-single-image request."""
        self.requests_made.append(("upscale", payload))
        self.call_count["upscale"] += 1
        
        return upscale_response(
            image=payload.get("image", ""),
            upscaler=payload.get("upscaler_1", "R-ESRGAN 4x+"),
            scale=payload.get("upscaling_resize", 2),
        )
    
    def controlnet(self, payload: dict) -> dict:
        """Handle /controlnet/* request (ADetailer)."""
        self.requests_made.append(("controlnet", payload))
        self.call_count["controlnet"] += 1
        
        return controlnet_response(
            prompt=payload.get("prompt", ""),
            control_image=payload.get("controlnet_input_image", [""])[0],
            module=payload.get("controlnet_module", "none"),
            model=payload.get("controlnet_model", "None"),
        )
    
    def reset(self):
        """Clear request history (for test isolation)."""
        self.requests_made.clear()
        self.call_count = {"txt2img": 0, "img2img": 0, "upscale": 0, "controlnet": 0}


# Singleton instance for CI tests
_mock_server: MockWebUIServer | None = None


def get_mock_server() -> MockWebUIServer:
    """Get or create singleton mock server."""
    global _mock_server
    if _mock_server is None:
        _mock_server = MockWebUIServer()
    return _mock_server
