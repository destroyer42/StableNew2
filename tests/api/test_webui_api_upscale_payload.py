"""Tests for the upscale payload builder in SDWebUIClient."""

from __future__ import annotations

import requests_mock

from src.api.client import SDWebUIClient


def _no_sleep(_duration: float) -> None:
    """No-op sleep replacement used in tests."""


def test_upscale_image_payload_uses_data_url() -> None:
    """Ensure the upscale payload sends a valid data URL."""
    client = SDWebUIClient()
    client._sleep = _no_sleep  # Avoid waiting while retry policy is configured
    with requests_mock.Mocker() as mocker:
        mocker.post(
            f"{client.base_url}/sdapi/v1/extra-single-image",
            json={"image": "upscaled_image"},
        )
        result = client.upscale_image("raw_base64_data", "R-ESRGAN 4x+", 2.0)
        assert result is not None
        body = mocker.last_request.json()
        assert body["image"].startswith("data:image/png;base64,")
        assert body["image"].endswith("raw_base64_data")
        assert body["upscaler_1"] == "R-ESRGAN 4x+"
        assert body["upscaling_resize"] == 2.0


def test_upscale_image_handles_http_error() -> None:
    """HTTP errors from the WebUI should not raise and should be retried."""
    client = SDWebUIClient()
    client._sleep = _no_sleep
    with requests_mock.Mocker() as mocker:
        mocker.post(
            f"{client.base_url}/sdapi/v1/extra-single-image",
            status_code=500,
            text="Invalid encoded image",
        )
        result = client.upscale_image("raw_base64_data", "Latent", 1.5)
        assert result is None
        assert len(mocker.request_history) == 2
