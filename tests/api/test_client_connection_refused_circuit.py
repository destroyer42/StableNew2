"""A refused GET (nothing listening) must not cost three attempts and a backoff per resource getter."""

from __future__ import annotations

import json
from types import SimpleNamespace

import pytest
import requests
from urllib3.exceptions import MaxRetryError, NewConnectionError

from src.api import client as client_module
from src.api.client import (
    CONNECTION_REFUSED_CIRCUIT_SEC,
    SDWebUIClient,
    _is_connection_refused,
)


def _refused() -> requests.ConnectionError:
    """The exception chain requests raises when the port is closed."""

    refused = ConnectionRefusedError(
        10061, "No connection could be made because the target machine actively refused it"
    )
    new_connection = NewConnectionError(None, "Failed to establish a new connection")  # type: ignore[arg-type]
    new_connection.__cause__ = refused
    retry = MaxRetryError(None, "/sdapi/v1/sd-models", reason=new_connection)  # type: ignore[arg-type]
    return requests.ConnectionError(retry)


class _Ok(requests.Response):
    def __init__(self, payload: object) -> None:
        super().__init__()
        self.status_code = 200
        self._content = json.dumps(payload).encode("utf-8")

    def raise_for_status(self) -> None:
        return None


@pytest.fixture
def clocked(monkeypatch) -> SimpleNamespace:
    clock = SimpleNamespace(now=1000.0)
    monkeypatch.setattr(client_module.time, "monotonic", lambda: clock.now)
    return clock


def _client(monkeypatch, behaviours):
    """A client whose HTTP layer plays ``behaviours`` in order (an exception instance is raised)."""

    client = SDWebUIClient()
    sleeps: list[float] = []
    calls: list[tuple[str, str]] = []
    queue = list(behaviours)

    def _request(method, url, **_kwargs):
        calls.append((method, url))
        item = queue.pop(0) if len(queue) > 1 else queue[0]
        if isinstance(item, BaseException):
            raise item
        return item

    monkeypatch.setattr(client._session, "request", _request)
    monkeypatch.setattr(client, "_sleep", lambda duration: sleeps.append(duration))
    monkeypatch.setattr(
        client, "_reset_http_session", lambda: None
    )  # keep the fake in place across retries
    return client, calls, sleeps


def test_a_refused_get_is_attempted_once_without_backoff(monkeypatch, clocked) -> None:
    client, calls, sleeps = _client(monkeypatch, [_refused()])

    with pytest.raises(requests.ConnectionError):
        client._perform_request("GET", "/sdapi/v1/sd-models")

    assert len(calls) == 1
    assert sleeps == []


def test_other_getters_fail_instantly_while_the_circuit_is_open(monkeypatch, clocked) -> None:
    client, calls, _sleeps = _client(monkeypatch, [_refused()])
    with pytest.raises(requests.ConnectionError):
        client._perform_request("GET", "/sdapi/v1/sd-models")

    for endpoint in ("/sdapi/v1/sd-vae", "/sdapi/v1/samplers", "/sdapi/v1/sd-modules"):
        with pytest.raises(requests.ConnectionError, match="refused moments ago"):
            client._perform_request("GET", endpoint)

    assert len(calls) == 1  # no network call for the three that followed


def test_resource_getters_raise_the_same_error_instantly_while_open(monkeypatch, clocked) -> None:
    client, calls, _sleeps = _client(monkeypatch, [_refused()])

    with pytest.raises(requests.ConnectionError):
        client.get_models()
    with pytest.raises(requests.ConnectionError, match="refused moments ago"):
        client.get_vae_models()

    assert len(calls) == 1


def test_the_circuit_closes_after_its_window(monkeypatch, clocked) -> None:
    client, calls, _sleeps = _client(monkeypatch, [_refused(), _Ok([{"title": "m"}])])
    with pytest.raises(requests.ConnectionError):
        client.get_models()
    clocked.now += CONNECTION_REFUSED_CIRCUIT_SEC + 0.1

    assert client.get_vae_models() == [{"title": "m"}]
    assert len(calls) == 2


def test_clearing_runtime_failure_state_closes_the_circuit_when_the_backend_is_ready(
    monkeypatch, clocked
) -> None:
    client, calls, _sleeps = _client(monkeypatch, [_refused(), _Ok([{"title": "m"}])])
    with pytest.raises(requests.ConnectionError):
        client.get_models()

    client.clear_runtime_failure_state()  # the controller calls this when the backend is proven READY

    assert client.get_vae_models() == [{"title": "m"}]
    assert len(calls) == 2


def test_a_success_after_a_refusal_resets_the_circuit(monkeypatch, clocked) -> None:
    client, _calls, _sleeps = _client(monkeypatch, [_refused(), _Ok([])])
    with pytest.raises(requests.ConnectionError):
        client._perform_request("GET", "/sdapi/v1/sd-models")
    assert client._connection_refused_until > clocked.now

    clocked.now += CONNECTION_REFUSED_CIRCUIT_SEC + 0.1
    assert client._perform_request("GET", "/sdapi/v1/sd-models") is not None

    assert client._connection_refused_until == 0.0


def test_non_refused_get_failures_still_retry_with_backoff(monkeypatch, clocked) -> None:
    client, calls, sleeps = _client(monkeypatch, [requests.ReadTimeout("slow"), _Ok([])])

    assert client._perform_request("GET", "/sdapi/v1/sd-models") is not None

    assert len(calls) == 2
    assert len(sleeps) == 1


def test_a_refused_post_keeps_its_existing_retry_behaviour(monkeypatch, clocked) -> None:
    client, calls, _sleeps = _client(monkeypatch, [_refused()])

    with pytest.raises(requests.ConnectionError):
        client._perform_request("POST", "/sdapi/v1/options", json={"k": "v"})

    assert len(calls) == client.max_retries  # POST is unchanged
    assert client._connection_refused_until == 0.0


def test_refusal_detection_follows_the_exception_chain() -> None:
    assert _is_connection_refused(_refused())
    assert _is_connection_refused(ConnectionRefusedError())
    assert _is_connection_refused(OSError(111, "Connection refused"))
    assert not _is_connection_refused(requests.ReadTimeout("slow"))
    assert not _is_connection_refused(requests.ConnectionError("reset by peer"))
    assert not _is_connection_refused(ValueError("nope"))
