from __future__ import annotations

import pytest

from src.video.comfy_healthcheck import ComfyHealthCheckTimeout, validate_comfy_health, wait_for_comfy_ready


class _Response:
    def __init__(self, status_code: int, payload):
        self.status_code = status_code
        self._payload = payload

    def json(self):
        return self._payload


def test_wait_for_comfy_ready_succeeds_when_required_endpoints_are_ready(monkeypatch) -> None:
    responses = {
        "http://127.0.0.1:8188/system_stats": _Response(200, {"devices": []}),
        "http://127.0.0.1:8188/object_info": _Response(200, {"LTXLoader": {}}),
    }

    monkeypatch.setattr(
        "src.video.comfy_healthcheck.requests.get",
        lambda url, timeout: responses[url],
    )

    assert wait_for_comfy_ready("http://127.0.0.1:8188", timeout=0.1, poll_interval=0.01) is True


def test_wait_for_comfy_ready_times_out_when_object_info_never_recovers(monkeypatch) -> None:
    def fake_get(url, timeout):
        if url.endswith("/system_stats"):
            return _Response(200, {"devices": []})
        return _Response(500, {"error": "down"})

    monkeypatch.setattr("src.video.comfy_healthcheck.requests.get", fake_get)

    with pytest.raises(ComfyHealthCheckTimeout):
        wait_for_comfy_ready("http://127.0.0.1:8188", timeout=0.05, poll_interval=0.01)


def test_validate_comfy_health_reports_endpoint_failures(monkeypatch) -> None:
    def fake_get(url, timeout):
        if url.endswith("/system_stats"):
            return _Response(200, {"devices": []})
        return _Response(404, {"detail": "missing"})

    monkeypatch.setattr("src.video.comfy_healthcheck.requests.get", fake_get)

    report = validate_comfy_health("http://127.0.0.1:8188", timeout=0.05)

    assert report["healthy"] is False
    assert report["system_stats_ok"] is True
    assert report["object_info_ok"] is False
