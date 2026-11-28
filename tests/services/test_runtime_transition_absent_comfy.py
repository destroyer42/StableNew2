"""The per-job Comfy presence check answers at once when nothing listens on a loopback port (hermetic: fakes only).

Windows takes about two seconds to refuse a closed localhost port, so the HTTP probe spent its whole 0.5 s timeout
before every image job that ran without ComfyUI.
"""

from __future__ import annotations

from types import SimpleNamespace

import psutil
import pytest

from src.services import runtime_transition_service as transition


@pytest.fixture
def probe(monkeypatch):
    """The configured Comfy URL, the machine's listening ports and a recorded HTTP probe."""

    state = SimpleNamespace(url="http://127.0.0.1:8000", listening=[], http=[], answer="occupied")

    def http(base_url: str, *, timeout: float) -> str:
        state.http.append(base_url)
        return state.answer

    def connections(kind: str):
        assert kind == "tcp"
        return [
            SimpleNamespace(status=status, laddr=SimpleNamespace(ip="0.0.0.0", port=port))
            for port, status in state.listening
        ]

    monkeypatch.setattr(transition, "_configured_endpoint", lambda *_a: state.url)
    monkeypatch.setattr("src.video.comfy_healthcheck.probe_comfy_endpoint", http)
    monkeypatch.setattr(psutil, "net_connections", connections)
    return state


@pytest.mark.parametrize(
    "url", ["http://127.0.0.1:8000", "http://localhost:8000", "http://[::1]:8000"]
)
def test_no_listener_on_a_loopback_port_is_absent_without_an_http_probe(probe, url):
    probe.url = url
    probe.listening = [(7860, psutil.CONN_LISTEN), (8000, psutil.CONN_TIME_WAIT)]
    assert transition._default_comfy_endpoint_presence() is False
    assert probe.http == []


def test_a_comfy_that_starts_is_seen_by_the_very_next_check(probe):
    assert transition._default_comfy_endpoint_presence() is False
    probe.listening = [(8000, psutil.CONN_LISTEN)]
    assert transition._default_comfy_endpoint_presence() is True
    assert probe.http == [probe.url]


def test_a_listener_is_still_judged_by_the_http_probe(probe):
    probe.listening = [(8000, psutil.CONN_LISTEN)]
    probe.answer = "free"
    assert transition._default_comfy_endpoint_presence() is False
    assert probe.http == [probe.url]


def test_another_host_is_always_probed(probe):
    probe.url = "http://comfy.example.test:8000"
    assert transition._default_comfy_endpoint_presence() is True
    assert probe.http == [probe.url]


def test_when_the_ports_cannot_be_listed_the_http_probe_decides(probe, monkeypatch):
    def refused(kind: str):
        raise psutil.AccessDenied()

    monkeypatch.setattr(psutil, "net_connections", refused)
    assert transition._default_comfy_endpoint_presence() is True
    assert probe.http == [probe.url]
