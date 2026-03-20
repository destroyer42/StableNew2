from __future__ import annotations

from unittest import mock

import pytest

from src.video.comfy_api_client import ComfyApiClient


def test_comfy_api_client_reads_system_stats() -> None:
    session = mock.Mock()
    response = mock.Mock()
    response.json.return_value = {"devices": []}
    response.raise_for_status.return_value = None
    session.get.return_value = response

    client = ComfyApiClient(base_url="http://127.0.0.1:8188", session=session)

    assert client.get_system_stats() == {"devices": []}
    session.get.assert_called_once_with("http://127.0.0.1:8188/system_stats", timeout=5.0)


def test_comfy_api_client_queue_prompt_posts_payload() -> None:
    session = mock.Mock()
    response = mock.Mock()
    response.json.return_value = {"prompt_id": "abc123"}
    response.raise_for_status.return_value = None
    session.post.return_value = response

    client = ComfyApiClient(base_url="http://127.0.0.1:8188", session=session)

    result = client.queue_prompt({"prompt": {"1": {"class_type": "Empty"}}})

    assert result["prompt_id"] == "abc123"
    session.post.assert_called_once()


def test_comfy_api_client_rejects_non_dict_json() -> None:
    session = mock.Mock()
    response = mock.Mock()
    response.json.return_value = []
    response.raise_for_status.return_value = None
    session.get.return_value = response

    client = ComfyApiClient(session=session)

    with pytest.raises(RuntimeError):
        client.get_object_info()


def test_comfy_api_client_reads_prompt_history() -> None:
    session = mock.Mock()
    response = mock.Mock()
    response.json.return_value = {"prompt-123": {"outputs": {}}}
    response.raise_for_status.return_value = None
    session.get.return_value = response

    client = ComfyApiClient(base_url="http://127.0.0.1:8188", session=session)

    result = client.get_history("prompt-123")

    assert result == {"prompt-123": {"outputs": {}}}
    session.get.assert_called_once_with("http://127.0.0.1:8188/history/prompt-123", timeout=10.0)
