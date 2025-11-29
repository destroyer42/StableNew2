"""Tests for SDWebUIClient retry backoff behavior."""

from __future__ import annotations

from unittest.mock import Mock

import pytest
import requests

from src.api.client import SDWebUIClient


@pytest.fixture()
def client():
    """Create an SDWebUIClient with deterministic backoff."""
    return SDWebUIClient(max_retries=4, backoff_factor=1.0, jitter=0.0)


def test_retry_backoff_sequence(monkeypatch, client):
    """The client should apply exponential backoff between retry attempts."""

    attempt_counter = {"count": 0}
    sleep_calls: list[float] = []

    def fake_request(method, url, timeout=None, **kwargs):  # noqa: ANN001
        attempt_counter["count"] += 1
        if attempt_counter["count"] < 4:
            raise requests.exceptions.ConnectionError("boom")
        response = Mock()
        response.raise_for_status.return_value = None
        response.json.return_value = {"ok": True}
        return response

    def fake_sleep(duration: float) -> None:
        sleep_calls.append(duration)

    monkeypatch.setattr("src.api.client.requests.request", fake_request)
    monkeypatch.setattr(client, "_sleep", fake_sleep)

    response = client._perform_request("get", "/retry", timeout=1)

    assert response is not None
    assert attempt_counter["count"] == 4
    assert sleep_calls == [1.0, 2.0, 4.0]


def test_retry_terminates_after_max_attempts(monkeypatch):
    """The client should stop retrying after the configured attempts."""

    client = SDWebUIClient(max_retries=3, backoff_factor=1.0, jitter=0.0)
    attempt_counter = {"count": 0}
    sleep_calls: list[float] = []

    def fake_request(method, url, timeout=None, **kwargs):  # noqa: ANN001
        attempt_counter["count"] += 1
        raise requests.exceptions.HTTPError("nope")

    def fake_sleep(duration: float) -> None:
        sleep_calls.append(duration)

    monkeypatch.setattr("src.api.client.requests.request", fake_request)
    monkeypatch.setattr(client, "_sleep", fake_sleep)

    response = client._perform_request("post", "/retry", timeout=1)

    assert response is None
    assert attempt_counter["count"] == 3
    assert sleep_calls == [1.0, 2.0]
