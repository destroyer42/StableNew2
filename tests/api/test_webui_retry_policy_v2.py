"""Tests for the new SDWebUIClient retry policy integration (Phase 7)."""

from __future__ import annotations

import json

import pytest
import requests

from src.api.client import SDWebUIClient, WebUIGenerationOutcomeUnknownError
from src.api.types import GenerateErrorCode


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


class _StructuredOomResponse(requests.Response):
    """500 response stub carrying a structured CUDA OOM payload."""

    def __init__(self) -> None:
        super().__init__()
        self.status_code = 500
        self._content = json.dumps(
            {
                "error": "RuntimeError",
                "errors": "CUDA error: out of memory",
            }
        ).encode("utf-8")

    def raise_for_status(self) -> None:
        raise requests.HTTPError("500 Server Error", response=self)


def _setup_connect_timeout_requests(failures: int) -> tuple[list[str], callable]:
    """Return a callable that fails before connection, then succeeds."""

    attempts: list[str] = []
    calls = {"count": 0}

    def _fake_request(self, method: str, url: str, **kwargs: object) -> requests.Response:
        calls["count"] += 1
        attempts.append(method)
        if calls["count"] <= failures:
            raise requests.ConnectTimeout("connection was not established")
        return _DummyResponse()

    return attempts, _fake_request


