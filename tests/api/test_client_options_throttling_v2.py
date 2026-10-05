import contextlib
import time
from types import SimpleNamespace
from unittest import mock

import pytest

from src.api import client as client_module
from src.api.client import SDWebUIClient


class _ClockedTime:
    """Stands in for ``time`` inside the client module: real time, controllable monotonic."""

    def __init__(self, clock: SimpleNamespace) -> None:
        self._clock = clock

    def monotonic(self) -> float:
        return self._clock.now

    def __getattr__(self, name: str):
        return getattr(time, name)


@pytest.fixture
def low_uptime_clock(monkeypatch) -> SimpleNamespace:
    """A host that booted a few seconds ago: monotonic() is far below the throttle interval."""

    clock = SimpleNamespace(now=5.0)
    monkeypatch.setattr(client_module, "time", _ClockedTime(clock))
    return clock


def test_options_post_skipped_when_readiness_false(monkeypatch):
    client = SDWebUIClient()
    client.set_options_write_enabled(True)
    client.set_options_readiness_provider(lambda: False)
    ctx_mock = mock.Mock(return_value=contextlib.nullcontext(mock.Mock()))
    monkeypatch.setattr(SDWebUIClient, "_request_context", ctx_mock)

    assert client.set_model("foo") is False
    ctx_mock.assert_not_called()
    assert client.last_options_write_failure == "readiness"


def test_options_post_throttled(monkeypatch):
    client = SDWebUIClient()
    client.set_options_write_enabled(True)
    client._options_min_interval_seconds = 60.0
    client.set_options_readiness_provider(lambda: True)
    ctx_mock = mock.Mock(return_value=contextlib.nullcontext(mock.Mock()))
    monkeypatch.setattr(SDWebUIClient, "_request_context", ctx_mock)

    client.set_model("first")
    client.set_model("second")

    assert ctx_mock.call_count == 1
    assert client.last_options_write_failure == "throttle"


def test_set_model_records_http_failure(monkeypatch):
    client = SDWebUIClient()
    client.set_options_write_enabled(True)
    client.set_options_readiness_provider(lambda: True)
    ctx_mock = mock.Mock(return_value=contextlib.nullcontext(None))
    monkeypatch.setattr(SDWebUIClient, "_request_context", ctx_mock)

    assert client.set_model("foo") is False
    assert client.last_options_write_failure == "http"


def test_first_options_write_is_allowed_on_a_freshly_booted_host(monkeypatch, low_uptime_clock):
    client = SDWebUIClient()
    client.set_options_write_enabled(True)
    client._options_min_interval_seconds = 60.0
    client.set_options_readiness_provider(lambda: True)
    ctx_mock = mock.Mock(return_value=contextlib.nullcontext(mock.Mock()))
    monkeypatch.setattr(SDWebUIClient, "_request_context", ctx_mock)

    assert low_uptime_clock.now < client._options_min_interval_seconds
    client.set_model("first")

    assert ctx_mock.call_count == 1, "the first write must not be throttled by host uptime"

    # A write inside the interval is still throttled.
    low_uptime_clock.now += 10.0
    client.set_model("second")
    assert ctx_mock.call_count == 1
    assert client.last_options_write_failure == "throttle"

    # After the interval a write is allowed again.
    low_uptime_clock.now += 60.0
    client.set_model("third")
    assert ctx_mock.call_count == 2
