import logging

import pytest
import requests

from src.api.healthcheck import (
    MODELS_PATH,
    OPTIONS_PATH,
    PROGRESS_PATH,
    WebUIHealthCheckTimeout,
    wait_for_webui_ready,
)


class _DummyResponse:
    def __init__(self, status_code: int, payload=None):
        self.status_code = status_code
        self._payload = payload if payload is not None else []

    def json(self):
        return self._payload


def test_wait_for_webui_ready_succeeds_when_models_endpoint_ready(monkeypatch):
    def fake_get(url, timeout):  # noqa: ARG001
        assert MODELS_PATH in url
        return _DummyResponse(200, payload=[{"name": "foo"}])

    monkeypatch.setattr("src.api.healthcheck.requests.get", fake_get)

    assert wait_for_webui_ready("http://127.0.0.1:7860", timeout=1.0, poll_interval=0.01) is True


def test_wait_for_webui_ready_does_not_return_true_on_progress_only(monkeypatch, caplog):
    caplog.set_level(logging.INFO)

    def fake_get(url, timeout):  # noqa: ARG001
        if PROGRESS_PATH in url:
            return _DummyResponse(200)
        if MODELS_PATH in url:
            return _DummyResponse(503)
        if OPTIONS_PATH in url:
            raise requests.exceptions.ConnectionError("models/options not ready")
        raise AssertionError(f"Unexpected URL: {url}")

    monkeypatch.setattr("src.api.healthcheck.requests.get", fake_get)

    with pytest.raises(WebUIHealthCheckTimeout):
        wait_for_webui_ready("http://127.0.0.1:7860", timeout=0.3, poll_interval=0.01)

    assert "WebUI API reachable but models/options not ready yet" in caplog.text


def test_wait_for_webui_ready_includes_last_error_in_timeout(monkeypatch):
    def fake_get(url, timeout):  # noqa: ARG001
        if MODELS_PATH in url:
            return _DummyResponse(503)
        if OPTIONS_PATH in url:
            return _DummyResponse(503)
        raise requests.exceptions.Timeout("still starting")

    monkeypatch.setattr("src.api.healthcheck.requests.get", fake_get)

    with pytest.raises(WebUIHealthCheckTimeout) as excinfo:
        wait_for_webui_ready("http://127.0.0.1:7860", timeout=0.2, poll_interval=0.01)

    assert OPTIONS_PATH in str(excinfo.value)
