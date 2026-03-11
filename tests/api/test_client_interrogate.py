from __future__ import annotations

import requests_mock

from src.api.client import SDWebUIClient

API_BASE_URL = "http://127.0.0.1:7860"


def test_interrogate_success() -> None:
    client = SDWebUIClient()

    with requests_mock.Mocker() as mocker:
        mocker.post(
            f"{API_BASE_URL}/sdapi/v1/interrogate",
            json={"caption": "portrait, smiling"},
        )

        response = client.interrogate("ZmFrZQ==")

    assert response == "portrait, smiling"
    assert mocker.last_request.json()["model"] == "clip"
    assert mocker.last_request.json()["image"].startswith("data:image/png;base64,")
