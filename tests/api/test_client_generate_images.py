from __future__ import annotations

import requests

import pytest

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
