"""The typed transport: which failures are safe to retry, and which must never be (audit E1, P3-4)."""

from __future__ import annotations

import contextlib
import socket
import threading
from collections.abc import Iterator
from unittest import mock

import pytest
import requests

from src.api.http_transport import (
    DefiniteRefusal,
    DispatchOutcomeUnknown,
    EndpointUnavailable,
    HttpTransport,
    MalformedResponse,
    RequestPolicy,
)


def _response(status: int = 200, payload=None, text: str = "") -> mock.Mock:
    response = mock.Mock()
    response.status_code = status
    response.text = text
    response.json.return_value = {} if payload is None else payload
    return response


# --- classification against a real socket ---------------------------------------------------------


def _closed_port() -> int:
    with socket.socket() as probe:
        probe.bind(("127.0.0.1", 0))
        return probe.getsockname()[1]


@contextlib.contextmanager
def _server(behaviour: str) -> Iterator[int]:
    """A throwaway local server: ``silent`` accepts and never answers, ``hangup`` accepts, reads, then closes."""

    listener = socket.socket()
    listener.bind(("127.0.0.1", 0))
    listener.listen(4)
    listener.settimeout(0.2)
    stop = threading.Event()
    held: list[socket.socket] = []

    def _serve() -> None:
        while not stop.is_set():
            try:
                conn, _ = listener.accept()
            except (TimeoutError, OSError):
                continue
            if behaviour == "hangup":
                conn.settimeout(1.0)
                with contextlib.suppress(OSError):
                    conn.recv(65536)
                conn.close()
            else:
                held.append(conn)

    thread = threading.Thread(target=_serve, daemon=True)
    thread.start()
    try:
        yield listener.getsockname()[1]
    finally:
        stop.set()
        thread.join(timeout=2)
        for conn in held:
            conn.close()
        listener.close()


def test_connection_refused_is_endpoint_unavailable() -> None:
    transport = HttpTransport(f"http://127.0.0.1:{_closed_port()}")
    with pytest.raises(EndpointUnavailable):
        transport.request_json("GET", "/x", policy=RequestPolicy(timeout=2.0, idempotent=True))


def test_a_read_timeout_is_dispatch_outcome_unknown() -> None:
    with _server("silent") as port:
        transport = HttpTransport(f"http://127.0.0.1:{port}")
        with pytest.raises(DispatchOutcomeUnknown):
            transport.request_json("POST", "/prompt", policy=RequestPolicy(timeout=0.4), json={})


def test_a_connection_dropped_after_sending_is_dispatch_outcome_unknown() -> None:
    with _server("hangup") as port:
        transport = HttpTransport(f"http://127.0.0.1:{port}")
        with pytest.raises(DispatchOutcomeUnknown):
            transport.request_json("POST", "/prompt", policy=RequestPolicy(timeout=3.0), json={})


# --- status and payload handling ------------------------------------------------------------------


def test_an_error_status_is_a_definite_refusal_with_a_bounded_body() -> None:
    session = mock.Mock()
    session.get.return_value = _response(500, text="x" * 5000)
    transport = HttpTransport("http://h", session)
    with pytest.raises(DefiniteRefusal) as caught:
        transport.request_json("GET", "/y", policy=RequestPolicy())
    assert caught.value.status_code == 500
    assert len(caught.value.body) == 2000
    assert "HTTP 500" in str(caught.value)


def test_non_json_and_non_dict_payloads_are_malformed() -> None:
    session = mock.Mock()
    bad_json = _response()
    bad_json.json.side_effect = ValueError("no json")
    session.get.return_value = bad_json
    transport = HttpTransport("http://h", session)
    with pytest.raises(MalformedResponse):
        transport.request_json("GET", "/y", policy=RequestPolicy())
    session.get.return_value = _response(payload=[1, 2])
    with pytest.raises(MalformedResponse):
        transport.request_json("GET", "/y", policy=RequestPolicy())


def test_typed_errors_are_runtime_errors_for_existing_handlers() -> None:
    assert issubclass(MalformedResponse, RuntimeError)
    assert issubclass(DefiniteRefusal, RuntimeError)


# --- retry rules ----------------------------------------------------------------------------------


def test_a_non_idempotent_request_is_never_retried_even_when_retries_are_requested() -> None:
    session = mock.Mock()
    session.post.side_effect = requests.exceptions.ReadTimeout("slow")
    sleeps: list[float] = []
    transport = HttpTransport("http://h", session, sleep=sleeps.append)
    with pytest.raises(DispatchOutcomeUnknown):
        transport.send("POST", "/prompt", policy=RequestPolicy(idempotent=False, retries=5))
    assert session.post.call_count == 1
    assert sleeps == []


def test_an_idempotent_request_retries_unavailable_and_unknown_failures_then_succeeds() -> None:
    session = mock.Mock()
    session.get.side_effect = [
        requests.exceptions.ConnectTimeout("a"),
        requests.exceptions.ReadTimeout("b"),
        _response(payload={"ok": True}),
    ]
    sleeps: list[float] = []
    transport = HttpTransport("http://h", session, sleep=sleeps.append)
    result = transport.request_json(
        "GET", "/y", policy=RequestPolicy(idempotent=True, retries=2, retry_delay_seconds=0.25)
    )
    assert result == {"ok": True}
    assert session.get.call_count == 3
    assert sleeps == [0.25, 0.25]


def test_a_refusal_is_the_servers_answer_and_is_not_retried() -> None:
    session = mock.Mock()
    session.get.return_value = _response(404)
    transport = HttpTransport("http://h", session, sleep=lambda _s: None)
    with pytest.raises(DefiniteRefusal):
        transport.send("GET", "/y", policy=RequestPolicy(idempotent=True, retries=3))
    assert session.get.call_count == 1


def test_retries_exhausted_raise_the_last_typed_error() -> None:
    session = mock.Mock()
    session.get.side_effect = requests.exceptions.ConnectTimeout("never")
    transport = HttpTransport("http://h", session, sleep=lambda _s: None)
    with pytest.raises(EndpointUnavailable):
        transport.send("GET", "/y", policy=RequestPolicy(idempotent=True, retries=2))
    assert session.get.call_count == 3
