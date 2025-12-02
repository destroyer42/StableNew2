from typing import Any

class WebUIAPI:
    def txt2img(self, *, prompt: str = "", **kwargs: Any) -> dict[str, Any]:
        # Minimal stub for journey tests
        return {
            "images": [{"data": "stub_txt2img_image"}],
            "info": '{"prompt": "%s"}' % prompt,
        }

    def upscale_image(
        self,
        *,
        image: Any,
        upscale_factor: float,
        model: str,
        tile_size: int | None = None,
        prompt: str | None = None,
        **kwargs: Any,
    ) -> dict[str, Any]:
        # Minimal stub for journey tests
        return {
            "images": [{"data": "stub_upscaled_image"}],
            "info": '{"upscale_factor": %s, "model": "%s"}' % (upscale_factor, model or "UltraSharp"),
        }
