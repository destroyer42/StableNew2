"""PR-IMG-FORGE-230: the once-per-run WebUI defaults must not send options the WebUI lacks.

Forge answers a write naming an unknown option (``DAT_tile``) with HTTP 500 and refuses the
whole write, so the conservative defaults for the options it does have were never confirmed.
"""

from __future__ import annotations

import requests_mock

from src.api.client import SDWebUIClient
from src.pipeline.executor import Pipeline
from src.utils import StructuredLogger

BASE_URL = "http://127.0.0.1:7871"
OPTIONS_URL = f"{BASE_URL}/sdapi/v1/options"

# What the managed Forge advertises: the ESRGAN/cache options, no DAT upscaler options.
FORGE_OPTIONS = {
    "img_max_size_mp": 200,
    "ESRGAN_tile": 192,
    "ESRGAN_tile_overlap": 8,
    "upscaling_max_images_in_cache": 5,
    "jpeg_quality": 80,
}


def _pipeline() -> Pipeline:
    client = SDWebUIClient(base_url=BASE_URL, options_write_enabled=True)
    client._sleep = lambda _seconds: None  # type: ignore[method-assign]
    return Pipeline(client, StructuredLogger())


def _options_posts(mocker: requests_mock.Mocker) -> list:
    return [
        r for r in mocker.request_history if r.method == "POST" and r.path == "/sdapi/v1/options"
    ]


def test_defaults_once_sends_only_advertised_options_and_is_not_repeated() -> None:
    pipeline = _pipeline()
    with requests_mock.Mocker() as m:
        m.get(OPTIONS_URL, json=FORGE_OPTIONS)
        m.post(OPTIONS_URL, json={})

        pipeline._apply_webui_defaults_once()
        pipeline._apply_webui_defaults_once()

        posts = _options_posts(m)
        assert len(posts) == 1  # once per run, not once per call
        assert posts[0].json() == {
            "img_max_size_mp": 8.0,
            "ESRGAN_tile": 768,
            "ESRGAN_tile_overlap": 64,
            "upscaling_max_images_in_cache": 4,
        }
    assert pipeline._webui_defaults_applied is True


def test_defaults_once_does_not_raise_when_the_write_is_rejected() -> None:
    pipeline = _pipeline()
    with requests_mock.Mocker() as m:
        m.get(OPTIONS_URL, json=FORGE_OPTIONS)
        m.post(OPTIONS_URL, status_code=500, text="KeyError: 'DAT_tile'")

        pipeline._apply_webui_defaults_once()

    # best-effort and attempted once: the run proceeds and does not loop on a refusing WebUI
    assert pipeline._webui_defaults_applied is True
