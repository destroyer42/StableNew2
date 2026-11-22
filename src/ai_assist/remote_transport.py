"""Deadline-bounded HTTP over the operator-managed IPv4 loopback SSH forward."""

from __future__ import annotations

import errno
import http.client
import io
import socket
import time
from collections.abc import Buffer, Callable
from typing import BinaryIO

from src.ai_assist.contracts import AiCancelToken

HOST = "127.0.0.1"
PORT = 11435
POLL_SECONDS = 0.2
MAX_REQUEST_BYTES = 512 * 1024
MAX_WIRE_BYTES = 1024 * 1024
_DISCONNECT_ERRORS = {
    errno.ECONNABORTED,
    errno.ECONNREFUSED,
    errno.ECONNRESET,
    errno.EHOSTUNREACH,
    errno.ENETDOWN,
    errno.ENETUNREACH,
    errno.EPIPE,
    10051,  # WSAENETUNREACH
    10053,  # WSAECONNABORTED
    10054,  # WSAECONNRESET
    10061,  # WSAECONNREFUSED
    10065,  # WSAEHOSTUNREACH
}


class TransportFailure(Exception):
    """Fixed failure category. Only disconnection is eligible for local fallback."""


Transport = Callable[[str, bytes | None, AiCancelToken, float, int], tuple[int, bytes]]


def _remaining(token: AiCancelToken, deadline: float) -> float:
    if token.cancelled:
        raise TransportFailure("cancelled")
    remaining = deadline - time.monotonic()
    if remaining <= 0:
        raise TransportFailure("timeout")
    return min(remaining, POLL_SECONDS)


class _DeadlineReader(io.RawIOBase):
    def __init__(self, connection: socket.socket, token: AiCancelToken, deadline: float) -> None:
        super().__init__()
        self.connection = connection
        self.token = token
        self.deadline = deadline
        self.total = 0
        self.eof = False

    def close(self) -> None:
        self.connection.close()
        super().close()

    def readable(self) -> bool:
        return True

    def readinto(self, buffer: Buffer) -> int:
        # A socket timeout alone lets a drip-fed HTTP header or chunk extend the request indefinitely.
        while True:
            self.connection.settimeout(_remaining(self.token, self.deadline))
            try:
                size = self.connection.recv_into(buffer)
            except TimeoutError:
                continue
            self.eof = size == 0
            self.total += size
            if self.total > MAX_WIRE_BYTES:
                raise TransportFailure("response_too_large")
            return size


class _RequestSocket(socket.socket):
    def __init__(self, token: AiCancelToken, deadline: float) -> None:
        super().__init__(socket.AF_INET, socket.SOCK_STREAM)
        self.token = token
        self.deadline = deadline
        self.reader: _DeadlineReader | None = None

    def makefile(  # type: ignore[override]
        self, mode: str = "rb", *args: object, **kwargs: object
    ) -> BinaryIO:
        # HTTPResponse uses one read-only socket file. The enclosing request owns the socket.
        reader_socket = socket.socket(
            self.family, self.type, self.proto, fileno=socket.dup(self.fileno())
        )
        self.reader = _DeadlineReader(reader_socket, self.token, self.deadline)
        return io.BufferedReader(self.reader)


def loopback_request(
    path: str, body: bytes | None, token: AiCancelToken, timeout: float, limit: int
) -> tuple[int, bytes]:
    if (path, body is None) not in {
        ("/api/version", True),
        ("/api/tags", True),
        ("/api/generate", False),
    }:
        raise TransportFailure("invalid_endpoint")
    if body is not None and len(body) > MAX_REQUEST_BYTES:
        raise TransportFailure("request_too_large")
    deadline = time.monotonic() + timeout
    _remaining(token, deadline)
    client = http.client.HTTPConnection(HOST, PORT, timeout=POLL_SECONDS)
    client.auto_open = False  # Never reconnect and never retry a dispatched request.
    connection = _RequestSocket(token, deadline)
    disconnected = "disconnected"
    try:
        with connection:
            connection.settimeout(_remaining(token, deadline))
            connection.connect((HOST, PORT))
            client.sock = connection
            connection.settimeout(_remaining(token, deadline))
            headers = {"Connection": "close", "Accept": "application/json"}
            if body is not None:
                headers["Content-Type"] = "application/json"
                # Once a POST may have reached Ollama, a disconnect cannot prove that it never started.
                disconnected = "response_lost"
            client.request("GET" if body is None else "POST", path, body, headers)
            with client.getresponse() as response:
                if response.status != 200:
                    return response.status, b""
                if response.length is not None and response.length > limit:
                    raise TransportFailure("response_too_large")
                document = response.read(limit + 1)
                if len(document) > limit:
                    raise TransportFailure("response_too_large")
                if response.length:
                    raise TransportFailure(disconnected)
                _remaining(token, deadline)
                return response.status, document
    except http.client.RemoteDisconnected:
        raise TransportFailure(disconnected) from None
    except http.client.IncompleteRead:
        # CPython also raises IncompleteRead for an invalid chunk-size line.
        reader = connection.reader
        raise TransportFailure(
            disconnected if reader is not None and reader.eof else "invalid_http"
        ) from None
    except TimeoutError:
        raise TransportFailure("timeout") from None
    except OSError as exc:
        reason = disconnected if exc.errno in _DISCONNECT_ERRORS else "transport_error"
        raise TransportFailure(reason) from None
    except (http.client.HTTPException, ValueError):
        raise TransportFailure("invalid_http") from None
    finally:
        client.close()
