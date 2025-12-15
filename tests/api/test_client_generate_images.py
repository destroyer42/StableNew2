from __future__ import annotations

from typing import Any

import requests

from src.api.client import SDWebUIClient
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
