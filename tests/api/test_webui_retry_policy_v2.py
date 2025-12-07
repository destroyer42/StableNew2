"""Tests for the new SDWebUIClient retry policy integration (Phase 7)."""

from __future__ import annotations

import json

import pytest
import requests

from src.api.client import SDWebUIClient


class _DummyResponse(requests.Response):
    """Minimal response stub that can return JSON."""

    def __init__(self, payload: dict[str, object] | None = None, status_code: int = 200) -> None:
        super().__init__()
        self.status_code = status_code
        content = payload or {"images": [], "info": {}, "parameters": {}}
        self._content = json.dumps(content).encode("utf-8")

    def raise_for_status(self) -> None:
        if self.status_code >= 400:
            raise requests.HTTPError("failed")

    def json(self) -> dict[str, object]:
        payload = super().json()
        if isinstance(payload, dict):
            return payload
        return {}


def _setup_retry_requests(failures: int) -> tuple[list[str], callable]:
    """Return a callable that fails the first `failures` attempts and succeeds thereafter."""

    attempts: list[str] = []
    calls = {"count": 0}

    def _fake_request(method: str, url: str, **kwargs: object) -> requests.Response:
        calls["count"] += 1
        attempts.append(method)
        if calls["count"] <= failures:
            raise requests.exceptions.Timeout("transient")
        return _DummyResponse()

    return attempts, _fake_request


def test_txt2img_retries_with_stage_policy(monkeypatch: pytest.MonkeyPatch) -> None:
    """TXT2IMG requests honor the stage policy, calling the API multiple times."""

    attempts, stub_request = _setup_retry_requests(failures=2)
    monkeypatch.setattr("src.api.client.requests.request", stub_request)
    client = SDWebUIClient()
    client._sleep = lambda _: None

    result = client.txt2img({"prompt": "retry test"})
    assert result is not None
    assert len(attempts) == 3


def test_retry_callback_records_attempts(monkeypatch: pytest.MonkeyPatch) -> None:
    """Retry callback receives stage details for each failed attempt."""

    attempts, stub_request = _setup_retry_requests(failures=1)
    monkeypatch.setattr("src.api.client.requests.request", stub_request)
    logged: list[tuple[str, int, int, str]] = []

    client = SDWebUIClient(retry_callback=lambda stage, attempt_index, max_attempts, reason: logged.append((stage, attempt_index, max_attempts, reason)))
    client._sleep = lambda _: None

    result = client.txt2img({"prompt": "callback test"})
    assert result is not None
    assert len(attempts) == 2
    assert logged
    stage, attempt_index, max_attempts, reason = logged[0]
    assert stage == "txt2img"
    assert attempt_index == 1
    assert max_attempts == 3
    assert reason in {"Timeout", "TimeoutError", "requests.exceptions.Timeout"}
