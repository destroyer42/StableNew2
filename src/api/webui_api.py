from typing import Any

class WebUIAPI:
    def txt2img(self, **kwargs) -> dict[str, Any]:
        # Minimal stub for journey tests
        return {
            'images': [{'data': 'stub_txt2img_image'}],
            'info': '{"prompt": "%s"}' % kwargs.get('prompt', '')
        }

    def upscale_image(self, **kwargs) -> dict[str, Any]:
        # Minimal stub for journey tests
        return {
            'images': [{'data': 'stub_upscaled_image'}],
            'info': '{"upscale_factor": %s, "model": "%s"}' % (
                kwargs.get('upscale_factor', 2.0), kwargs.get('model', 'UltraSharp'))
        }