def test_txt2img_retries_safe_connect_timeout_with_stage_policy(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """TXT2IMG retains retries when connection establishment is known-safe."""

    attempts, stub_request = _setup_connect_timeout_requests(failures=2)
    monkeypatch.setattr("src.api.client.requests.Session.request", stub_request)
    client = SDWebUIClient()
    client._sleep = lambda _: None

    result = client.txt2img({"prompt": "retry test"})
    assert result is not None
    assert len(attempts) == 3


def test_txt2img_read_timeout_does_not_replay_generation_post(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A response loss after dispatch becomes an explicit unknown outcome."""
    attempts: list[str] = []

    def _fake_request(self, method: str, url: str, **kwargs: object) -> requests.Response:
        attempts.append(method)
        if len(attempts) == 1:
            raise requests.ReadTimeout("response lost after dispatch")
        return _DummyResponse()

    monkeypatch.setattr("src.api.client.requests.Session.request", _fake_request)
    client = SDWebUIClient()
    client._sleep = lambda _: None
    resets: list[str] = []
    original_reset = client._reset_http_session

    def _record_reset() -> None:
        resets.append("reset")
        original_reset()

    monkeypatch.setattr(client, "_reset_http_session", _record_reset)

    outcome = client.generate_images(stage="txt2img", payload={"prompt": "ambiguous"})

    assert outcome.error is not None
    assert outcome.error.code == GenerateErrorCode.OUTCOME_UNKNOWN
    assert outcome.error.details["request_may_have_executed"] is True
    assert outcome.error.details["attempt_count"] == 1
    assert attempts == ["POST"]
    assert resets == ["reset"]


def test_img2img_read_timeout_does_not_replay_generation_post(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Img2img receives the same ambiguous-outcome protection."""
    attempts: list[str] = []

    def _fake_request(self, method: str, url: str, **kwargs: object) -> requests.Response:
        attempts.append(method)
        if len(attempts) == 1:
            raise requests.ReadTimeout("response lost after dispatch")
        return _DummyResponse()

    monkeypatch.setattr("src.api.client.requests.Session.request", _fake_request)
    client = SDWebUIClient()
    client._sleep = lambda _: None

    outcome = client.generate_images(stage="img2img", payload={"prompt": "ambiguous"})

    assert outcome.error is not None
    assert outcome.error.code == GenerateErrorCode.OUTCOME_UNKNOWN
    assert attempts == ["POST"]


def test_ambiguous_generation_error_retains_transport_contract(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def _fake_request(self, method: str, url: str, **kwargs: object) -> requests.Response:
        raise requests.ReadTimeout("response lost after dispatch")

    monkeypatch.setattr("src.api.client.requests.Session.request", _fake_request)
    client = SDWebUIClient()

    with pytest.raises(WebUIGenerationOutcomeUnknownError) as exc_info:
        client._perform_request(
            "post",
            "/sdapi/v1/txt2img",
            json={"prompt": "ambiguous"},
            stage="txt2img",
        )

    error = exc_info.value
    assert error.endpoint == "/sdapi/v1/txt2img"
    assert error.stage == "txt2img"
    assert error.attempt_count == 1
    assert error.request_may_have_executed is True
    assert isinstance(error.original_exception, requests.ReadTimeout)


def test_retry_callback_records_attempts(monkeypatch: pytest.MonkeyPatch) -> None:
    """Retry callback receives stage details for each failed attempt."""

    attempts, stub_request = _setup_connect_timeout_requests(failures=1)
    monkeypatch.setattr("src.api.client.requests.Session.request", stub_request)
    logged: list[tuple[str, int, int, str]] = []

    client = SDWebUIClient(
        retry_callback=lambda stage, attempt_index, max_attempts, reason: logged.append(
            (stage, attempt_index, max_attempts, reason)
        )
    )
    client._sleep = lambda _: None

    result = client.txt2img({"prompt": "callback test"})
    assert result is not None
    assert len(attempts) == 2
    assert logged
    stage, attempt_index, max_attempts, reason = logged[0]
    assert stage == "txt2img"
    assert attempt_index == 1
    assert max_attempts == 3
    assert reason == "ConnectTimeout"


def test_connect_timeout_retry_recycles_http_session(monkeypatch: pytest.MonkeyPatch) -> None:
    """Known pre-connect retries rebuild the HTTP session before the next attempt."""

    attempts, stub_request = _setup_connect_timeout_requests(failures=1)
    monkeypatch.setattr("src.api.client.requests.Session.request", stub_request)
    client = SDWebUIClient()
    client._sleep = lambda _: None

    resets: list[str] = []
    original_reset = client._reset_http_session

    def _wrapped_reset() -> None:
        resets.append("reset")
        original_reset()

    monkeypatch.setattr(client, "_reset_http_session", _wrapped_reset)

    result = client.txt2img({"prompt": "session reset test"})

    assert result is not None
    assert len(attempts) == 2
    assert resets == ["reset"]


def test_generic_connection_error_does_not_replay_generation_post(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    attempts: list[str] = []

    def _fake_request(self, method: str, url: str, **kwargs: object) -> requests.Response:
        attempts.append(method)
        raise requests.ConnectionError("connection vanished")

    monkeypatch.setattr("src.api.client.requests.Session.request", _fake_request)
    client = SDWebUIClient()

    outcome = client.generate_images(stage="txt2img", payload={"prompt": "ambiguous"})

    assert outcome.error is not None
    assert outcome.error.code == GenerateErrorCode.OUTCOME_UNKNOWN
    assert attempts == ["POST"]


def test_adetailer_remains_single_attempt_on_ambiguous_timeout(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    attempts: list[str] = []

    def _fake_request(self, method: str, url: str, **kwargs: object) -> requests.Response:
        attempts.append(method)
        raise requests.ReadTimeout("response lost after dispatch")

    monkeypatch.setattr("src.api.client.requests.Session.request", _fake_request)
    client = SDWebUIClient()

    outcome = client.generate_images(stage="adetailer", payload={"prompt": "ambiguous"})

    assert outcome.error is not None
    assert outcome.error.code == GenerateErrorCode.OUTCOME_UNKNOWN
    assert attempts == ["POST"]


def test_get_read_timeout_retains_existing_retry_behavior(monkeypatch: pytest.MonkeyPatch) -> None:
    attempts: list[str] = []

    def _fake_request(self, method: str, url: str, **kwargs: object) -> requests.Response:
        attempts.append(method)
        if len(attempts) == 1:
            raise requests.ReadTimeout("resource response lost")
        return _DummyResponse()

    stub_request = _fake_request
    monkeypatch.setattr("src.api.client.requests.Session.request", stub_request)
    client = SDWebUIClient()
    client._sleep = lambda _: None

    response = client._perform_request("get", "/sdapi/v1/samplers", max_retries=2)

    assert response is not None
    assert attempts == ["GET", "GET"]


def test_txt2img_structured_cuda_oom_http_500_is_fail_fast(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    attempts: list[str] = []

    def _fake_request(self, method: str, url: str, **kwargs: object) -> requests.Response:
        attempts.append(method)
        return _StructuredOomResponse()

    monkeypatch.setattr("src.api.client.requests.Session.request", _fake_request)
    client = SDWebUIClient()
    client._sleep = lambda _: None

    with pytest.raises(requests.HTTPError) as exc_info:
        client._perform_request(
            "post",
            "/sdapi/v1/txt2img",
            json={"prompt": "oom"},
            stage="txt2img",
        )

    assert len(attempts) == 1
    assert getattr(exc_info.value, "fail_fast_reason", None) == "cuda_oom"
