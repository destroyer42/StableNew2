import itertools

import pytest

from src.api.healthcheck import WebUIHealthCheckTimeout, wait_for_webui_ready


class _Response:
    def __init__(self, status_code: int, payload=None):
        self.status_code = status_code
        self._payload = payload if payload is not None else []

    def json(self):
        return self._payload


def test_wait_for_webui_ready_retries_and_succeeds(monkeypatch):
    attempts = itertools.count()

    def fake_get(url, timeout):  # noqa: ARG001
        idx = next(attempts)
        if idx < 2:
            raise RuntimeError("transient")
        return _Response(200, payload=[])

    monkeypatch.setattr("requests.get", fake_get)

    assert wait_for_webui_ready("http://localhost:7860", timeout=1.0, poll_interval=0.01) is True


def test_wait_for_webui_ready_times_out(monkeypatch):
    def fake_get(url, timeout):  # noqa: ARG001
        return _Response(503)

    monkeypatch.setattr("requests.get", fake_get)

    with pytest.raises(WebUIHealthCheckTimeout):
        wait_for_webui_ready("http://localhost:7860", timeout=0.05, poll_interval=0.01)
