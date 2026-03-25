from __future__ import annotations

import json
from typing import Any

import requests
import pytest

from src.api.client import SDWebUIClient, WebUIUnavailableError
from src.api.types import GenerateErrorCode


def test_generate_images_success(monkeypatch):
    client = SDWebUIClient()

    def fake_txt2img(payload):
        return {"images": ["img"], "info": {"steps": 10}}

    monkeypatch.setattr(client, "txt2img", fake_txt2img)
    outcome = client.generate_images(stage="txt2img", payload={})

    assert outcome.ok
    assert outcome.result is not None
    assert outcome.result.stage == "txt2img"
    assert outcome.result.info["steps"] == 10


def test_generate_images_connection_error(monkeypatch):
    client = SDWebUIClient()

    def fake_txt2img(payload):
        raise requests.ConnectionError("network fail")

    monkeypatch.setattr(client, "txt2img", fake_txt2img)
    outcome = client.generate_images(stage="txt2img", payload={})

    assert not outcome.ok
    assert outcome.error is not None
    assert outcome.error.code == GenerateErrorCode.CONNECTION
    assert "network fail" in outcome.error.message


def test_generate_images_webui_unavailable_error_maps_to_connection(monkeypatch):
    client = SDWebUIClient()

    def fake_txt2img(payload):
        raise WebUIUnavailableError(
            endpoint="/sdapi/v1/txt2img",
            method="POST",
            stage="txt2img",
            reason="Read timed out",
        )

    monkeypatch.setattr(client, "txt2img", fake_txt2img)
    outcome = client.generate_images(stage="txt2img", payload={})

    assert not outcome.ok
    assert outcome.error is not None
    assert outcome.error.code == GenerateErrorCode.CONNECTION
    assert "WebUI unavailable" in outcome.error.message


def test_generate_images_http_error_uses_webui_error_payload(monkeypatch):
    client = SDWebUIClient()

    def fake_img2img(payload, *, policy=None):
        exc = requests.HTTPError("500 Server Error: Internal Server Error for url: http://127.0.0.1:7860/sdapi/v1/img2img")
        exc.diagnostics_context = {
            "request_summary": {
                "status": 500,
                "response_snippet": json.dumps(
                    {
                        "error": "NansException",
                        "errors": "A tensor with NaNs was produced in Unet.",
                    }
                ),
            }
        }
        raise exc

    monkeypatch.setattr(client, "img2img", fake_img2img)
    outcome = client.generate_images(stage="adetailer", payload={})

    assert not outcome.ok
    assert outcome.error is not None
    assert outcome.error.code == GenerateErrorCode.UNKNOWN
    assert outcome.error.message == "NansException: A tensor with NaNs was produced in Unet."


class _HttpErrorResponse:
    def __init__(self) -> None:
        self.status_code = 500
        self.text = json.dumps(
            {
                "error": "NansException",
                "errors": "A tensor with NaNs was produced in Unet.",
            }
        )

    def raise_for_status(self) -> None:
        raise requests.HTTPError("500 Server Error", response=self)

    def close(self) -> None:
        return None


class _SessionWithHttpError:
    def request(self, *args, **kwargs):
        return _HttpErrorResponse()


def test_perform_request_raises_final_http_error_with_diagnostics() -> None:
    client = SDWebUIClient()
    client._session = _SessionWithHttpError()

    with pytest.raises(requests.HTTPError) as exc_info:
        client._perform_request(
            "post",
            "/sdapi/v1/img2img",
            json={"prompt": "test"},
            stage="img2img",
            max_retries=1,
        )

    diagnostics = getattr(exc_info.value, "diagnostics_context", None)
    assert isinstance(diagnostics, dict)
    assert diagnostics["request_summary"]["status"] == 500
    assert "NansException" in diagnostics["request_summary"]["response_snippet"]


class _FakeResponse:
    def __init__(self) -> None:
        self.closed = False

    def json(self) -> dict[str, Any]:
        raise ValueError("parse failure")

    def close(self) -> None:
        self.closed = True


def test_txt2img_closes_response(monkeypatch):
    client = SDWebUIClient()
    fake_response = _FakeResponse()
    monkeypatch.setattr(client, "_perform_request", lambda *args, **kwargs: fake_response)

    result = client.txt2img({})

    assert result is None
    assert fake_response.closed
